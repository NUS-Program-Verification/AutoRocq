"""
TacticHistoryManager: recording tactics, the duplicate filter, and the
save/reload round trip.

This file used to be a __main__ debug script -- pytest collected nothing from
it -- and its first act was `history_file.unlink()` on
proof-search/data/tactic_history.json, the agent's own accumulated history.
Everything here writes under tmp_path instead.

The one live-Rocq test records a tactic applied through CoqInterface, which is
what the agent actually does; the rest are pure unit tests on the manager.
Retrieval (get_similar_history) has its own file, test_get_similar_history.py.
"""

import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from agent.history_recorder import TacticHistoryEntry, TacticHistoryManager
from backend.coq_interface import CoqInterface
from tests.test_utils import temp_example_copy


@pytest.fixture
def manager(tmp_path):
    """A manager over an empty history file of this test's own."""
    return TacticHistoryManager(str(tmp_path / "tactic_history.json"))


def test_a_new_manager_starts_empty(manager):
    assert manager.entries == []
    assert manager.get_statistics() == {"total_entries": 0}
    assert manager.get_recent_tactics() == []


def test_added_tactics_survive_a_save_and_reload(tmp_path):
    """The round trip through JSON has to preserve every field."""
    history_file = tmp_path / "tactic_history.json"
    manager = TacticHistoryManager(str(history_file))

    manager.add_successful_tactic(
        tactic="intros x y z.",
        goals_before="forall x y z : nat, x + y = z",
        goals_after="x, y, z : nat |- x + y = z",
        theorem_name="round_trip",
        hypotheses_before="",
        hypotheses_after="x, y, z : nat",
        step_number=1,
    )
    assert len(manager.entries) == 1

    manager.save_history()
    assert history_file.exists(), "save_history() wrote nothing"

    on_disk = json.loads(history_file.read_text())
    assert len(on_disk["entries"]) == 1, on_disk
    assert on_disk["metadata"]["total_entries"] == 1

    reloaded = TacticHistoryManager(str(history_file))
    assert len(reloaded.entries) == 1, "a fresh manager did not read the file back"

    entry = reloaded.entries[0]
    assert entry.tactic == "intros x y z."
    assert entry.goals_before == "forall x y z : nat, x + y = z"
    assert entry.goals_after == "x, y, z : nat |- x + y = z"
    assert entry.hypotheses_after == "x, y, z : nat"
    assert entry.theorem_name == "round_trip"
    assert entry.step_number == 1
    assert entry.source == "agent"


def test_only_an_exact_repeat_counts_as_a_duplicate(manager):
    """The signature is tactic + goals_before + goals_after, nothing else."""
    def add(tactic, before, after, theorem="t"):
        manager.add_successful_tactic(
            tactic=tactic,
            goals_before=before,
            goals_after=after,
            theorem_name=theorem,
        )

    add("lia.", "0 <= n", "")
    add("lia.", "0 <= n", "")
    assert len(manager.entries) == 1, "an exact repeat was stored twice"

    # A different theorem is still the same signature.
    add("lia.", "0 <= n", "", theorem="other")
    assert len(manager.entries) == 1, "theorem_name must not enter the signature"

    # Any of the three fields differing makes it a new entry.
    add("lia.", "0 <= m", "")
    add("nia.", "0 <= n", "")
    add("lia.", "0 <= n", "n = 0", theorem="second")
    assert len(manager.entries) == 4

    stats = manager.get_statistics()
    assert stats["total_entries"] == 4
    assert stats["unique_signatures"] == 4
    # "other" was deduplicated away, so only "t" and "second" are represented.
    assert stats["theorems_covered"] == 2
    assert stats["unique_tactics"] == 2, stats["most_common_tactics"]


def test_lookups_filter_and_order_the_entries(manager):
    for i, theorem in enumerate(["alpha", "beta", "alpha"], start=1):
        manager.add_successful_tactic(
            tactic=f"tactic_{i}.",
            goals_before=f"goal before {i}",
            goals_after=f"goal after {i}",
            theorem_name=theorem,
            step_number=i,
        )

    alpha = manager.get_tactics_for_theorem("alpha")
    assert [e["tactic"] for e in alpha] == ["tactic_1.", "tactic_3."]
    assert manager.get_tactics_for_theorem("gamma") == []
    assert manager.get_tactics_for_theorem("") == []

    recent = manager.get_recent_tactics(limit=2)
    assert [e["tactic"] for e in recent] == ["tactic_2.", "tactic_3."]
    assert set(recent[0]) >= {"tactic", "goals_before", "goals_after", "theorem_name"}


def test_clear_history_is_in_memory_until_saved(tmp_path):
    history_file = tmp_path / "tactic_history.json"
    manager = TacticHistoryManager(str(history_file))
    manager.add_successful_tactic(
        tactic="lia.", goals_before="0 <= n", goals_after="", theorem_name="t"
    )
    manager.save_history()

    manager.clear_history()

    assert manager.entries == []
    # clear_history() drops the entries and the signatures; it does not write.
    assert len(json.loads(history_file.read_text())["entries"]) == 1

    manager.save_history()
    assert json.loads(history_file.read_text())["entries"] == []
    assert TacticHistoryManager(str(history_file)).entries == []


def test_a_corrupt_history_file_does_not_take_the_manager_down(tmp_path):
    history_file = tmp_path / "tactic_history.json"
    # Long enough to get past the "too small, likely truncated" guard, so this
    # exercises the JSON decode failure itself.
    history_file.write_text('{"entries": [ this is not valid json at all')

    manager = TacticHistoryManager(str(history_file))

    assert manager.entries == []


def test_entry_dict_round_trip():
    entry = TacticHistoryEntry.from_dict(
        {
            "tactic": "lia.",
            "goals_before": "0 <= n",
            "goals_after": "",
            "hypotheses_before": "n : Z",
            "hypotheses_after": "n : Z",
            "theorem_name": "t",
            "timestamp": "2026-09-02T00:00:00",
            "step_number": 4,
            "source": "user",
        }
    )

    assert entry.tactic == "lia."
    assert entry.step_number == 4
    assert entry.source == "user"
    assert entry.timestamp.year == 2026

    assert TacticHistoryEntry.from_dict(entry.to_dict()).to_dict() == entry.to_dict()


def test_a_tactic_applied_through_coq_is_recorded_with_its_real_states(tmp_path):
    """End to end: the states stored are the ones Rocq actually produced."""
    coq = CoqInterface(str(temp_example_copy("example.v")))
    assert coq.load(), f"load() failed: {coq.get_last_error()}"

    try:
        manager = TacticHistoryManager(str(tmp_path / "tactic_history.json"))

        goals_before = coq.get_goal_str()
        hypotheses_before = coq.get_hypothesis()

        assert coq.apply_tactic(" intros b."), coq.get_last_error()

        goals_after = coq.get_goal_str()
        hypotheses_after = coq.get_hypothesis()
        assert goals_after != goals_before, "intros left the goal unchanged"

        manager.add_successful_tactic(
            tactic="intros b.",
            goals_before=goals_before,
            goals_after=goals_after,
            theorem_name="orb_true_l",
            hypotheses_before=hypotheses_before,
            hypotheses_after=hypotheses_after,
            step_number=1,
        )
        manager.save_history()
    finally:
        coq.close()

    reloaded = TacticHistoryManager(str(tmp_path / "tactic_history.json"))
    assert len(reloaded.entries) == 1

    entry = reloaded.entries[0]
    assert entry.tactic == "intros b."
    assert entry.theorem_name == "orb_true_l"
    assert "(true || b)%bool = true" in entry.goals_before
    assert entry.goals_before != entry.goals_after
    # intros binds b, so the stored "after" state has to show it in context.
    assert "b: bool" in entry.goals_after, entry.goals_after
    assert "∀ b : bool" not in entry.goals_after, "the binder was never introduced"
