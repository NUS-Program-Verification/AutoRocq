"""
Completion is reported, not caused.

get_proof_completion_status() used to close the proof it was asked to describe:
is_ready_for_qed() answered "could this be closed?" by appending Qed and keeping
it. The two flags the callers read were therefore measured either side of that
write -- is_complete saw the proof still open, qed_already_applied saw the
terminator the line above had just added -- and proof_controller required both.
Reordering those two dict keys would have stopped any run being recorded as
successful. is_proof_complete() had the matching defect underneath: it resolved
the proof through unproven_proofs, which a closed proof leaves, so completion
went False the moment the proof was finished.

These tests pin the contract that replaced it: asking changes nothing and can be
repeated, apply_qed() is the only thing that closes a proof, a refusal leaves the
proof untouched and says why, and completion stays true after completion.
"""

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.coq_interface import CoqInterface
from tests.test_utils import temp_example_copy

# Closes `forall b : bool, orb true b = true`; both branches need their own pair.
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


def _loaded(path):
    interface = CoqInterface(str(path))
    assert interface.load(), f"load() failed: {interface.get_last_error()}"
    return interface


@pytest.fixture
def coq():
    """A loaded interface on a throwaway copy of example.v (one open proof)."""
    interface = _loaded(temp_example_copy("example.v"))
    try:
        yield interface
    finally:
        interface.close()


@pytest.fixture
def two_proofs():
    """The same file with a second, untouched lemma after the first."""
    path = temp_example_copy("example.v")
    path.write_text(path.read_text() + SECOND_LEMMA)
    interface = _loaded(path)
    try:
        yield interface
    finally:
        interface.close()


def close_the_goals(coq):
    """Apply the six tactics. Leaves the proof goal-free but not terminated."""
    for tactic in PROOF_TACTICS:
        assert coq.apply_tactic(tactic), f"{tactic.strip()!r}: {coq.get_last_error()}"


def test_asking_for_status_leaves_the_proof_alone(coq):
    """The regression itself: status used to append Qed as a side effect."""
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
    """It reports whether Qed is worth trying. apply_qed() does the trying."""
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


def test_completion_survives_qed(coq):
    """The defect this replaced: completion flipped False exactly when true."""
    close_the_goals(coq)
    assert coq.is_proof_complete(), "no goals left but not reported complete"

    assert coq.apply_qed(), f"Qed refused: {coq.get_last_error()}"

    # coqpyt drops a closed proof out of unproven_proofs, which is what the old
    # implementation read, so this is the exact moment it used to go False.
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
    """What made the old code fragile: the dict's key order was load-bearing."""
    close_the_goals(coq)

    # Deliberately the reverse of the order get_proof_completion_status() uses.
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
    """Rocq can reject Qed on a goal-free proof: evars, a guard condition.

    is_ready_for_qed() only predicts, so apply_qed() is where that is found out.
    It has to leave the proof exactly as it was, report False, and record the
    reason -- which used to be swallowed by a bare `except Exception:`.
    """
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
    assert not (status["is_complete"] and status["qed_already_applied"]), (
        "an unsaved proof would be reported as finished"
    )


def test_the_agents_completion_check_fires_only_once_the_proof_is_closed(coq):
    """The exact conjunction proof_controller reads, at all three moments."""
    def agent_sees_success():
        status = coq.get_proof_completion_status()
        return status["is_complete"] and status["qed_already_applied"]

    assert not agent_sees_success(), "success before a single tactic"

    close_the_goals(coq)
    assert not agent_sees_success(), "success before the proof was saved"

    assert coq.apply_qed(), f"Qed refused: {coq.get_last_error()}"
    assert agent_sees_success(), "the finished proof was not recognised"


def test_get_proof_status_reports_a_proved_file_as_complete(coq):
    """main.py picks its cleanup branch off this flag."""
    close_the_goals(coq)
    assert coq.apply_qed(), f"Qed refused: {coq.get_last_error()}"

    assert coq.get_proof_status()["is_complete"], coq.get_proof_status()


def test_closing_one_proof_in_a_file_that_has_two(two_proofs):
    """Completion is about the proof being driven, not the file's first open one.

    With a second lemma still admitted, unproven_proofs is never empty, so a
    lookup-based answer reports on the wrong proof.
    """
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
