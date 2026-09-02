"""Test live Rocq searches and deterministic result reduction."""

import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

# Add the parent directory to the path so we can import from agent
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from agent.context_manager import ContextManager
from agent.context_search import CoqCommandSearch, ResultReducer, SearchResult
from agent.proof_controller import ProofController
from backend.coq_interface import CoqInterface
from tests.test_utils import configure_test_library, temp_example_copy
from utils.config import ProofAgentConfig
from utils.logger import setup_logger

# Work on a throwaway copy: CoqInterface.load() pops the trailing "Admitted."
# and coqpyt writes that change straight back to the file on disk, which would
# otherwise leave the tracked example without its proof terminator.
coq_file = temp_example_copy("main_loop_invariant_2_established_Coq.v")
config_file = PROJECT_ROOT / "configs" / "default_config.json"

# Query -> stable fragments expected in the result. Abs.Abs_pos checks that the
# configured benchmark library is on the Rocq load path.
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
    config = ProofAgentConfig.from_file(str(config_file))
    return configure_test_library(config)


def assert_real_result(query, result):
    """Fail on anything that is not a genuine query hit.

    CoqInterface.search() returns None on failure (reason on last_error), and
    CoqCommandSearch turns that into content prefixed "Query failed:". Neither
    is a result, and nor is a successful-but-empty "No results found." for the
    queries asserted here.
    """
    assert result is not None, f"{query}: query failed (search returned None)"
    assert result, f"{query}: empty result"
    assert not result.startswith("Query failed:"), f"{query}: {result}"
    assert result != "No results found.", f"{query}: query found nothing"


_interface = None


def get_interface():
    """Return the shared query session, creating it on first use."""
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
        try:
            assert coq.load(), f"CoqInterface.load() failed: {coq.get_last_error()}"
        except BaseException:
            coq.close()
            raise
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


class FakeCoq:
    def __init__(self, result, error=None):
        self.result = result
        self.error = error
        self.proof_file = object()

    def search(self, _query):
        return self.result

    def get_last_error(self):
        return self.error


def test_failed_command_search_preserves_the_error():
    error = "Error executing Search: lsp endpoint died"
    result = CoqCommandSearch(FakeCoq(None, error)).auto_search("Search Z.abs.")

    assert result.metadata["error"] == error
    assert result.content == f"Query failed: {error}"
    assert result.original_size == 0 and result.result_size == 0


def make_context_manager(result):
    manager = object.__new__(ContextManager)
    manager.context_search = FakeCoq(result)
    manager.enable_context_search = True
    manager.last_action_info = {}
    manager.logger = setup_logger("test_context_search")
    return manager


def test_context_manager_distinguishes_failure_from_empty_results():
    failure = SearchResult(
        content="Query failed: lsp endpoint died",
        source="coq_command",
        metadata={"error": "lsp endpoint died"},
    )
    empty = SearchResult(
        content="No results found.",
        source="coq_command",
        metadata={},
        result_size=len("No results found."),
    )

    for result, expected_success in [(failure, False), (empty, True)]:
        response, success = make_context_manager(result).handle_query_call(
            "Search Z.abs.", "call-1"
        )

        assert success is expected_success
        assert result.content in response


class FakeContextManager:
    def __init__(self, success):
        self.success = success

    def handle_query_call(self, _query, _tool_call_id):
        return "query response", self.success


def test_proof_controller_logs_query_status():
    for query_success in [True, False]:
        controller = object.__new__(ProofController)
        controller.context_manager = FakeContextManager(query_success)
        controller.query_commands = []
        controller.global_step_id = 1
        controller.logger = Mock()

        response = controller._run_query("Search Z.abs.", "call-1")

        assert response == "query response"
        assert controller.query_commands == ["Search Z.abs."]
        if query_success:
            controller.logger.info.assert_called_once()
            controller.logger.warning.assert_not_called()
        else:
            controller.logger.warning.assert_called_once()
            controller.logger.info.assert_not_called()


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
        assert not result.metadata.get("error"), f"{label}: {result.metadata}"
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


def test_a_search_with_no_hits_reports_no_results():
    """A miss is told apart from a hit by its content, nothing else.

    _create_search_result passes Rocq's own wording through, so "No results
    found." is the whole miss signal. Ranking of real hits is a separate thing
    and lives in ResultReducer._rank_entries.
    """
    coq_search = CoqCommandSearch(get_interface())

    hit = coq_search.search_lemma("Z.abs", "0 <= Z.abs x")
    assert hit.source == "coq_command"
    assert hit.result_size > 0 and "No results found" not in hit.content

    miss = coq_search.search_lemma("definitely_not_a_lemma_xyz")
    assert "No results found" in miss.content, (
        f"a search with no hits should say so, got {miss.content[:200]!r}"
    )
    print(f"\n🎯 hit={hit.result_size} chars, miss={miss.content.strip()!r}")


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
    test_failed_command_search_preserves_the_error,
    test_context_manager_distinguishes_failure_from_empty_results,
    test_proof_controller_logs_query_status,
    test_coq_setup,
    test_query_commands_return_real_results,
    test_command_search_returns_real_content,
    test_large_results_are_summarized,
    test_a_search_with_no_hits_reports_no_results,
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
