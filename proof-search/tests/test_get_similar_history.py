"""
TacticHistoryManager.get_similar_history(): the retrieval that puts previously
successful tactics in front of the model.

The old version ran against proof-search/data/tactic_history.json -- gitignored
local state that only exists once someone has proved something on that machine
-- and returned True early when the file was missing or empty, False from its
`except`, and `len(similar) > 0` otherwise. pytest ignores all three, so it
passed whether the retrieval worked, returned nothing, or threw. On a fresh
checkout it never reached the function at all.

The corpus here is built in the test instead, so the ranking is actually
pinned rather than depending on what the machine happens to have proved.
"""

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from agent.history_recorder import TacticHistoryManager

# Deliberately spread across three different goal shapes.
CORPUS = [
    ("apply Z.abs_nonneg.", "0 <= Z.abs i"),
    ("apply app_assoc.", "forall l : list nat, l ++ nil = l"),
    ("destruct b.", "forall b : bool, orb true b = true"),
    ("lia.", "forall i i1 : int, i <= i1 -> i1 * i1 <= 99"),
]


@pytest.fixture
def manager(tmp_path):
    manager = TacticHistoryManager(str(tmp_path / "tactic_history.json"))
    for i, (tactic, goals_before) in enumerate(CORPUS):
        manager.add_successful_tactic(
            tactic=tactic,
            goals_before=goals_before,
            goals_after=f"goal after {i}",
            theorem_name=f"theorem_{i}",
            step_number=i,
        )
    assert len(manager.entries) == len(CORPUS)
    return manager


def test_an_exact_goal_match_ranks_first(manager):
    """Nothing can be more similar to a goal than that goal itself."""
    for tactic, goals_before in CORPUS:
        top = manager.get_similar_history(goals_before, n=1)

        assert len(top) == 1
        assert top[0]["tactic"] == tactic, (
            f"querying with {goals_before!r} returned {top[0]['tactic']!r}"
        )


def test_a_near_match_still_wins(manager):
    """Retrieval has to survive the goal not being character-identical."""
    similar = manager.get_similar_history("0 <= Z.abs n", n=2)

    assert similar
    assert similar[0]["tactic"] == "apply Z.abs_nonneg."


def test_results_are_capped_and_ordered_by_score(manager):
    similar = manager.get_similar_history("0 <= Z.abs i", n=2)

    assert len(similar) == 2, "n was not honoured"
    scores = [entry["similarity_score"] for entry in similar]
    assert scores == sorted(scores, reverse=True), scores
    assert all(0.0 <= score <= 1.0 for score in scores), scores

    # Asking for more than exists returns everything, not padding.
    everything = manager.get_similar_history("0 <= Z.abs i", n=99)
    assert len(everything) == len(CORPUS)
    assert len({entry["tactic"] for entry in everything}) == len(CORPUS)


def test_each_result_carries_the_fields_the_prompt_needs(manager):
    entry = manager.get_similar_history("0 <= Z.abs i", n=1)[0]

    assert set(entry) == {"tactic", "goals_before", "goals_after", "similarity_score"}
    assert entry["goals_before"] == "0 <= Z.abs i"
    assert entry["goals_after"] == "goal after 0"


def test_nothing_to_match_against_returns_nothing(manager, tmp_path):
    assert manager.get_similar_history("", n=5) == [], "an empty goal matched something"

    empty = TacticHistoryManager(str(tmp_path / "empty.json"))
    assert empty.get_similar_history("0 <= Z.abs i", n=5) == []
