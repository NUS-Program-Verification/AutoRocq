"""
CoqInterface's core surface, against a real coq-lsp session on examples/example.v.

Every line of this file used to sit under `if __name__ == "__main__":`, so
pytest collected nothing from it and none of these calls were checked by a test
run. The tactic list had gone stale along the way -- it introduced two nat
variables (`intros n m.`) and rewrote with `plus_O_n` for a lemma that takes a
single bool.
"""

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.coq_interface import CoqInterface
from coqpyt.coq.structs import TermType
from tests.test_utils import temp_example_copy

# The proof of `forall b : bool, orb true b = true` that example.v admits.
# Both branches of the destruct need their own simpl/reflexivity pair.
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
    """A loaded interface on a throwaway copy of example.v.

    Function-scoped on purpose: applying tactics mutates the proof and coqpyt
    writes each accepted step back to the file, so tests must not share one.
    """
    interface = CoqInterface(str(temp_example_copy("example.v")))
    assert interface.load(), f"load() failed: {interface.get_last_error()}"
    try:
        yield interface
    finally:
        interface.close()


def test_load_opens_the_admitted_proof(coq):
    """load() has to find the admitted proof and pop its terminator."""
    assert coq.proof is not None, "no unproven proof found"
    assert coq.in_proof(), "load() left the session outside a proof"

    steps = [step.text.strip() for step in coq.proof.steps]
    assert steps == ["Proof."], f"expected only 'Proof.' to remain, got {steps}"

    # example.v imports Utf8, so the goal comes back in notation form rather
    # than as `orb true b = true`.
    goal = coq.get_goal_str()
    assert "(true || b)%bool = true" in goal, goal
    assert coq.get_current_step_number() == 1


def test_context_terms_include_the_files_own_definitions(coq):
    """get_context_terms/get_notations must reflect what the file declares."""
    terms = coq.get_context_terms()
    assert terms, "context has no terms at all"
    assert "orb_true_l" in terms, "the file's own lemma is missing from the context"
    assert "reduce_eq" in terms, "the file's Ltac is missing from the context"
    assert "orb" in terms, "the imported stdlib is missing from the context"

    notations = coq.get_notations()
    assert notations, "example.v imports ZArith and Utf8 but exposes no notations"
    assert all(n.type == TermType.NOTATION for n in notations), (
        "get_notations() returned a non-notation term"
    )
    assert len(notations) < len(terms), "every term cannot be a notation"


def test_tactics_drive_the_proof_to_qed(coq):
    """The full sequence has to apply, change the goal, and close the proof."""
    goal_before = coq.get_goal_str()

    for i, tactic in enumerate(PROOF_TACTICS, start=1):
        assert coq.apply_tactic(tactic), (
            f"{tactic.strip()!r} failed: {coq.get_last_error()}"
        )
        # Step 1 is "Proof.", so the i-th tactic lands on step i + 1.
        assert coq.get_current_step_number() == i + 1, (
            f"after {tactic.strip()!r}: {coq.get_current_step_number()}"
        )

    assert coq.get_goal_str() != goal_before, "six tactics left the goal untouched"
    assert "No more goals" in coq.get_goal_str(), coq.get_goal_str()
    assert coq.is_proof_complete(), "no goals left but the proof is not complete"

    # Asking for status reports on the proof; it does not close it.
    status = coq.get_proof_completion_status()
    assert status["ready_for_qed"], status
    assert not status["qed_already_applied"], "status applied Qed as a side effect"
    assert status == coq.get_proof_completion_status(), "status is not idempotent"

    assert coq.apply_qed(), "Qed was refused on a finished proof"
    assert coq.proof.steps[-1].text.strip() == "Qed."

    # Completion survives Qed, even though coqpyt drops the proof out of
    # unproven_proofs the moment it closes.
    assert coq.proof_file.unproven_proofs == []
    assert coq.is_proof_complete(), "completion flipped back to False after Qed"
    final = coq.get_proof_completion_status()
    assert final["is_complete"] and final["qed_already_applied"], final


def test_a_bad_tactic_fails_without_breaking_the_session(coq):
    """A rejected tactic must report why and leave the proof where it was."""
    steps_before = coq.get_current_step_number()

    assert not coq.apply_tactic(" exact I."), "nonsense tactic reported success"
    assert coq.get_last_error(), "a failed tactic recorded no error"
    assert coq.get_current_step_number() == steps_before, "failed tactic left a step behind"

    # The session must still accept a good tactic afterwards.
    assert coq.apply_tactic(" intros b."), coq.get_last_error()
    assert coq.get_current_step_number() == steps_before + 1
