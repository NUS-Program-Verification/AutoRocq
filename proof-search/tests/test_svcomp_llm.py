"""
The full agent on the SV-COMP goal: ContextController + context search +
error feedback, driven by a live model.

Where test_controller_prove.py checks the bare prove_theorem() contract, this
run has context search and error feedback on, so it also pins that the query
commands the model issues are recorded separately from tactics and never end up
in the proof script.

The old version tallied everything the run produced, printed a verdict in three
tiers ("SUCCESSFUL" / "PARTIALLY SUCCESSFUL" / "STRUGGLED"), and returned
is_complete -- which pytest ignores, so all three tiers passed identically, as
did a run that raised before the model was ever called. Like its sibling it
printed `controller.step_count`, which at the time did not exist; the
AttributeError was swallowed by the blanket `except Exception`. That is the
counter's name now.
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
THEOREM = "main_loop_invariant_2_established"
MAX_STEPS = 100

QUERY_PREFIXES = ("Search", "Print", "Locate", "About", "Check")


@pytest.mark.llm
def test_the_agent_runs_the_goal_and_keeps_its_books_straight(tmp_path):
    config = ProofAgentConfig.from_file(str(config_file))
    skip_if_libraries_missing(config)

    coq_file = temp_example_copy("main_loop_invariant_2_established_Coq.v")
    coq = CoqInterface(
        file_path=str(coq_file),
        workspace=config.coq.workspace or str(coq_file.parent),
        library_paths=config.coq.library_paths,
        auto_setup_coqproject=config.coq.auto_setup_coqproject,
        coqproject_extra_options=config.coq.coqproject_extra_options,
        timeout=config.coq.timeout,
    )
    assert coq.load(), f"load() failed: {coq.get_last_error()}"

    try:
        context_manager = ContextManager(
            coq,
            api_key=config.llm.api_key,
            enable_history_context=getattr(config, "enable_history_context", True),
            enable_context_search=getattr(config, "enable_context_search", True),
        )
        assert context_manager.chat_session is not None
        assert context_manager.model, "no model configured"

        controller = ProofController(
            coq_interface=coq,
            context_manager=context_manager,
            max_steps=MAX_STEPS,
            enable_recording=False,
            enable_error_feedback=getattr(config, "enable_error_feedback", True),
            max_context_search=getattr(config, "max_context_search", 3),
            output_dir=str(tmp_path),
        )

        assert coq.get_proof_status()["proof_steps"] == 1, "load() left more than 'Proof.'"

        success = controller.prove_theorem(THEOREM)

        assert isinstance(success, bool)
        assert success == controller.is_successful
        assert 0 <= controller.step_count <= MAX_STEPS

        script = [s.text.strip() for s in coq.proof.steps]
        assert script[0] == "Proof."

        # Query commands are recorded as queries, not as proven tactics.
        for query in controller.query_commands:
            assert query.strip().startswith(QUERY_PREFIXES), query
            assert query.strip() not in controller.successful_tactics
        assert not set(controller.successful_tactics) & set(controller.failed_tactics)

        # The run artifacts land in output_dir whatever the outcome.
        tree_json = tmp_path / f"{THEOREM}_proof_tree_final.json"
        assert (tmp_path / f"{THEOREM}_proof_tree_final.png").exists()
        assert tree_json.exists()
        assert json.loads(tree_json.read_text())["root"]["tactic"] == "Proof."

        if success:
            assert script[-1] == "Qed."
            assert coq.proof_file.unproven_proofs == []
            assert "Admitted." not in Path(coq.file_path).read_text(encoding="utf-8")
        else:
            assert coq.proof_file.unproven_proofs, (
                "the run reported failure but the goal is closed"
            )
            # A failed run still has to leave the session usable.
            assert coq.get_goal_str().strip()
    finally:
        coq.close()
