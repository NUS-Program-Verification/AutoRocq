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

from agent.context_search import CoqCommandSearch
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
    """The whole point: a backend failure must not score like a real hit."""
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
        assert result.relevance_score == 0.0, f"{label}: scored {result.relevance_score}"
        assert result.metadata["failed"] is True, label
        assert error in result.content, f"{label}: {result.content!r}"
        assert result.original_size == 0 and result.result_size == 0, label
        print(f"  ✅ {label:18} relevance=0.0, flagged failed")


def test_successful_query_is_unaffected():
    """The success path must be exactly as it was."""
    content = "Z.abs_0: Z.abs 0 = 0\nZ.abs_nonneg: forall n : int, 0 <= Z.abs n"
    result = CoqCommandSearch(FakeCoq(content)).search_lemma("Z.abs")

    assert result.relevance_score == 1.0
    assert result.metadata.get("failed") is None
    assert result.content == content
    assert result.original_size == len(content)

    # A genuine empty result stays scored 0.0, as before.
    empty = CoqCommandSearch(FakeCoq("No results found.")).search_lemma("nope")
    assert empty.relevance_score == 0.0
    assert empty.metadata.get("failed") is None, "an empty result is not a failure"
    print("  ✅ success -> 1.0; genuine empty -> 0.0 but not flagged failed")


TESTS = [
    test_extraction_failure_returns_none_and_records_why,
    test_genuinely_empty_search_is_not_a_failure,
    test_inaccessible_aux_file_returns_none,
    test_malformed_queries_return_none,
    test_print_branch_failure_returns_none,
    test_failed_query_never_reaches_the_llm_as_a_good_result,
    test_successful_query_is_unaffected,
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
