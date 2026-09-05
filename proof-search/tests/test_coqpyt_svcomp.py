"""
The same SV-COMP proof as test_svcomp.py, but one layer down: straight through
coqpyt's ProofFile, with no CoqInterface in the way.

What this pins that the CoqInterface test does not is that the libframac
realizations resolve from the workspace's _CoqProject alone -- if they do not,
`wp_goal` never typechecks and coqpyt fails to open a proof at all.

The old version tallied `successful_steps`/`failed_steps`, then decided
completion from `failed_steps == 0 and successful_steps > 0 and has_qed`,
printed the verdict, and returned it -- which pytest discards. Its
`if not current_goals:` check could never fire either: `current_goals` is a
GoalAnswer object that stays truthy after the last goal is closed. The only
`assert` in the file sat in the `__main__` block, unreachable under pytest.
"""

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from coqpyt.coq.exceptions import InvalidChangeException
from coqpyt.coq.proof_file import ProofFile
from tests.test_utils import skip_if_libraries_missing, temp_example_copy
from utils.config import ProofAgentConfig

config_file = PROJECT_ROOT / "configs" / "default_config.json"

TACTICS = [
    "   \nintros i_1 i Hle Hlow Hup Hup_i Hsint.",
    "   \nassert (Hrange: -9 <= i <= 9) by lia.",
    "   \ndestruct Hrange as [Hi_low Hi_up].",
    "   \nSearch (Z.abs _ <= _ -> _ * _ <= _).",
    "   \nSearch Z.abs.",
    "   \nassert (Hi_abs_le : Z.abs i <= 9) by now apply Z.abs_le.",
    "   \nrewrite <- Z.abs_square.",
    "   \nassert (0 <= Z.abs i) by apply Z.abs_nonneg.",
    "   \nassert (Habs_sq_le_81 : Z.abs i * Z.abs i <= 9 * 9) by (apply Z.square_le_mono_nonneg; lia).",
    "   \nintros _.",
    "   \napply (Z.le_trans _ (9 * 9)); lia.",
]


def open_goals(proof_file):
    """The goals actually left to prove; `current_goals` itself is always truthy."""
    return proof_file.current_goals.goals.goals


@pytest.fixture(scope="module")
def open_proof():
    """The goal file with its "Admitted." popped, ready for tactics.

    temp_example_copy brings examples/_CoqProject along, which is what maps
    libframac for a bare ProofFile -- nothing here regenerates it.
    """
    skip_if_libraries_missing(ProofAgentConfig.from_file(str(config_file)))

    coq_file = temp_example_copy("main_loop_invariant_2_established_Coq.v")
    with ProofFile(
        str(coq_file),
        workspace=str(coq_file.parent),
        timeout=60,
        use_disk_cache=True,
    ) as proof_file:
        proof_file.run()

        assert proof_file.unproven_proofs, (
            "no unproven proof: the libframac mapping probably did not resolve"
        )
        proof = proof_file.unproven_proofs[0]
        assert "wp_goal" in proof.text, proof.text[:200]
        assert "is_sint32" in proof.text, "this is not the SV-COMP goal"

        assert proof.steps[-1].text.strip() == "Admitted."
        proof_file.pop_step(proof)

        yield proof_file, proof


def test_the_goal_opens_with_the_libraries_resolved(open_proof):
    proof_file, proof = open_proof

    assert [s.text.strip() for s in proof.steps] == ["Proof."]
    assert len(open_goals(proof_file)) == 1

    goal = str(proof_file.current_goals)
    assert "is_sint32" in goal, goal[:300]
    assert "i1 * i1 <= 99" in goal, goal[:300]


def test_every_tactic_is_accepted_and_the_proof_closes(open_proof):
    """All twelve steps land, the goals run out, and Qed is accepted."""
    proof_file, proof = open_proof
    steps_before = len(proof.steps)

    for i, tactic in enumerate(TACTICS, start=1):
        try:
            proof_file.append_step(proof, tactic)
        except InvalidChangeException as e:
            pytest.fail(f"step {i}, {tactic.strip()[:60]!r} was rejected: {e}")
        assert len(proof.steps) == steps_before + i, (
            f"step {i} was accepted without adding a step"
        )

    assert open_goals(proof_file) == [], (
        f"goals remain after the last tactic: {proof_file.current_goals}"
    )

    proof_file.append_step(proof, "\nQed.")
    assert proof.steps[-1].text.strip() == "Qed."
    assert proof_file.unproven_proofs == [], "the goal is still listed as unproven"

    # Both Search commands are kept in the script, queries though they are.
    script = [s.text.strip() for s in proof.steps]
    assert sum(1 for s in script if s.startswith("Search ")) == 2, script
