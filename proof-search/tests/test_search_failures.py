"""
CoqInterface.search() must distinguish "found nothing" from "broke".

search() used to encode every failure as ordinary text -- "aux_file not
accessible", "Query error: ...", "Error executing print: ...". Those strings
flowed into CoqCommandSearch._create_search_result, which scores anything not
containing "No results found" as relevance 1.0, so a broken backend reached the
LLM looking like a confident search hit. search() now returns None on failure
with the reason on last_error, the same signal apply_tactic already uses.

These are pure unit tests: no Rocq process, no coq-lsp, no example file.
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from agent.context_manager import ContextManager
from agent.context_search import CoqCommandSearch, SearchResult
from backend.coq_interface import CoqInterface
from utils.logger import setup_logger


class FakeAuxFile:
    """Just the surface _run_aux_query touches."""

    def __init__(self, queries=None, raises=None, diagnostics=""):
        self._queries = queries or []
        self._raises = raises
        self._diagnostics = diagnostics

    def _AuxFile__get_queries(self, _kind):
        if self._raises is not None:
            raise self._raises
        return self._queries

    def read(self):
        return "Require Import ZArith.\nOpen Scope Z_scope.\n"

    def get_diagnostics(self, _cmd, _identifier, _line):
        if self._raises is not None:
            raise self._raises
        return self._diagnostics


class FakeCoq:
    """A CoqInterface double for the CoqCommandSearch tests."""

    def __init__(self, result, error=None):
        self._result = result
        self._error = error
        self.proof_file = object()  # non-None, so CoqCommandSearch skips load()

    def search(self, _query):
        return self._result

    def get_last_error(self):
        return self._error


def bare_interface():
    """A CoqInterface with only the attributes these paths read."""
    coq = object.__new__(CoqInterface)
    coq.logger = setup_logger("test_search_failures")
    coq.timeout = 1  # keep the poll deadline short
    coq.last_error = None
    return coq


def test_extraction_failure_returns_none_and_records_why():
    """An exception mid-extraction must not look like an empty result set."""
    coq = bare_interface()
    aux = FakeAuxFile(raises=RuntimeError("lsp endpoint died"))

    result = coq._run_aux_query(aux, "Search Z.abs.", 0)

    assert result is None, f"expected None on failure, got {result!r}"
    assert "lsp endpoint died" in coq.get_last_error(), coq.get_last_error()
    print(f"  ✅ extraction failure -> None, last_error={coq.get_last_error()!r}")


def test_genuinely_empty_search_is_not_a_failure():
    """Nothing matched is a successful query, and must stay a string."""
    coq = bare_interface()
    aux = FakeAuxFile(queries=[])

    result = coq._run_aux_query(aux, "Search Z.abs.", 0)

    assert result == "No results found.", f"got {result!r}"
    assert coq.get_last_error() is None, coq.get_last_error()
    print("  ✅ empty search -> 'No results found.', no error recorded")


def test_inaccessible_aux_file_returns_none():
    coq = bare_interface()
    coq.proof_file = object()  # has no _ProofFile__aux_file

    result = coq.search("Search Z.abs.")

    assert result is None, f"got {result!r}"
    assert coq.get_last_error() == "aux_file not accessible"
    print("  ✅ inaccessible aux_file -> None, last_error='aux_file not accessible'")


def test_malformed_queries_return_none():
    """Every remaining encoded-failure string is now a None plus last_error."""
    cases = [
        ("", "Empty query"),
        ("Search .", "No search term provided"),
        ("Frobnicate foo.", "Unsupported query type: frobnicate"),
    ]
    for query, expected_error in cases:
        coq = bare_interface()
        result = coq._run_aux_query(FakeAuxFile(), query, 0)
        assert result is None, f"{query!r}: got {result!r}"
        assert coq.get_last_error() == expected_error, coq.get_last_error()
        print(f"  ✅ {query!r:18} -> None, last_error={expected_error!r}")


def test_print_branch_failure_returns_none():
    coq = bare_interface()
    aux = FakeAuxFile(raises=RuntimeError("diagnostics unavailable"))

    result = coq._run_aux_query(aux, "Print nat.", 0)

    assert result is None, f"got {result!r}"
    assert "diagnostics unavailable" in coq.get_last_error(), coq.get_last_error()
    print(f"  ✅ print failure -> None, last_error={coq.get_last_error()!r}")


def test_failed_query_never_reaches_the_llm_as_a_good_result():
    """The whole point: a backend failure must not look like a real hit."""
    error = "Error executing Search: lsp endpoint died"
    coq_search = CoqCommandSearch(FakeCoq(None, error))

    for label, result in [
        ("search_lemma", coq_search.search_lemma("Z.abs", "0 <= Z.abs x")),
        ("search_pattern", coq_search.search_pattern("(_ <= _)", "x <= y")),
        ("print_definition", coq_search.print_definition("nat")),
        ("about_identifier", coq_search.about_identifier("Z.abs")),
        ("check_term", coq_search.check_term("nat")),
        ("locate_definition", coq_search.locate_definition("le")),
        ("print_assumptions", coq_search.print_assumptions("Z.abs")),
        ("auto_search", coq_search.auto_search("Search Z.abs.")),
    ]:
        assert result.content.startswith("Query failed:"), f"{label}: {result.content!r}"
        assert error in result.content, f"{label}: {result.content!r}"
        assert result.metadata["error"] == error, label
        assert result.original_size == 0 and result.result_size == 0, label
        print(f"  ✅ {label:18} content says it failed, reason in metadata")


def test_successful_query_is_unaffected():
    """The success path must be exactly as it was."""
    content = "Z.abs_0: Z.abs 0 = 0\nZ.abs_nonneg: forall n : int, 0 <= Z.abs n"
    result = CoqCommandSearch(FakeCoq(content)).search_lemma("Z.abs")

    assert result.content == content
    assert result.metadata.get("error") is None
    assert result.original_size == len(content)

    # A genuine empty result is a success. It carries Rocq's own wording and
    # records no error, and that is what tells it apart from a failed query.
    empty = CoqCommandSearch(FakeCoq("No results found.")).search_lemma("nope")
    assert empty.content == "No results found."
    assert empty.metadata.get("error") is None, "an empty result is not a failure"
    print("  ✅ success -> content passed through; genuine empty -> 'No results found.'")


class FakeSearch:
    """The ContextSearch surface _execute_context_search touches."""

    def __init__(self, result):
        self.result = result
        self.goal_contexts = []

    def search(self, query, goal_context=""):
        self.goal_contexts.append(goal_context)
        return self.result


class StubManager:
    """Just enough ContextManager to call the method unbound."""

    GOAL = "0 <= Z.abs x"

    def __init__(self, result):
        self.context_search = FakeSearch(result)
        self.coq = self
        self.logger = setup_logger("StubManager")

    def get_goal_str(self):
        return self.GOAL


FAILED = SearchResult(
    content="Query failed: lsp endpoint died",
    source='coq_command',
    metadata={'query': 'Search Z.abs.', 'type': 'direct_search', 'error': 'lsp endpoint died'},
)
EMPTY = SearchResult(
    content="No results found.",
    source='coq_command',
    metadata={'query': 'Search nope.', 'type': 'direct_search'},
    result_size=len("No results found."),
)
HIT = SearchResult(
    content="Z.abs_nonneg: forall n : Z, 0 <= Z.abs n",
    source='coq_command',
    metadata={'query': 'Search Z.abs.', 'type': 'direct_search'},
    result_size=40,
)


def run_query(result, query="Search Z.abs."):
    stub = StubManager(result)
    text, success = ContextManager._execute_context_search(stub, query)
    return stub, text, success


def test_every_path_out_of_execute_context_search_returns_a_pair():
    """The caller unpacks two values; one branch used to return a bare string.

    `search_result, success = self._execute_context_search(...)` against a
    string raises "too many values to unpack", so the one path meant to report
    an error was the one path that could not.
    """
    for label, result in [("failed", FAILED), ("empty", EMPTY), ("hit", HIT)]:
        value = ContextManager._execute_context_search(StubManager(result), "Search Z.abs.")
        assert isinstance(value, tuple) and len(value) == 2, f"{label}: {value!r}"
        text, success = value
        assert isinstance(text, str) and isinstance(success, bool), f"{label}: {value!r}"

    stub = StubManager(HIT)
    stub.context_search = None
    text, success = ContextManager._execute_context_search(stub, "Search Z.abs.")
    assert success is False and "not available" in text
    print("  ✅ all four paths return (str, bool)")


def test_a_failed_query_reaches_the_model_as_a_failure():
    """It used to be flattened into "No results found." -- the opposite claim."""
    _, text, success = run_query(FAILED)

    assert success is False
    assert "lsp endpoint died" in text, text
    assert "No results found" not in text, text
    print(f"  ✅ failure handed over as {text!r}")


def test_an_empty_result_is_reported_empty_and_a_hit_is_handed_over_whole():
    _, empty_text, empty_ok = run_query(EMPTY)
    assert (empty_text, empty_ok) == ("No results found.", False)

    _, hit_text, hit_ok = run_query(HIT)
    assert hit_ok is True
    assert hit_text == HIT.content, hit_text
    print("  ✅ empty -> (No results found., False); hit -> (content, True)")


def test_the_goal_is_passed_to_the_search_so_ranking_has_something_to_score():
    """Without it, a summarized result is whatever order Rocq printed."""
    stub, _, _ = run_query(HIT)
    assert stub.context_search.goal_contexts == [StubManager.GOAL]
    print("  ✅ goal context forwarded to search()")


TESTS = [
    test_extraction_failure_returns_none_and_records_why,
    test_genuinely_empty_search_is_not_a_failure,
    test_inaccessible_aux_file_returns_none,
    test_malformed_queries_return_none,
    test_print_branch_failure_returns_none,
    test_failed_query_never_reaches_the_llm_as_a_good_result,
    test_successful_query_is_unaffected,
    test_every_path_out_of_execute_context_search_returns_a_pair,
    test_a_failed_query_reaches_the_model_as_a_failure,
    test_an_empty_result_is_reported_empty_and_a_hit_is_handed_over_whole,
    test_the_goal_is_passed_to_the_search_so_ranking_has_something_to_score,
]


if __name__ == "__main__":
    failures = []
    for test in TESTS:
        print(f"\n🧪 {test.__name__}")
        try:
            test()
        except Exception as e:
            failures.append((test.__name__, e))
            print(f"  ❌ {e}")

    print(f"\n🏁 {len(TESTS) - len(failures)}/{len(TESTS)} tests passed")
    for name, error in failures:
        print(f"   ❌ {name}: {error}")
    sys.exit(1 if failures else 0)
