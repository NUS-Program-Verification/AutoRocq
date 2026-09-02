"""
ProofController.prove_theorem() end to end against a live model.

The model is not deterministic, so this asserts the controller's own contract
rather than "the proof succeeds": the return value agrees with is_successful,
the step budget is respected, the bookkeeping lists match the tactics that were
applied, the run artifacts are written, and the final proof state agrees with
the verdict.

The old version returned True/False from every branch -- pytest ignores that --
so it passed whether prove_theorem() proved the goal, crashed, or was never
reached because clean_proof_file() failed first. It also printed
`controller.step_count`, an attribute ProofController does not have; the
resulting AttributeError was swallowed by the blanket `except Exception` and
reported as "❌ Test failed", which still passed.
"""

import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from agent.context_manager import ContextManager
from agent.proof_controller import ProofController
from backend.coq_interface import CoqInterface
from tests.test_utils import skip_if_libraries_missing, temp_example_copy
from utils.config import ProofAgentConfig

config_file = PROJECT_ROOT / "configs" / "default_config.json"
THEOREM = "wp_goal"
MAX_STEPS = 15


@pytest.mark.llm
def test_prove_theorem_reports_an_outcome_that_matches_the_proof(tmp_path):
    config = ProofAgentConfig.from_file(str(config_file))
    skip_if_libraries_missing(config)

    coq_file = temp_example_copy("main_loop_invariant_2_established_Coq.v")
    coq = CoqInterface(
        file_path=str(coq_file),
        workspace=config.coq.workspace or str(coq_file.parent),
        library_paths=config.coq.library_paths,
        auto_setup_coqproject=config.coq.auto_setup_coqproject,
        timeout=config.coq.timeout,
    )
    assert coq.load(), f"load() failed: {coq.get_last_error()}"

    try:
        controller = ProofController(
            coq_interface=coq,
            context_manager=ContextManager(
                coq,
                api_key=config.llm.api_key,
                enable_history_context=getattr(config, "enable_history_context", True),
                enable_context_search=False,  # keep this run to one moving part
            ),
            max_steps=MAX_STEPS,
            enable_recording=False,
            output_dir=str(tmp_path),
        )

        success = controller.prove_theorem(THEOREM)

        # --- the verdict is a real bool and agrees with the controller state
        assert isinstance(success, bool), type(success)
        assert success == controller.is_successful
        assert controller.current_theorem_name == THEOREM

        # --- the step budget was respected
        assert 0 <= controller.gen_step_count <= MAX_STEPS, controller.gen_step_count
        assert controller.global_step_id >= controller.gen_step_count

        # --- bookkeeping matches what actually went into the proof
        applied = [s.text.strip() for s in coq.proof.steps][1:]  # drop "Proof."
        assert len(controller.successful_tactics) + len(controller.query_commands) >= 0
        for tactic in controller.successful_tactics:
            assert tactic.strip() in " ".join(applied), (
                f"{tactic.strip()!r} is recorded as successful but is not in the script"
            )
        assert not set(controller.successful_tactics) & set(controller.failed_tactics), (
            "a tactic is recorded as both successful and failed"
        )

        # --- the run artifacts are written either way
        png = tmp_path / f"{THEOREM}_proof_tree_final.png"
        tree_json = tmp_path / f"{THEOREM}_proof_tree_final.json"
        assert png.exists(), sorted(p.name for p in tmp_path.iterdir())
        assert tree_json.exists(), sorted(p.name for p in tmp_path.iterdir())

        tree = json.loads(tree_json.read_text())
        assert tree["root"]["tactic"] == "Proof."
        assert "metadata" in tree

        # --- and the file on disk agrees with the verdict
        content = Path(coq.file_path).read_text(encoding="utf-8")
        if success:
            assert coq.proof.steps[-1].text.strip() == "Qed."
            assert "Qed." in content
            assert coq.proof_file.unproven_proofs == []
        else:
            assert coq.proof_file.unproven_proofs, (
                "prove_theorem() reported failure but left no open proof"
            )
    finally:
        coq.close()
