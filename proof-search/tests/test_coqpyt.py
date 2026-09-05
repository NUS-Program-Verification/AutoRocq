"""
coqpyt's append_step/pop_step contract, driven straight through ProofFile.

The old version appended one hard-coded proof twice, swallowed
InvalidChangeException with a print, and asserted nothing -- so it passed
whether or not coqpyt accepted a single step. It also carried two dead tactic
lists (`incorrect`/`correct` built from `rewrite app_assoc`) that were
overwritten before use.

`current_goals` is a GoalAnswer, and its truthiness says nothing: it is a live
object even when the proof is finished, and str() of it is "No more goals."
rather than "". Every "is the proof done yet" check here goes through
open_goals() instead. The old `if not proof_file.current_goals:` idiom -- still
present in a few sibling tests -- can never fire.
"""

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from coqpyt.coq.exceptions import InvalidChangeException
from coqpyt.coq.proof_file import ProofFile
from tests.test_utils import temp_example_copy

# example.v admits `forall b : bool, orb true b = true`. `orb true b` reduces
# on its first argument, so plain `reflexivity.` closes the whole thing; this
# sequence takes the long way through both branches of the destruct, which is
# what makes the intermediate goal counts below worth asserting.
CORRECT_PROOF = [
    "  intros b.",
    "  destruct b.",
    "  simpl.",
    "  reflexivity.",
    "  simpl.",
    "  reflexivity.",
]

# Open goals after each step of CORRECT_PROOF: destruct splits, and each
# reflexivity closes one branch.
EXPECTED_OPEN_GOALS = [1, 2, 2, 1, 1, 0]


def open_goals(proof_file):
    """The goals actually left to prove."""
    return proof_file.current_goals.goals.goals


def clean_proof_file(file_path):
    """Cut the file back to its first `Proof.`, leaving the proof open."""
    content = Path(file_path).read_text(encoding="utf-8")
    proof_pos = content.find("Proof.")
    assert proof_pos != -1, f"no 'Proof.' in {file_path}"
    Path(file_path).write_text(
        content[: proof_pos + len("Proof.")] + "\n", encoding="utf-8"
    )


@pytest.fixture
def proof_file():
    """An open ProofFile on a throwaway copy of example.v.

    use_disk_cache is what CoqInterface passes, and it is the difference
    between a 4-second session and a 100-second one.
    """
    file_path = temp_example_copy("example.v")
    clean_proof_file(file_path)
    with ProofFile(str(file_path), use_disk_cache=True) as pf:
        pf.run()
        yield pf


def test_a_valid_proof_is_accepted_step_by_step_and_closes(proof_file):
    """Each step has to land, move the goal as expected, and end proven."""
    assert proof_file.unproven_proofs, "the cleaned file has no open proof"
    unproven = proof_file.unproven_proofs[0]
    assert [s.text.strip() for s in unproven.steps] == ["Proof."]
    assert len(open_goals(proof_file)) == 1

    for i, (step, expected_open) in enumerate(
        zip(CORRECT_PROOF, EXPECTED_OPEN_GOALS), start=1
    ):
        proof_file.append_step(unproven, step)
        assert len(unproven.steps) == i + 1, f"{step.strip()!r} added no step"
        assert len(open_goals(proof_file)) == expected_open, (
            f"after {step.strip()!r}: {len(open_goals(proof_file))} open goals, "
            f"expected {expected_open}"
        )

    proof_file.append_step(unproven, "  Qed.")
    assert [s.text.strip() for s in unproven.steps][-1] == "Qed."
    assert proof_file.unproven_proofs == [], "the proof is still listed as unproven"


def test_an_invalid_step_is_rejected_and_pop_rewinds(proof_file):
    """The reject-and-rollback path the agent depends on."""
    unproven = proof_file.unproven_proofs[0]
    steps_before = len(unproven.steps)
    goals_before = str(proof_file.current_goals)

    # Nothing in scope has this shape, so coqpyt must refuse the change.
    with pytest.raises(InvalidChangeException):
        proof_file.append_step(unproven, "  apply Z.abs_nonneg.")

    assert len(unproven.steps) == steps_before, "a rejected step was kept"
    assert str(proof_file.current_goals) == goals_before, "a rejected step moved the goal"

    # Accepted steps then pop back off cleanly, restoring the original state.
    proof_file.append_step(unproven, "  intros b.")
    proof_file.append_step(unproven, "  destruct b.")
    assert len(unproven.steps) == steps_before + 2
    assert len(open_goals(proof_file)) == 2

    proof_file.pop_step(unproven)
    proof_file.pop_step(unproven)

    assert len(unproven.steps) == steps_before
    assert len(open_goals(proof_file)) == 1
    assert str(proof_file.current_goals) == goals_before, (
        "popping both steps did not restore the original goal"
    )

    # And the proof still completes afterwards.
    for step in CORRECT_PROOF + ["  Qed."]:
        proof_file.append_step(unproven, step)
    assert proof_file.unproven_proofs == []
