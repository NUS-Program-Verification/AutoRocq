import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tests.test_utils import temp_example_copy, create_coq_interface

PROOF_TACTICS = [
    " intros b.",
    " destruct b.",
    " simpl.",
    " reflexivity.",
    " simpl.",
    " reflexivity.",
]

SECOND_LEMMA = """

Lemma andb_false_l : forall b : bool, andb false b = false.
Proof.
Admitted.
"""


@pytest.fixture
def two_proofs():
    path = temp_example_copy("example.v")
    path.write_text(path.read_text() + SECOND_LEMMA)
    interface = create_coq_interface(path)
    yield interface
    interface.close()


def close_the_goals(coq):
    for tactic in PROOF_TACTICS:
        assert coq.apply_tactic(tactic), f"{tactic.strip()!r}: {coq.get_last_error()}"


def test_asking_for_status_leaves_the_proof_alone(coq):
    opening = coq.get_proof_completion_status()
    assert opening["has_proof"] and not opening["ready_for_qed"], opening
    assert opening == coq.get_proof_completion_status(), "status is not idempotent"

    close_the_goals(coq)
    steps_before = len(coq.proof.steps)

    first = coq.get_proof_completion_status()
    second = coq.get_proof_completion_status()
    third = coq.get_proof_completion_status()

    assert first == second == third, "status changed between identical calls"
    assert first["ready_for_qed"], first
    assert not first["qed_already_applied"], "status closed the proof"
    assert len(coq.proof.steps) == steps_before, "status added a step"


def test_is_ready_for_qed_predicts_without_acting(coq):
    close_the_goals(coq)
    steps_before = len(coq.proof.steps)

    assert coq.is_ready_for_qed()
    assert coq.is_ready_for_qed()
    assert coq.is_ready_for_qed()
    assert len(coq.proof.steps) == steps_before, "the prediction changed the proof"
    assert coq.proof.steps[-1].text.strip() != "Qed."

    assert coq.apply_qed(), f"Qed refused: {coq.get_last_error()}"
    assert len(coq.proof.steps) == steps_before + 1
    assert coq.proof.steps[-1].text.strip() == "Qed."


def test_completion_uses_the_structured_goal_state(coq, monkeypatch):
    monkeypatch.setattr(coq, "get_goal_str", lambda: "No more goals.")

    assert coq.has_open_goals()
    assert not coq.is_ready_for_qed()
    assert not coq.is_proof_complete()


def test_completion_survives_qed(coq):
    close_the_goals(coq)
    assert coq.is_proof_complete(), "no goals left but not reported complete"

    assert coq.apply_qed(), f"Qed refused: {coq.get_last_error()}"

    # CoqPyt removes closed proofs from unproven_proofs.
    assert coq.proof_file.unproven_proofs == []
    assert coq.get_unproven_proof() is None
    assert coq.is_proof_complete(), "completion did not survive Qed"
    assert coq.is_proof_complete(), "completion is not stable"

    final = coq.get_proof_completion_status()
    assert final["is_complete"] and final["qed_already_applied"], final
    assert final["has_proof"], "a finished proof is still a proof"
    assert final == coq.get_proof_completion_status()


def test_applying_qed_twice_keeps_one_terminator(coq):
    close_the_goals(coq)
    assert coq.apply_qed()
    steps_after_qed = [step.text for step in coq.proof.steps]

    assert coq.apply_qed(), "a closed proof is not closeable a second time"
    assert [step.text for step in coq.proof.steps] == steps_after_qed


def test_the_flags_do_not_depend_on_the_order_they_are_computed(coq):
    close_the_goals(coq)

    terminated = coq._last_step_is_terminator(coq.proof)
    ready = coq.is_ready_for_qed()
    complete = coq.is_proof_complete()

    status = coq.get_proof_completion_status()
    assert (status["qed_already_applied"], status["ready_for_qed"], status["is_complete"]) == (
        terminated, ready, complete
    ), status

    assert coq.apply_qed(), f"Qed refused: {coq.get_last_error()}"

    terminated = coq._last_step_is_terminator(coq.proof)
    ready = coq.is_ready_for_qed()
    complete = coq.is_proof_complete()
    status = coq.get_proof_completion_status()
    assert (status["qed_already_applied"], status["ready_for_qed"], status["is_complete"]) == (
        terminated, ready, complete
    ), status


def test_a_refused_qed_leaves_the_proof_alone_and_says_why(coq, monkeypatch):
    close_the_goals(coq)
    assert coq.is_ready_for_qed(), "the goals are gone, Qed is worth trying"

    def refuse(*_args, **_kwargs):
        raise RuntimeError("Attempt to save an incomplete proof")

    monkeypatch.setattr(coq.proof_file, "append_step", refuse)
    steps_before = [step.text for step in coq.proof.steps]

    assert coq.apply_qed() is False, "a refused Qed reported success"
    assert [step.text for step in coq.proof.steps] == steps_before, (
        "a refused Qed left something behind"
    )
    assert "Attempt to save an incomplete proof" in coq.get_last_error(), (
        coq.get_last_error()
    )

    status = coq.get_proof_completion_status()
    assert not status["qed_already_applied"], status
    assert status["is_complete"], "the proof body remains goal-free"


def test_the_agents_completion_check_fires_only_once_the_proof_is_closed(coq):
    def agent_sees_success():
        status = coq.get_proof_completion_status()
        return status["is_complete"] and status["qed_already_applied"]

    assert not agent_sees_success(), "success before a single tactic"

    close_the_goals(coq)
    assert not agent_sees_success(), "success before the proof was saved"

    assert coq.apply_qed(), f"Qed refused: {coq.get_last_error()}"
    assert agent_sees_success(), "the finished proof was not recognised"


def test_get_proof_status_reports_a_proved_file_as_complete(coq):
    close_the_goals(coq)
    assert coq.apply_qed(), f"Qed refused: {coq.get_last_error()}"

    assert coq.get_proof_status()["is_complete"], coq.get_proof_status()


def test_closing_one_proof_in_a_file_that_has_two(two_proofs):
    coq = two_proofs
    target = coq.proof
    assert target is not None

    close_the_goals(coq)
    assert coq.apply_qed(), f"Qed refused: {coq.get_last_error()}"

    assert coq.proof is target, "the interface changed proofs underneath us"
    assert coq.proof_file.unproven_proofs, "the second lemma should still be open"
    assert coq.get_unproven_proof() is not target, (
        "the lookup returns the other proof, which is the point of this test"
    )

    status = coq.get_proof_completion_status()
    assert status["qed_already_applied"], status
    assert status["is_complete"], status
    assert coq.is_proof_complete()
