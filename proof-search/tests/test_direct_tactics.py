"""
clear_unproven_proof_steps() and the get_proof_completion_status() transitions
that the controller reads to decide when a proof is finished.

The old version carried three tactic lists, two of which were dead (each
assignment overwrote the previous), and returned True/False from every branch;
its single assert sat behind an `if` that a failing run never reached. A run
where every tactic was rejected returned False and still passed.
"""

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.coq_interface import CoqInterface
from tests.test_utils import temp_example_copy

# Both branches of `destruct b` for `forall b : bool, orb true b = true`.
PROOF_TACTICS = [
    " intros b.",
    " destruct b.",
    " simpl.",
    " reflexivity.",
    " simpl.",
    " reflexivity.",
]


@pytest.fixture
def coq():
    interface = CoqInterface(str(temp_example_copy("example.v")))
    assert interface.load(), f"load() failed: {interface.get_last_error()}"
    try:
        yield interface
    finally:
        interface.close()


def test_clear_unproven_proof_steps_rewinds_to_proof(coq):
    """Clearing has to put the proof back exactly where load() left it."""
    initial_goal = coq.get_goal_str()

    assert coq.apply_tactic(" intros b."), coq.get_last_error()
    assert coq.apply_tactic(" destruct b."), coq.get_last_error()
    assert coq.get_current_step_number() == 3
    assert coq.get_goal_str() != initial_goal

    assert coq.clear_unproven_proof_steps(), coq.get_last_error()

    assert [s.text.strip() for s in coq.get_unproven_proof().steps] == ["Proof."]
    assert coq.get_current_step_number() == 1
    assert coq.get_goal_str() == initial_goal, "clearing did not restore the goal"

    # And the cleared proof still accepts tactics.
    assert coq.apply_tactic(" intros b."), coq.get_last_error()


def test_completion_status_only_flips_once_the_goals_are_gone(coq):
    """ready_for_qed must stay False while anything is still to prove."""
    opening = coq.get_proof_completion_status()
    assert opening["has_proof"]
    assert not opening["is_complete"], opening
    assert not opening["ready_for_qed"], opening
    assert not opening["qed_already_applied"], opening

    # Halfway through, one branch of the destruct is still open.
    for tactic in PROOF_TACTICS[:4]:
        assert coq.apply_tactic(tactic), (
            f"{tactic.strip()!r} failed: {coq.get_last_error()}"
        )

    midway = coq.get_proof_completion_status()
    assert not midway["ready_for_qed"], midway
    assert midway["current_goals"].strip(), "goals vanished with a branch still open"

    for tactic in PROOF_TACTICS[4:]:
        assert coq.apply_tactic(tactic), (
            f"{tactic.strip()!r} failed: {coq.get_last_error()}"
        )

    final = coq.get_proof_completion_status()
    assert final["ready_for_qed"], final
    # is_ready_for_qed() applies Qed as soon as it succeeds and keeps it.
    assert final["qed_already_applied"], final
    assert coq.get_unproven_proof() is None, "the proof is still open after Qed"


def test_a_rejected_tactic_reports_the_error_and_changes_nothing(coq):
    """get_last_error() is the agent's only signal that a step was refused."""
    goal_before = coq.get_goal_str()
    step_before = coq.get_current_step_number()

    assert not coq.apply_tactic(" apply Z.abs_nonneg."), "a bogus tactic reported success"

    error = coq.get_last_error()
    assert error, "a rejected tactic recorded no error"
    assert coq.get_current_step_number() == step_before
    assert coq.get_goal_str() == goal_before
