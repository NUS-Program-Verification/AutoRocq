"""
Entry parsing and ranking on *live* Search output, plus the ContextSearch
wrapper the agent actually calls.

test_context_search.py deliberately drives ResultReducer with synthetic entries
so the size bands stay deterministic; the gap that leaves is that nothing
checks _parse_search_entries against text Rocq really emitted. That is what
this file does, together with ContextSearch.search/execute_coq_query, which
test_context_search.py never touches.

The old version pointed at examples/match_string_assert.v, a fixture that has
never been committed, so it skipped on every run. Even when it did not, it
caught every failure inside its own loop, printed the traceback and carried on,
then returned True -- which pytest ignores.
"""

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from agent.context_search import CoqCommandSearch, ContextSearch, ResultReducer
from backend.coq_interface import CoqInterface
from tests.test_utils import skip_if_libraries_missing, temp_example_copy
from utils.config import ProofAgentConfig

config_file = PROJECT_ROOT / "configs" / "default_config.json"


@pytest.fixture(scope="module")
def coq():
    """One read-only session; none of these tests changes the proof state."""
    config = ProofAgentConfig.from_file(str(config_file))
    skip_if_libraries_missing(config)

    coq_file = temp_example_copy("main_loop_invariant_2_established_Coq.v")
    interface = CoqInterface(
        file_path=str(coq_file),
        workspace=config.coq.workspace or str(coq_file.parent),
        library_paths=config.coq.library_paths,
        auto_setup_coqproject=config.coq.auto_setup_coqproject,
        coqproject_extra_options=config.coq.coqproject_extra_options,
        timeout=config.coq.timeout,
    )
    assert interface.load(), f"load() failed: {interface.get_last_error()}"
    try:
        yield interface
    finally:
        interface.close()


def test_real_search_output_parses_into_named_entries(coq):
    """_parse_search_entries has to survive text Rocq actually produced."""
    raw = coq.search("Search Z.abs.")
    assert raw is not None, coq.get_last_error()
    assert raw != "No results found."

    entries = ResultReducer()._parse_search_entries(raw.splitlines())

    assert len(entries) > 5, f"only {len(entries)} entries parsed from {len(raw)} chars"
    assert all(e["name"] for e in entries), "an entry parsed with an empty name"
    assert all(e["signature"] for e in entries), "an entry parsed with no signature"

    names = {e["name"] for e in entries}
    assert "abs_0" in names or "Abs_pos" in names, sorted(names)[:20]

    # A dotted name is split into module + leaf, not left whole.
    dotted = [e for e in entries if e["module"]]
    assert dotted, "nothing carried a module prefix"
    for entry in dotted:
        assert entry["full_name"] == f"{entry['module']}.{entry['name']}"
        assert "." not in entry["name"], entry


def test_ranking_reorders_real_entries_without_losing_any(coq):
    """The goal context has to reach the ranking of live results."""
    raw = coq.search("Search Z.abs.")
    reducer = ResultReducer()
    entries = reducer._parse_search_entries(raw.splitlines())

    unranked = [e["name"] for e in entries]
    ranked = [e["name"] for e in reducer._rank_entries(entries, "0 <= Z.abs i nonneg")]

    assert sorted(ranked) == sorted(unranked), "ranking dropped or duplicated entries"
    assert ranked != unranked, "the goal context did not change the order"


def test_context_search_wrapper_returns_the_same_result_as_the_command(coq):
    """ContextSearch.search is a thin pass-through to auto_search."""
    context_search = ContextSearch(coq)

    through_wrapper = context_search.search("Print bool.")
    direct = CoqCommandSearch(coq).auto_search("Print bool.")

    assert through_wrapper.content == direct.content
    assert through_wrapper.source == "coq_command"
    assert "Inductive bool : Set" in through_wrapper.content


def test_execute_coq_query_dispatches_on_the_query_type(coq):
    """The typed entry point the controller uses for its query commands."""
    context_search = ContextSearch(coq)

    by_identifier = context_search.execute_coq_query(
        "search", identifier="Z.abs", goal_context="0 <= Z.abs x"
    )
    assert by_identifier.result_size > 0, by_identifier.content[:200]
    assert "Z.abs" in by_identifier.content

    by_pattern = context_search.execute_coq_query(
        "search", pattern="(_ <= _)", goal_context="x <= y"
    )
    assert by_pattern.result_size > 0
    assert by_pattern.original_size > by_identifier.original_size, (
        "a wildcard pattern should match more than one identifier"
    )

    printed = context_search.execute_coq_query("print", identifier="nat")
    assert "Inductive nat : Set" in printed.content

    # Missing parameters are reported, not guessed at.
    missing = context_search.execute_coq_query("search")
    assert "requires either identifier or pattern" in missing.content
    assert missing.metadata["error"] == "Missing parameters"


def test_a_search_that_matches_nothing_reports_no_results(coq):
    """An empty result must not reach the LLM looking like a hit."""
    result = ContextSearch(coq).search("Search definitely_not_a_lemma_xyz.")

    assert "No results found" in result.content, result.content[:200]
    assert result.metadata.get("error") is None, "an empty result is not a failure"
