"""Test CoqInterface.search() results and failure reporting against Rocq."""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import pytest

from backend.coq_interface import CoqInterface
from tests.test_utils import skip_if_libraries_missing, temp_example_copy
from utils.config import ProofAgentConfig
from utils.logger import setup_logger

coq_file = temp_example_copy("main_loop_invariant_2_established_Coq.v")
config_file = PROJECT_ROOT / "configs" / "default_config.json"

# query -> a fragment the output must contain, or None when the query returns a
# large multi-entry result whose exact members drift with the stdlib version.
# Fragments only, never sizes: Rocq renders terms differently depending on which
# notations are in scope.
QUERY_EXPECTATIONS = [
    # Search
    ("Search Z.abs", "Z.abs_0"),
    ("Search (_ <= _)", "Z.le_refl"),
    ("Search Z.mul", None),
    ("Search nat", None),
    ("Search (_ + _)", "Z.add_0_r"),
    # Print
    ("Print Z.abs", "Z.abs ="),
    ("Print nat", "Inductive nat : Set"),
    ("Print bool", "Inductive bool : Set"),
    ("Print option", "Inductive option"),
    # Print Assumptions
    ("Print Assumptions Z.abs", "Closed under the global context"),
    # Locate
    ("Locate Z.abs", "Stdlib.ZArith.BinInt.Z.abs"),
    ("Locate le", "Corelib.Init.Peano.le"),
    ("Locate mult", "Corelib.Init.Peano.mult"),
    ("Locate nat", "Corelib.Init.Datatypes.nat"),
    # About
    ("About Z.abs", "Z.abs : int -> int"),
    ("About Z", "Z : Set"),
    ("About nat", "nat : Set"),
    ("About bool", "bool : Set"),
    # Check
    ("Check Z.abs", "int -> int"),
    ("Check nat", ": Set"),
    ("Check bool", ": Set"),
    ("Check (fun x => x + 1)", "fun x : int => x + 1"),
]

LARGE_RESULT_MIN = 1000

_interface = None


def get_interface():
    """Return the shared query session, creating it on first use."""
    global _interface
    if _interface is None:
        config = ProofAgentConfig.from_file(str(config_file))
        skip_if_libraries_missing(config)
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
    yield
    close_interface()


class FakeAuxFile:
    def __init__(self, queries=None, raises=None):
        self._queries = queries or []
        self._raises = raises

    def _AuxFile__get_queries(self, _kind):
        if self._raises is not None:
            raise self._raises
        return self._queries

    def read(self):
        return "Require Import ZArith.\n"

    def get_diagnostics(self, _cmd, _identifier, _line):
        if self._raises is not None:
            raise self._raises
        return ""


def bare_interface():
    coq = object.__new__(CoqInterface)
    coq.logger = setup_logger("test_coq_interface_queries")
    coq.timeout = 0.01
    coq.last_error = None
    return coq


def test_unit_query_failures_return_none_with_a_reason():
    coq = bare_interface()
    result = coq._run_aux_query(
        FakeAuxFile(raises=RuntimeError("lsp endpoint died")),
        "Search Z.abs.",
        0,
    )
    assert result is None
    assert "lsp endpoint died" in coq.get_last_error()

    coq = bare_interface()
    result = coq._run_aux_query(
        FakeAuxFile(raises=RuntimeError("diagnostics unavailable")),
        "Print nat.",
        0,
    )
    assert result is None
    assert "diagnostics unavailable" in coq.get_last_error()

    coq = bare_interface()
    coq.proof_file = object()
    assert coq.search("Search Z.abs.") is None
    assert coq.get_last_error() == "aux_file not accessible"

    for query, expected_error in [
        ("", "Empty query"),
        ("Search .", "No search term provided"),
        ("Frobnicate foo.", "Unsupported query type: frobnicate"),
    ]:
        coq = bare_interface()
        assert coq._run_aux_query(FakeAuxFile(), query, 0) is None
        assert coq.get_last_error() == expected_error


def test_unit_empty_search_is_not_a_failure():
    coq = bare_interface()
    result = coq._run_aux_query(FakeAuxFile(), "Search Z.abs.", 0)

    assert result == "No results found."
    assert coq.get_last_error() is None


def test_every_query_command_returns_real_content():
    """All six command types have to come back with the content they should."""
    print("\n🔍 Testing search() across every query command type:")
    coq = get_interface()
    by_type = {}

    for query, expected in QUERY_EXPECTATIONS:
        result = coq.search(query)

        assert result is not None, f"{query}: search failed -> {coq.get_last_error()}"
        assert result.strip(), f"{query}: empty result"
        assert result != "No results found.", f"{query}: found nothing"

        if expected is None:
            assert len(result) > LARGE_RESULT_MIN, (
                f"{query}: expected a large multi-entry result, got {len(result)} chars"
            )
        else:
            assert expected in result, (
                f"{query}: expected {expected!r}, got {result[:300]!r}"
            )

        cmd_type = query.split()[0].lower()
        by_type[cmd_type] = by_type.get(cmd_type, 0) + 1
        print(f"  ✅ {query:24} {len(result):7d} chars")

    print(f"\n📊 {len(QUERY_EXPECTATIONS)} queries across {len(by_type)} command types:")
    for cmd_type, count in sorted(by_type.items()):
        print(f"   - {cmd_type.upper()}: {count}")


def test_empty_result_is_a_success_not_a_failure():
    """A bare `Print Assumptions` genuinely matches nothing -- that is not an error."""
    coq = get_interface()
    result = coq.search("Print Assumptions")

    assert result == "No results found.", f"got {result!r}"
    assert coq.get_last_error() is None, coq.get_last_error()
    print("\n  ✅ empty result -> 'No results found.', last_error stays None")


def test_failed_query_returns_none_with_a_reason():
    """The failure half of the contract, against a live session."""
    coq = get_interface()
    result = coq.search("Frobnicate foo.")

    assert result is None, f"expected None for an unsupported command, got {result!r}"
    assert coq.get_last_error() == "Unsupported query type: frobnicate", (
        coq.get_last_error()
    )
    print("  ✅ unsupported command -> None, last_error names the command")

    # The session must still work afterwards.
    assert coq.search("Check nat") is not None, "a failed query broke the session"
    print("  ✅ session still usable after a failed query")


TESTS = [
    test_unit_query_failures_return_none_with_a_reason,
    test_unit_empty_search_is_not_a_failure,
    test_every_query_command_returns_real_content,
    test_empty_result_is_a_success_not_a_failure,
    test_failed_query_returns_none_with_a_reason,
]


if __name__ == "__main__":
    print("🔬 CoqInterface query command tests")
    print("=" * 60)

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

    print(f"\n🏁 {len(TESTS) - len(failures)}/{len(TESTS)} tests passed")
    for name, error in failures:
        print(f"   ❌ {name}: {error}")
    sys.exit(1 if failures else 0)
