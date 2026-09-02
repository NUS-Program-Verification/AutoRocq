"""
ProofState, the per-step snapshot in agent/proof_tree.py.

This file used to be a __main__ script that built a ProofState per tactic and
printed it; pytest collected nothing from it. ProofState has no caller in the
agent outside its own copy(), so these tests are the only thing pinning its
contract.

Hypotheses go in as a list of lines, which is what the `List[str]` annotation
asks for. The old script passed the raw string from get_hypothesis(), which
made copy() -- `list(self.hypothesis)` -- explode the state into one entry per
character.
"""

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from agent.proof_tree import ProofState
from backend.coq_interface import CoqInterface
from tests.test_utils import temp_example_copy

TACTICS = [" intros b.", " destruct b.", " simpl.", " reflexivity."]


def as_hypothesis_list(raw):
    """get_hypothesis() returns one blob; ProofState wants the lines."""
    return [line for line in (raw or "").splitlines() if line.strip()]


@pytest.fixture
def coq():
    interface = CoqInterface(str(temp_example_copy("example.v")))
    assert interface.load(), f"load() failed: {interface.get_last_error()}"
    try:
        yield interface
    finally:
        interface.close()


def test_proof_state_records_each_step_of_a_real_proof(coq):
    """A state per tactic has to carry that step's goal and history."""
    applied = []
    states = []

    for step_idx, tactic in enumerate(TACTICS, start=1):
        assert coq.apply_tactic(tactic), (
            f"{tactic.strip()!r} failed: {coq.get_last_error()}"
        )
        applied.append(tactic.strip())
        states.append(
            ProofState(
                step_idx=step_idx,
                current_goal=coq.get_goal_str(),
                hypothesis=as_hypothesis_list(coq.get_hypothesis()),
                applied_tactics=list(applied),
                last_tactic=tactic.strip(),
            )
        )

    assert len(states) == len(TACTICS)
    assert [s.step_idx for s in states] == [1, 2, 3, 4]
    assert [len(s.applied_tactics) for s in states] == [1, 2, 3, 4]
    assert states[-1].applied_tactics == [t.strip() for t in TACTICS]
    assert states[-1].last_tactic == "reflexivity."

    # `intros b.` binds b, so the goal it leaves must differ from what
    # `destruct b.` leaves behind.
    assert states[0].current_goal != states[1].current_goal, (
        "destruct did not change the goal recorded in the state"
    )

    # Each state keeps its own copy of the history rather than aliasing it.
    assert states[0].applied_tactics == ["intros b."]

    # The list is what got stored, not an exploded string.
    for state in states:
        assert all(len(h) != 1 for h in state.hypothesis), state.hypothesis


def test_is_terminal_only_for_a_closed_goal():
    def state(goal):
        return ProofState(step_idx=0, current_goal=goal, hypothesis=[])

    assert state("").is_terminal()
    assert state("   ").is_terminal()
    assert state("Qed.").is_terminal()
    assert not state("orb true b = true").is_terminal()


def test_copy_is_independent_of_the_original():
    original = ProofState(
        step_idx=3,
        current_goal="orb true b = true",
        hypothesis=["b : bool"],
        applied_tactics=["intros b."],
        reward=0.5,
        last_tactic="intros b.",
        error_info={"kind": "none"},
    )

    clone = original.copy()

    assert clone.step_idx == 3
    assert clone.current_goal == original.current_goal
    assert clone.applied_tactics == original.applied_tactics
    assert clone.reward == 0.5
    assert clone.last_tactic == "intros b."
    assert clone.error_info == {"kind": "none"}
    assert clone.timestamp == original.timestamp

    clone.applied_tactics.append("destruct b.")
    clone.hypothesis.append("b0 : bool")
    clone.error_info["kind"] = "changed"

    assert original.applied_tactics == ["intros b."]
    assert original.hypothesis == ["b : bool"]
    assert original.error_info == {"kind": "none"}


def test_str_reports_the_whole_state():
    rendered = str(
        ProofState(
            step_idx=7,
            current_goal="orb true b = true",
            hypothesis=["b : bool"],
            applied_tactics=["intros b."],
            reward=1.5,
        )
    )

    assert "step 7" in rendered
    assert "orb true b = true" in rendered
    assert "b : bool" in rendered
    assert "intros b." in rendered
    assert "1.5" in rendered
