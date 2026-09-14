"""
Goal tracking through coqpyt on a proof reset to `Proof. Admitted.` by
tests/test_utils, covering the reset/pop-terminator path the agent uses before
it starts proving.
"""

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from coqpyt.coq.proof_file import ProofFile
from tests.test_utils import (
    reset_coq_file_to_admitted,
    restore_coq_file_from_backup,
    temp_example_copy,
)

TACTICS = ["  intros b.", "  destruct b.", "  simpl.", "  reflexivity."]


def open_goals(proof_file):
    """The goals actually left to prove; `current_goals` itself is always truthy."""
    return proof_file.current_goals.goals.goals


@pytest.fixture
def open_proof():
    """An open proof on a throwaway copy of example.v, terminator popped off.

    A copy because this rewrites the file and coqpyt writes every appended
    tactic back to it; the restore below is skipped on SIGKILL or timeout.
    """
    file_path = temp_example_copy("example.v")
    assert reset_coq_file_to_admitted(file_path, backup=True), (
        f"could not reset {file_path} to an admitted proof"
    )

    try:
        with ProofFile(str(file_path), timeout=60, use_disk_cache=True) as proof_file:
            proof_file.run()

            assert proof_file.proofs, "no proofs at all in the file"
            assert proof_file.unproven_proofs, "the reset left no unproven proof"
            unproven = proof_file.unproven_proofs[0]

            assert [s.text.strip() for s in unproven.steps] == ["Proof.", "Admitted."]
            proof_file.pop_step(unproven)

            yield proof_file, unproven
    finally:
        restore_coq_file_from_backup(file_path)


def test_reset_leaves_exactly_the_open_proof(open_proof):
    """reset_coq_file_to_admitted + one pop must reopen the original goal."""
    proof_file, unproven = open_proof

    assert [s.text.strip() for s in unproven.steps] == ["Proof."]
    assert "orb_true_l" in unproven.text, unproven.text
    assert len(open_goals(proof_file)) == 1, "an open proof reports no goal"
    assert "orb" in str(proof_file.current_goals) or "||" in str(proof_file.current_goals)


def test_walking_both_branches_closes_the_proof(open_proof):
    """Every tactic must land, and the goal count must follow the destruct."""
    proof_file, unproven = open_proof

    # destruct splits into two branches; each reflexivity closes one.
    for tactic, expected_open in zip(TACTICS, [1, 2, 2, 1]):
        steps_before = len(unproven.steps)
        proof_file.append_step(unproven, tactic)

        assert len(unproven.steps) == steps_before + 1, (
            f"{tactic.strip()!r} was accepted without adding a step"
        )
        assert len(open_goals(proof_file)) == expected_open, (
            f"after {tactic.strip()!r}: {len(open_goals(proof_file))} open, "
            f"expected {expected_open}"
        )

    # One branch is still open at this point -- the old test stopped here and
    # called it a success.
    assert open_goals(proof_file), "all four tactics closed the whole proof"

    for tactic in ["  simpl.", "  reflexivity."]:
        proof_file.append_step(unproven, tactic)

    assert open_goals(proof_file) == [], (
        f"goals remain: {proof_file.current_goals}"
    )

    proof_file.append_step(unproven, "  Qed.")
    assert unproven.steps[-1].text.strip() == "Qed."
    assert proof_file.unproven_proofs == []
