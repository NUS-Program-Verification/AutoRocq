import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from agent.history_recorder import TacticHistoryManager
from agent.proof_controller import ProofController


class _Tree:
    def get_proof_tree_string(self):
        return "root -> goal"


class _Context:
    def __init__(self, enable_context_search=True, enable_history_context=False, entries=None):
        self.enable_context_search = enable_context_search
        self.enable_history_context = enable_history_context
        self._entries = entries or []

    def get_similar_history(self, _proof_state, n=5):
        return self._entries[:n]


class _Coq:
    def __init__(self, goal, hypothesis):
        self._goal = goal
        self._hypothesis = hypothesis

    def get_goal_str(self):
        return self._goal

    def get_hypothesis(self):
        return self._hypothesis


def test_error_streak_uses_normalized_diagnostics():
    controller = object.__new__(ProofController)
    controller._last_normalized_error = None
    controller._consecutive_same_error = 0

    assert controller._update_error_streak("\x1b[31mError:\x1b[0m  foo\nbar") == 1
    assert controller._update_error_streak("Error: foo   bar") == 2
    assert controller._update_error_streak("Different error") == 1


def test_rejected_feedback_bundle_and_query_escalation():
    controller = object.__new__(ProofController)
    controller.enable_error_feedback = True
    controller.max_errors = 3
    controller.context_manager = _Context(enable_context_search=True, enable_history_context=False)
    controller.proof_tree = _Tree()

    error_text = "The term \"I\" has type \"True\" while it is expected to have type \"False\"."
    feedback = controller._build_rejected_tactic_feedback("exact I.", error_text, same_error_streak=3)

    assert "Tactic: exact I." in feedback
    assert error_text in feedback
    assert "## CURRENT PROOF TREE:" in feedback
    assert "root -> goal" in feedback
    assert "Call `query` before trying another tactic." in feedback


def test_error_feedback_ablation_hides_diagnostic_and_escalation():
    controller = object.__new__(ProofController)
    controller.enable_error_feedback = False
    controller.max_errors = 3
    controller.context_manager = _Context(enable_context_search=True, enable_history_context=False)
    controller.proof_tree = _Tree()

    error_text = "Some Rocq error text."
    feedback = controller._build_rejected_tactic_feedback("exact I.", error_text, same_error_streak=5)

    assert "## CURRENT PROOF TREE:" in feedback
    assert "root -> goal" in feedback
    assert "Tactic: exact I." not in feedback
    assert error_text not in feedback
    assert "Call `query` before trying another tactic." not in feedback


def test_history_context_includes_complete_transition_fields():
    entries = [
        {
            "tactic": "intros.",
            "goals_before": "forall x, P x",
            "goals_after": "x : T |- P x",
            "hypotheses_before": "None",
            "hypotheses_after": "x : T",
            "theorem_name": "thm_a",
            "step_number": 2,
            "source": "agent",
        }
    ]
    controller = object.__new__(ProofController)
    controller.context_manager = _Context(enable_history_context=True, entries=entries)
    controller.coq = _Coq("forall x, P x", "")
    controller._history_context_signature = None

    feedback = controller._build_history_context_feedback(force_refresh=True)
    assert "RELEVANT SUCCESSFUL TRANSITIONS (TOP 5)" in feedback
    assert "tactic: intros." in feedback
    assert "theorem: thm_a" in feedback
    assert "step: 2" in feedback
    assert "source: agent" in feedback
    assert "hypotheses_before: None" in feedback
    assert "hypotheses_after: x : T" in feedback
    assert controller._build_history_context_feedback() == ""


def test_history_dedup_keeps_theorem_and_hypotheses_provenance(tmp_path):
    history_file = tmp_path / "history.json"
    manager = TacticHistoryManager(str(history_file))

    manager.add_successful_tactic(
        tactic="exact H.",
        goals_before="A",
        goals_after="",
        hypotheses_before="H : A",
        hypotheses_after="H : A",
        theorem_name="thm_one",
        step_number=1,
        source="agent",
    )
    manager.add_successful_tactic(
        tactic="exact H.",
        goals_before="A",
        goals_after="",
        hypotheses_before="H : A",
        hypotheses_after="H : A",
        theorem_name="thm_two",
        step_number=1,
        source="agent",
    )
    manager.add_successful_tactic(
        tactic="exact H.",
        goals_before="A",
        goals_after="",
        hypotheses_before="H1 : A",
        hypotheses_after="H1 : A",
        theorem_name="thm_one",
        step_number=1,
        source="agent",
    )
    manager.add_successful_tactic(
        tactic="exact H.",
        goals_before="A",
        goals_after="",
        hypotheses_before="H : A",
        hypotheses_after="H : A",
        theorem_name="thm_one",
        step_number=1,
        source="agent",
    )

    assert len(manager.entries) == 3

    similar = manager.get_similar_history("A", n=1)[0]
    assert "hypotheses_before" in similar
    assert "hypotheses_after" in similar
    assert "theorem_name" in similar
    assert "step_number" in similar
    assert "source" in similar
