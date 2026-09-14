"""CoqInterface's core surface, against a real coq-lsp session on examples/example.v."""

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.coq_interface import CoqInterface
from coqpyt.coq.structs import TermType
from tests.test_utils import temp_example_copy

# example.v's goal reduces on `orb`'s first argument, so `reflexivity.` alone
# would close it; going through both destruct branches exercises more of
# apply_tactic's step bookkeeping on the way to Qed.
PROOF = [
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


def test_a_bad_tactic_fails_without_breaking_the_session(coq):
    """A rejected tactic must report why and leave the proof where it was."""
    steps_before = coq.get_current_step_number()

    assert not coq.apply_tactic(" exact I."), "nonsense tactic reported success"
    assert coq.get_last_error(), "a failed tactic recorded no error"
    assert coq.get_current_step_number() == steps_before, "failed tactic left a step behind"

    # The session must still accept a good tactic afterwards.
    assert coq.apply_tactic(" intros b."), coq.get_last_error()
    assert coq.get_current_step_number() == steps_before + 1


def test_a_full_proof_runs_through_to_qed(coq):
    """Stepwise application has to close the proof."""
    assert not coq.is_proof_complete(), "an admitted proof reported complete"

    for offset, tactic in enumerate(PROOF, start=1):
        assert coq.apply_tactic(tactic), f"{tactic.strip()}: {coq.get_last_error()}"
        assert coq.get_current_step_number() == 1 + offset

    # Goals are exhausted, but the proof is not closed until Qed lands.
    assert "No more goals." in coq.get_goal_str(), coq.get_goal_str()

    assert coq.apply_tactic(" Qed."), coq.get_last_error()
    assert coq.proof.steps[-1].text.strip() == "Qed."
    assert not coq.proof_file.unproven_proofs, "Qed left the proof unproven"


@pytest.mark.xfail(
    strict=True,
    reason="is_proof_complete() reads unproven_proofs[0], which Qed removes, so it "
    "returns False exactly when the proof is complete",
)
def test_is_proof_complete_reports_a_closed_proof(coq):
    for tactic in PROOF + [" Qed."]:
        assert coq.apply_tactic(tactic), f"{tactic.strip()}: {coq.get_last_error()}"

    assert coq.is_proof_complete()
