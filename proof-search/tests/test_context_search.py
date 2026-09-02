"""
Test script for Context Search Module with Adaptive Result Reduction
Tests full Coq command search functionality: Search/Print/Check/About/Locate/Print Assumptions
with adaptive size reduction strategies.

Two levels, deliberately kept apart:

* The query tests run against a real coq-lsp session with the libframac
  realizations on the load path, and assert on the *content* that comes back.
  That is what proves context search reaches Rocq and can see the library.
* The ranking and reduction tests call ResultReducer directly with synthetic
  input. Which
  size band a live query lands in is decided purely by len(content), and real
  output sits close enough to the boundaries that library or Rocq churn would
  silently move it -- Search to_sint32. is 503 characters against a 500-char
  boundary. Driving the reducer directly pins every band deterministically.
"""

import sys
from pathlib import Path

import pytest

# Add the parent directory to the path so we can import from agent
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from agent.context_search import CoqCommandSearch, ResultReducer
from backend.coq_interface import CoqInterface
from tests.test_utils import temp_example_copy
from utils.config import ProofAgentConfig

# Work on a throwaway copy: CoqInterface.load() pops the trailing "Admitted."
# and coqpyt writes that change straight back to the file on disk, which would
# otherwise leave the tracked example without its proof terminator.
coq_file = temp_example_copy("main_loop_invariant_2_established_Coq.v")
config_file = PROJECT_ROOT / "configs" / "default_config.json"

# query -> fragments the result must contain. Substrings, never sizes or exact
# text: Rocq renders the same term differently depending on which notations are
# in scope (nat -> nat vs nat → nat under Utf8), and sizes drift with the
# stdlib. "Abs.Abs_pos" comes from libautorocq/int/Abs.v, so it fails if the
# libframac mapping is not actually on the load path.
QUERY_EXPECTATIONS = [
    ("Search Z.abs.", ["Z.abs_0: Z.abs 0 = 0", "Abs.Abs_pos"]),
    ("Search to_sint32.", ["is_to_sint32", "id_sint32"]),
    ("Search is_uint32.", ["is_to_uint32", "id_uint32"]),
    ("Print nat.", ["Inductive nat : Set"]),
    ("Print bool.", ["Inductive bool : Set", "true : bool"]),
    ("Print Assumptions Z.abs.", ["Closed under the global context"]),
    ("Locate le.", ["Corelib.Init.Peano.le"]),
    ("About Z.abs.", ["Z.abs", "not universe polymorphic"]),
    ("About to_sint32.", ["to_sint32", "not universe polymorphic"]),
    ("Check nat.", ["nat", ": Set"]),
    ("Check bool.", ["bool", ": Set"]),
    ("Check to_sint32.", ["to_sint32", "int -> int"]),
]

# method, argument, goal context, fragments the content must contain
SEARCH_EXPECTATIONS = [
    ("search_lemma", "Z.abs", "0 <= Z.abs x", ["Z.abs"]),
    ("search_lemma", "to_sint32", "is_sint32 (to_sint32 x)", ["to_sint32"]),
    ("search_pattern", "(_ <= _)", "x <= y -> y <= z -> x <= z", ["<="]),
    ("print_definition", "nat", "", ["Inductive nat : Set"]),
    ("print_definition", "bool", "", ["Inductive bool : Set"]),
    ("check_term", "to_sint32", "", ["to_sint32"]),
    ("about_identifier", "Z.abs", "", ["Z.abs"]),
    ("locate_definition", "le", "", ["le"]),
    ("auto_search", "Print bool.", "", ["Inductive bool : Set"]),
]

# Entries shaped like _parse_search_entries output, for the ranking tests.
RANK_ENTRIES = [
    {"name": "Z.abs_nonneg", "signature": "forall n : int, 0 <= Z.abs n", "module": "Z"},
    {"name": "Zis_gcd_0_abs", "signature": "forall a : int, Zis_gcd 0 a", "module": "Znumtheory"},
    {"name": "le_refl", "signature": "forall n : int, n <= n", "module": "Z"},
]

# len(content), query_type -> the band ResultReducer must pick.
# Boundaries matter: max_small_result is inclusive, so 500 is still "none" and
# 501 is the first medium result.
REDUCTION_BANDS = [
    (100, "search_lemma", "none"),
    (100, "print_definition", "none"),
    (500, "search_lemma", "none"),
    (500, "print_definition", "none"),
    (501, "search_lemma", "boundary_aware_truncation"),
    (501, "print_definition", "simple_truncation"),
    (750, "search_lemma", "boundary_aware_truncation"),
    (1000, "search_lemma", "boundary_aware_truncation"),
    (1000, "print_definition", "simple_truncation"),
    (1001, "search_lemma", "structured_summary"),
    (1001, "print_definition", "boundary_aware_truncation"),
    (5000, "search_lemma", "structured_summary"),
    (5000, "print_definition", "boundary_aware_truncation"),
]


def load_config():
    return ProofAgentConfig.from_file(str(config_file))


# CoqInterface.search() never raises -- it returns its failures as ordinary
# strings, so a test that only checks "did a string come back" passes on every
# one of them. See backend/coq_interface.py::search / _run_aux_query.
QUERY_ERRORS = (
    "aux_file not accessible",
    "Empty query",
    "No search term provided",
    "No results found.",
    "Unsupported query type:",
    "Error executing ",
    "Query error:",
)


def assert_real_result(query, result):
    """Fail on the failure strings search() returns in place of raising."""
    assert result, f"{query}: empty result"
    for sentinel in QUERY_ERRORS:
        assert not result.startswith(sentinel), f"{query}: query failed -> {result!r}"


_interface = None


def get_interface():
    """One coq-lsp session, shared by every live test.

    Starting coq-lsp and replaying the goal file costs most of the runtime, and
    none of the live tests changes the proof state -- they only issue queries --
    so one session serves all of them. Torn down explicitly by the fixture
    below (or by __main__): closing it from an atexit hook instead deadlocks,
    because coqpyt's LSP client shuts its threads down during interpreter exit.

    The workspace and library_paths are not optional: without the libframac
    mapping the goal file's statement does not typecheck, no proof is opened,
    and load() dies in coqpyt with "pop from empty list".
    """
    global _interface
    if _interface is None:
        config = load_config()
        coq = CoqInterface(
            file_path=str(coq_file),
            workspace=config.coq.workspace or str(coq_file.parent),
            library_paths=config.coq.library_paths,
            auto_setup_coqproject=config.coq.auto_setup_coqproject,
            coqproject_extra_options=config.coq.coqproject_extra_options,
            timeout=config.coq.timeout,
        )
        assert coq.load(), f"CoqInterface.load() failed: {coq.get_last_error()}"
        print("✅ CoqInterface loaded")
        _interface = coq
    return _interface


def close_interface():
    global _interface
    if _interface is not None:
        _interface.close()
        _interface = None


@pytest.fixture(scope="module", autouse=True)
def _shared_interface():
    """Close the shared session once this module's tests are done."""
    yield
    close_interface()


def make_search_output(size):
    """A block of Search-shaped entries of exactly `size` characters."""
    entry = "Lemma foo_bar_baz : forall x y : Z, x + y = y + x\n"
    return (entry * (size // len(entry) + 1))[:size]


def test_coq_setup():
    """The fixture file and every configured library have to actually be there."""
    print("\n🔧 Checking CoqInterface Setup...")

    assert coq_file.exists(), f"missing fixture: {coq_file}"
    content = coq_file.read_text()
    print(f"📄 Proof file: {coq_file.name}, {len(content)} characters")
    assert "Proof." in content, "fixture has no proof to open"

    library_paths = load_config().coq.library_paths
    assert library_paths, "default_config.json declares no library paths"
    for lib in library_paths:
        lib_path = Path(lib["path"])
        assert lib_path.is_dir(), f"{lib['name']}: {lib_path} is not a directory"
        lib_files = list(lib_path.rglob("*.v"))
        assert lib_files, f"{lib['name']}: no .v files under {lib_path}"
        print(f"📚 {lib['name']}: {len(lib_files)} .v files under {lib_path}")


def test_query_commands_return_real_results():
    """Every query command has to come back with the content it should."""
    print("\n🔍 Testing full query command functionality:")

    coq = get_interface()
    for query, expected in QUERY_EXPECTATIONS:
        result = coq.search(query)
        assert_real_result(query, result)
        for fragment in expected:
            assert fragment in result, (
                f"{query}: expected {fragment!r} in result, got {result[:300]!r}"
            )
        print(f"  ✅ {query:26} {len(result):6d} chars")


def test_command_search_returns_real_content():
    """The same, through CoqCommandSearch, with its size bookkeeping checked."""
    print("\n🔬 Testing CoqCommandSearch:")

    coq_search = CoqCommandSearch(get_interface())
    small_result_limit = ResultReducer().max_small_result

    for method_name, argument, goal_context, expected in SEARCH_EXPECTATIONS:
        method = getattr(coq_search, method_name)
        result = method(argument) if not goal_context else method(argument, goal_context)

        label = f"{method_name}({argument})"
        assert_real_result(label, result.content)
        for fragment in expected:
            assert fragment in result.content, (
                f"{label}: expected {fragment!r}, got {result.content[:300]!r}"
            )

        assert result.original_size > 0, f"{label}: original_size not recorded"
        assert result.result_size <= result.original_size, (
            f"{label}: reduction grew the result, "
            f"{result.original_size} -> {result.result_size}"
        )
        # Small results are the one band a live query can pin down safely:
        # under the threshold nothing may be touched at all.
        if result.original_size <= small_result_limit:
            assert result.reduction_applied in (None, "none"), (
                f"{label}: {result.original_size} chars should not be reduced, "
                f"got {result.reduction_applied}"
            )
            assert result.result_size == result.original_size

        print(
            f"  ✅ {label:34} {result.original_size:6d} -> {result.result_size:6d} "
            f"[{result.reduction_applied or 'none'}]"
        )


def test_large_results_are_summarized():
    """A genuinely large search must be cut down, not passed through."""
    coq_search = CoqCommandSearch(get_interface())
    result = coq_search.search_pattern("(_ <= _)", "x <= y -> y <= z -> x <= z")

    assert_real_result("search_pattern((_ <= _))", result.content)
    assert result.original_size > 1000, (
        f"expected a large result to summarize, got {result.original_size} chars"
    )
    assert result.reduction_applied == "structured_summary"
    assert result.result_size < result.original_size
    print(
        f"\n💾 search_pattern((_ <= _)): {result.original_size} -> "
        f"{result.result_size} chars [{result.reduction_applied}]"
    )


def test_relevance_score_flags_empty_results():
    """relevance_score is a hit/miss flag, not a ranking score.

    _create_search_result sets it to 1.0 whenever the content does not say
    "No results found" and 0.0 otherwise, so that is all it can be asserted to
    mean. The actual ranking lives in ResultReducer._rank_entries.
    """
    coq_search = CoqCommandSearch(get_interface())

    hit = coq_search.search_lemma("Z.abs", "0 <= Z.abs x")
    assert hit.relevance_score == 1.0
    assert hit.source == "coq_command"

    miss = coq_search.search_lemma("definitely_not_a_lemma_xyz")
    assert miss.relevance_score == 0.0, (
        f"a search with no hits should score 0.0, got {miss.relevance_score}"
    )
    print(f"\n🎯 relevance: hit={hit.relevance_score} miss={miss.relevance_score}")


def test_goal_context_changes_the_summary():
    """The goal context has to actually reach the ranking and change the output."""
    coq_search = CoqCommandSearch(get_interface())

    # One reducer per call: _structured_summarization mutates result_hit_count,
    # so a shared instance would make this order-dependent.
    def summarize(goal_context):
        return CoqCommandSearch(get_interface()).search_pattern(
            "(_ <= _)", goal_context
        ).content

    no_context = summarize("")
    decidable = summarize("decidable comparison of two integers")
    logarithms = summarize("log2_land and land_ones bounds")

    assert decidable != no_context, "goal context did not reach the ranking"
    assert logarithms != no_context, "goal context did not reach the ranking"
    assert decidable != logarithms, "two different goal contexts produced the same summary"
    print("\n🎯 goal context changes the summary: 3 distinct summaries for one query")


def test_keyword_extraction():
    """The keyword filter is what the whole ranking is built on."""
    reducer = ResultReducer()
    keywords = reducer._extract_keywords("forall x y, 0 <= z.abs x")

    assert "forall" not in keywords, "Coq keywords must be dropped"
    assert "x" not in keywords and "y" not in keywords, "words under 3 chars must be dropped"
    assert "abs" in keywords, "z.abs must contribute 'abs' once punctuation is stripped"
    assert len(keywords) == len(set(keywords)), "keywords must be deduplicated"
    print(f"\n🔑 keywords from a goal: {sorted(keywords)}")


def test_goal_context_reranks_entries():
    """_rank_entries is the actual ranking -- pin it directly.

    Known defect, recorded rather than fixed: _structured_summarization records
    hit counts under hash(frozenset(entry.items())) while _rank_entries reads
    them back under md5(name), so the "exponential decay of frequently
    retrieved results" branch can never fire.
    """
    reducer = ResultReducer()
    names = lambda ranked: [entry["name"] for entry in ranked]

    # No context means no ranking is possible, so the order must survive intact.
    assert names(reducer._rank_entries(RANK_ENTRIES, "")) == names(RANK_ENTRIES)

    # A context naming an entry has to pull that entry to the front.
    gcd_first = names(reducer._rank_entries(RANK_ENTRIES, "Zis_gcd of a and zero"))
    assert gcd_first[0] == "Zis_gcd_0_abs", gcd_first
    abs_first = names(reducer._rank_entries(RANK_ENTRIES, "0 <= Z.abs n nonneg"))
    assert abs_first[0] == "Z.abs_nonneg", abs_first

    # Ranking reorders; it must never drop or duplicate an entry.
    assert sorted(gcd_first) == sorted(names(RANK_ENTRIES))
    print(f"🔀 rerank by context: {gcd_first[0]} vs {abs_first[0]}")


def test_reduction_bands():
    """ResultReducer picks its strategy from len(content) alone -- pin every band.

    Three known oddities are recorded by these expectations rather than fixed
    here, since fixing them changes agent behaviour:
      * boundary_aware_truncation appends its trailing marker without budgeting
        for it, so it can return more than max_size (1001 -> 1036 at cap 1000);
      * simple_truncation on 501-1000 chars appends "... (truncated)" without
        truncating anything, growing the string;
      * a 501-1000 char search result is labelled boundary_aware_truncation
        even though _boundary_aware_truncation returns it untouched.
    """
    print("\n📏 Testing reduction band selection:")
    reducer = ResultReducer()

    assert reducer.reduce_result("", "search_lemma", "") == ("", "none")

    for size, query_type, expected in REDUCTION_BANDS:
        content = make_search_output(size)
        reduced, label = reducer.reduce_result(content, query_type, "commutativity")

        assert label == expected, (
            f"{size} chars as {query_type}: expected {expected}, got {label}"
        )
        if expected == "none":
            assert reduced == content, f"{size} chars must be passed through untouched"
        print(f"  ✅ {size:5d} chars {query_type:18} -> {label:26} {len(reduced):5d} out")


TESTS = [
    test_coq_setup,
    test_query_commands_return_real_results,
    test_command_search_returns_real_content,
    test_large_results_are_summarized,
    test_relevance_score_flags_empty_results,
    test_goal_context_changes_the_summary,
    test_keyword_extraction,
    test_goal_context_reranks_entries,
    test_reduction_bands,
]


if __name__ == "__main__":
    print("🚀 Starting Context Search Tests")
    print("=" * 90)

    failures = []
    try:
        for test in TESTS:
            try:
                test()
            except Exception as e:
                failures.append((test.__name__, e))
                print(f"❌ {test.__name__}: {e}")
    finally:
        close_interface()

    print("\n" + "=" * 90)
    print(f"🏁 {len(TESTS) - len(failures)}/{len(TESTS)} tests passed")
    for name, error in failures:
        print(f"   ❌ {name}: {error}")
    sys.exit(1 if failures else 0)
