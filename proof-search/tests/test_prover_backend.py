"""Exercise the agent without a native prover or prover-specific syntax."""

import subprocess
import sys
from pathlib import Path

import pytest

from agent.context_manager import ContextManager
from agent.interactive_session import InteractiveSessionManager
from agent.proof_controller import ProofController
from agent import visualizer
from prover_backends.types import CompletionStatus, Goal, SearchResult, TacticEffect


class ToyBackend:
    system_prompt = "Prove using the toy language."
    tactic_instruction = "Use advance and finish."
    prompt_guidelines = "Commands have no terminators."
    tactic_tool = {
        "type": "function",
        "function": {
            "name": "tactic",
            "description": "Use advance to change the toy goal or finish to solve it.",
            "parameters": {
                "type": "object", "properties": {"command": {"type": "string"}},
                "required": ["command"], "additionalProperties": False,
            },
        },
    }
    query_tool = {
        "type": "function",
        "function": {
            "name": "query",
            "description": "Use inspect to query the toy prover.",
            "parameters": {
                "type": "object", "properties": {"command": {"type": "string"}},
                "required": ["command"], "additionalProperties": False,
            },
        },
    }
    default_tactic = "advance"
    automation_tactic = "finish"
    proof_start_label = "begin"
    interactive_prompt = "toy> "
    history_filename = ".toy_history"
    query_help = "query the toy prover"

    def __init__(self, path):
        self.source_path = self.file_path = str(path)
        self.state = "initial"
        self.finalized = False
        self.commands = []
        self.steps = []
        self.queries = []
        self.restored = []
        self.refuse_finalization = False
        self.fail_restore = False

    def checkpoint(self):
        return ("opaque", self.state, len(self.steps))

    def get_step_count(self):
        return len(self.steps)

    def matches_checkpoint(self, checkpoint):
        return checkpoint == self.checkpoint()

    def restore(self, checkpoint):
        if self.fail_restore:
            raise RuntimeError("session lost")
        self.state = checkpoint[1]
        self.steps[:] = self.steps[:checkpoint[2]]
        self.restored.append(checkpoint)

    def has_active_proof(self):
        return True

    def get_goals(self):
        return [] if self.state == "solved" else [Goal("goal-1", self.state, "h : premise")]

    def get_goal_str(self):
        return "" if self.state == "solved" else self.state

    def get_hypothesis(self):
        return "h : premise"

    def display_state(self):
        return self.get_goal_str()

    def get_proof_file_content(self):
        return "toy theorem"

    def extract_proof_context(self, content):
        return content

    def normalize_tactic(self, tactic):
        return tactic.strip()

    def classify_command(self, command):
        return "query" if command == "inspect" else "tactic"

    def tactic_effect(self, command):
        return TacticEffect()

    def apply_tactic(self, command):
        self.commands.append(command)
        if command == "advance":
            self.state = "advanced"
        elif command == "finish":
            self.state = "solved"
        else:
            return False
        self.steps.append(command)
        return True

    def get_last_error(self):
        return "unknown toy command"

    def error_hint(self, command, error):
        return "Try advance."

    def include_in_history_feedback(self, tactic):
        return tactic != "structural"

    def completion_status(self):
        return CompletionStatus(self.state == "solved", self.finalized)

    def finalize(self):
        self.finalized = not self.refuse_finalization
        return self.finalized

    def search(self, query, goal_context=""):
        self.queries.append((query, goal_context))
        return SearchResult("toy context", "toy", result_size=11)

    def extract_goal_pattern(self, text):
        return text

    def count_goals(self, text):
        return int(bool(text))


def controller_for(tmp_path):
    backend = ToyBackend(tmp_path / "proof.toy")
    history = str(tmp_path / "history.json")
    context = ContextManager(backend, history_file=history, enable_caching=False)
    controller = ProofController(backend, context, history_file=history,
                                 enable_recording=False, output_dir=str(tmp_path))
    assert controller._init_proof_session("toy")
    return controller, backend


def test_automated_search_queries_rolls_back_and_finalizes(tmp_path):
    controller, backend = controller_for(tmp_path)
    actions = iter([
        {"type": "tactic", "content": "advance"},
        {"type": "query", "content": "inspect"},
        {"type": "rollback", "content": {"steps": 1, "reason": "retry"}},
        {"type": "tactic", "content": "advance"},
        {"type": "tactic", "content": "finish"},
    ])
    controller.context_manager.get_action = lambda *a, **k: (next(actions), "call")
    events = list(controller.step_generator())
    assert controller.is_successful and backend.finalized
    assert backend.commands == ["advance", "advance", "finish"]
    assert backend.queries == [("inspect", "advanced")]
    assert backend.restored == [("opaque", "initial", 0)]
    assert any(event['type'] == 'rollback' and event['success'] for event in events)
    assert not controller.proof_tree.open_subgoals
    assert "toy language" in controller.context_manager.chat_session.messages[0]['content']


def test_interactive_actions_share_checkpoints_and_require_finalization(tmp_path, monkeypatch):
    controller, backend = controller_for(tmp_path)
    monkeypatch.setattr(InteractiveSessionManager, '_setup_readline', lambda self: None)
    session = InteractiveSessionManager(controller)
    session._do_user_tactic("advance")
    assert controller._tactics_with_states[0]['source'] == 'user'
    session._do_rollback(1)
    assert backend.state == "initial"
    assert controller._tactics_with_states == []
    assert controller.proof_tree.current_goal(controller.proof_tree.root)[0] == "initial"
    backend.refuse_finalization = True
    session._do_user_tactic("finish")
    assert not session._done and not controller.is_successful
    backend.refuse_finalization = False
    assert controller._finalize_if_ready()
    assert backend.commands == ["advance", "finish"]


def test_tree_rejection_restores_backend_and_tree(tmp_path, monkeypatch):
    controller, backend = controller_for(tmp_path)
    before = backend.get_goals()
    tree = controller.proof_tree.to_dict()
    assert controller._apply_tactic("advance")

    def reject(*args):
        controller.proof_tree.root.children.clear()
        raise ValueError("unsupported transition")

    monkeypatch.setattr(controller, '_update_proof_tree', reject)
    assert not controller._handle_successful_tactic(
        "advance", before, backend.get_goals(), "initial", "advanced", "", "",
    )
    assert backend.state == "initial"
    assert controller.proof_tree.to_dict() == tree
    assert "unsupported transition" in controller.get_last_error()


def test_failed_restore_does_not_change_tree_or_history(tmp_path, monkeypatch):
    controller, backend = controller_for(tmp_path)
    monkeypatch.setattr(InteractiveSessionManager, '_setup_readline', lambda self: None)
    session = InteractiveSessionManager(controller)
    session._do_user_tactic("advance")
    tree = controller.proof_tree.to_dict()
    history = list(controller._tactics_with_states)
    backend.fail_restore = True
    with pytest.raises(RuntimeError, match="session lost"):
        session._do_rollback(1)
    assert controller.proof_tree.to_dict() == tree
    assert controller._tactics_with_states == history


def test_visualizer_preserves_normalized_goal_text():
    goal = Goal("one", "Stack: is part of this goal\nBullet: is also content", "h : T")
    rendered = visualizer.render_state(goal.conclusion)
    assert "Stack:" in rendered and "Bullet:" in rendered


def test_all_agent_modules_import_without_native_prover_dependencies():
    root = Path(__file__).resolve().parents[1]
    script = '''
import importlib.abc
import importlib
import pkgutil
import sys
class RejectNative(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, *args):
        if fullname.startswith(("coqpyt", "prover_backends.rocq")):
            raise AssertionError("Native dependency imported: " + fullname)
sys.meta_path.insert(0, RejectNative())
import agent
for item in pkgutil.iter_modules(agent.__path__):
    importlib.import_module("agent." + item.name)
'''
    result = subprocess.run([sys.executable, '-c', script], cwd=root,
                            text=True, capture_output=True, timeout=60)
    assert result.returncode == 0, result.stderr


def test_automation_records_the_command_that_actually_succeeded(tmp_path):
    controller, backend = controller_for(tmp_path)
    controller.enable_automation = True
    controller.max_errors = 0
    controller.context_manager.get_action = lambda *a, **k: (
        {"type": "tactic", "content": "invalid"}, "call",
    )
    events = list(controller.step_generator())
    assert controller.is_successful
    assert backend.commands == ["invalid", "finish"]
    assert controller._tactics_with_states[-1]['tactic'] == "finish"
    assert any(event.get('tactic') == 'finish' and event['success'] for event in events)


def test_history_feedback_uses_backend_filtering(tmp_path):
    controller, backend = controller_for(tmp_path)
    controller.context_manager.get_similar_history = lambda *a, **k: [
        {"tactic": "structural", "goals_before": "old"},
        {"tactic": "advance", "goals_before": "initial"},
    ]
    feedback = controller._provide_history_feedback(controller.max_errors + 1)
    assert "structural" not in feedback
    assert "advance" in feedback
