"""
The known-good proof of the SV-COMP goal, replayed through CoqInterface.

This is the end-to-end check that the agent's tactic-application path can carry
a real Frama-C/Why3 obligation from `Proof.` to `Qed.` with the libframac
realizations on the load path.

The old version counted successes and failures into `successful_steps` /
`failed_steps`, printed them, and then fell off the end of the function without
returning anything -- so a run where every tactic was rejected passed exactly
like a run where all eleven landed.
"""

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.coq_interface import CoqInterface
from tests.test_utils import skip_if_libraries_missing, temp_example_copy
from utils.config import ProofAgentConfig

config_file = PROJECT_ROOT / "configs" / "default_config.json"

# The proof of wp_goal. `intros i_1 i ...` names seven of the eight binders --
# the `i <= 10` hypothesis is the one left for `intros _.` further down.
TACTICS = [
    "   \nintros i_1 i Hle Hlow Hup Hup_i Hsint.",
    "   \nassert (Hrange: -9 <= i <= 9) by lia.",
    "   \ndestruct Hrange as [Hi_low Hi_up].",
    "   \nSearch Z.abs.",
    "   \nassert (Hi_abs_le : Z.abs i <= 9) by now apply Z.abs_le.",
    "   \nrewrite <- Z.abs_square.",
    "   \nassert (0 <= Z.abs i) by apply Z.abs_nonneg.",
    "   \nassert (Habs_sq_le_81 : Z.abs i * Z.abs i <= 9 * 9) by (apply Z.square_le_mono_nonneg; lia).",
    "   \nintros _.",
    "   \napply (Z.le_trans _ (9 * 9)); lia.",
    "   \nQed.",
]


@pytest.fixture(scope="module")
def coq():
    """One session on an untouched copy of the goal file.

    load() pops the trailing "Admitted." itself, so there is nothing to clean
    first; rewriting the file beforehand only invalidates coqpyt's disk cache
    and turns a warm load into a two-minute one.
    """
    config = ProofAgentConfig.from_file(str(config_file))
    skip_if_libraries_missing(config)

    coq_file = temp_example_copy("main_loop_invariant_2_established_Coq.v")
    interface = CoqInterface(
        file_path=str(coq_file),
        workspace=config.coq.workspace or str(coq_file.parent),
        library_paths=config.coq.library_paths,
        auto_setup_coqproject=config.coq.auto_setup_coqproject,
        coqproject_extra_options=config.coq.coqproject_extra_options,
        timeout=config.coq.timeout,
    )
    assert interface.load(), f"load() failed: {interface.get_last_error()}"
    try:
        yield interface
    finally:
        interface.close()


def test_the_known_good_proof_goes_through_to_qed(coq):
    """Every one of the eleven steps has to be accepted, in order."""
    assert coq.get_proof_status()["proof_steps"] == 1, "load() left more than 'Proof.'"
    goal_before = coq.get_goal_str()

    for i, tactic in enumerate(TACTICS, start=1):
        assert coq.apply_tactic(tactic), (
            f"step {i}, {tactic.strip()[:60]!r} failed: {coq.get_last_error()}"
        )
        # Step 1 is "Proof.", so the i-th tactic lands on step i + 1.
        assert coq.get_current_step_number() == i + 1, (
            f"step {i}: interface reports step {coq.get_current_step_number()}"
        )

    assert coq.get_goal_str() != goal_before

    steps = [step.text.strip() for step in coq.proof.steps]
    assert len(steps) == len(TACTICS) + 1
    assert steps[-1] == "Qed."
    # A query command is a proof step like any other as far as coqpyt is
    # concerned -- it is replayed with the rest of the script.
    assert "Search Z.abs." in steps

    assert coq.proof_file.unproven_proofs == [], "the goal is still unproven"
    # Known defect, recorded rather than fixed: is_proof_complete() reads
    # unproven_proofs, so it reports False precisely once Qed has landed.
    assert not coq.is_proof_complete()


def test_the_finished_proof_is_written_back_to_the_file(coq):
    """coqpyt persists accepted steps, which is how the agent saves a proof."""
    content = Path(coq.file_path).read_text(encoding="utf-8")

    assert "Admitted." not in content, "the terminator was never replaced"
    assert "Qed." in content
    assert "apply (Z.le_trans _ (9 * 9)); lia." in content
