"""Executable contracts for AutoRocq paper Section 4.3.

These tests use a scripted decision source, not an LLM API.  They exercise the
same ProofController loop while keeping ordinary pytest runs deterministic and
free of credentials or network calls.
"""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from agent.proof_controller import ProofController


TREE = "0. Proof.\n   Goal: target\n   Status: Open"


class ScriptedContextManager:
    def __init__(self, decisions, history=None, query_result="query result"):
        self.decisions = list(decisions)
        self.history = list(history or [])
        self.query_result = query_result
        self.prompts = []
        self.history_requests = []
        self.enable_history_context = bool(history)
        self.chat_session = SimpleNamespace(messages=[], current_plan="")

    def build_initial_prompt(self, _proof_tree):
        return "initial context"

    def get_action(self, prompt, **_kwargs):
        self.prompts.append(prompt)
        return self.decisions.pop(0), f"call-{len(self.prompts)}"

    @staticmethod
    def get_tactic(tactic, _tool_call_id):
        return tactic if tactic.endswith(".") else tactic + "."

    def handle_query_call(self, query, _tool_call_id):
        return f"Query executed: {query}\n\n{self.query_result}", True

    def handle_plan_call(self, plan, _tool_call_id):
        self.chat_session.current_plan = plan
        return "plan recorded"

    def should_give_up(self):
        return "give up" in self.chat_session.current_plan

    def get_similar_history(self, proof_state, n=5):
        self.history_requests.append((proof_state, n))
        return self.history[:n]


class RejectingCoq:
    def __init__(self, errors):
        self.errors = list(errors)
        self.last_error = None
        self.proof = SimpleNamespace(steps=[SimpleNamespace(step="Proof.")])

    def get_goal_str(self):
        return "target"

    def get_hypothesis(self):
        return "H: premise"

    def get_subgoals(self):
        return ["target"]

    def apply_tactic(self, _tactic):
        self.last_error = self.errors.pop(0)
        return False

    def get_last_error(self):
        return self.last_error


class SequencedCoq(RejectingCoq):
    def __init__(self, outcomes):
        super().__init__([])
        self.outcomes = list(outcomes)

    def apply_tactic(self, tactic):
        success, error = self.outcomes.pop(0)
        self.last_error = error
        if success:
            self.proof.steps.append(SimpleNamespace(step=tactic))
        return success

    @staticmethod
    def get_proof_completion_status():
        return {"is_complete": False, "qed_already_applied": False}


class GoalChangingCoq(SequencedCoq):
    def __init__(self):
        super().__init__([(True, None)])
        self.goal = "target"

    def get_goal_str(self):
        return self.goal

    def get_subgoals(self):
        return [self.goal]

    def apply_tactic(self, tactic_text):
        success = super().apply_tactic(tactic_text)
        self.goal = "next target"
        return success


class StaticProofTree:
    @staticmethod
    def get_proof_tree_string():
        return TREE


def tactic(command):
    return {"type": "tactic", "content": command}


def query(command):
    return {"type": "query", "content": command}


def give_up():
    return {"type": "plan", "content": "give up"}


def make_controller(decisions, errors, *, feedback=True, history=None):
    controller = ProofController.__new__(ProofController)
    controller.logger = Mock()
    controller.context_manager = ScriptedContextManager(decisions, history)
    controller.coq = RejectingCoq(errors)
    controller.proof_tree = StaticProofTree()
    controller.max_steps = 10
    controller.max_errors = 3
    controller.max_context_search = 3
    controller.enable_error_feedback = feedback
    controller.enable_hammer = False
    controller.gen_step_count = 0
    controller.global_step_id = 0
    controller.steps_since_restart = 0
    controller.successful_tactics = []
    controller.failed_tactics = []
    controller.query_commands = []
    controller._pending_hints = []
    controller._tactics_with_states = []
    controller.is_successful = False
    controller.give_up = False
    return controller


def run(controller):
    return list(controller.step_generator())


def test_one_rocq_error_returns_the_tactic_diagnostic_and_current_tree():
    controller = make_controller(
        [tactic("apply missing_lemma"), give_up()],
        ["The reference missing_lemma was not found"],
    )

    run(controller)

    feedback = controller.context_manager.prompts[1]
    assert "apply missing_lemma." in feedback
    assert "The reference missing_lemma was not found" in feedback
    assert "## CURRENT PROOF TREE:\n" + TREE in feedback


def test_disabling_error_feedback_hides_diagnostics_and_error_escalation_only():
    error = "The reference missing_lemma was not found"
    controller = make_controller(
        [
            tactic("apply candidate_one"),
            tactic("apply candidate_two"),
            tactic("apply candidate_three"),
            give_up(),
        ],
        [error, error, error],
        feedback=False,
    )

    run(controller)

    failure_feedback = controller.context_manager.prompts[1:]
    assert all("missing_lemma" not in prompt for prompt in failure_feedback)
    assert all("was not found" not in prompt for prompt in failure_feedback)
    assert all("## PERSISTENT ERROR" not in prompt for prompt in failure_feedback)
    assert all(
        "## CURRENT PROOF TREE:\n" + TREE in prompt
        for prompt in failure_feedback
    )


def test_three_repeats_of_the_same_error_request_context_then_return_its_result():
    error = "The reference needed_lemma was not found"
    controller = make_controller(
        [
            tactic("apply candidate_one"),
            tactic("apply candidate_two"),
            tactic("apply candidate_three"),
            query("Search (_ <= Z.abs _)."),
            give_up(),
        ],
        [error, error, error],
    )

    run(controller)

    escalation = controller.context_manager.prompts[3]
    assert "## PERSISTENT ERROR" in escalation
    assert "3 consecutive occurrences" in escalation
    assert "call the `query` tool" in escalation
    assert "## CURRENT PROOF TREE:\n" + TREE in escalation
    assert controller.query_commands == ["Search (_ <= Z.abs _)."]
    assert "query result" in controller.context_manager.prompts[4]


@pytest.mark.parametrize("threshold", [1, 3, 5])
def test_context_search_starts_at_the_configured_same_error_threshold(threshold):
    error = "The reference needed_lemma was not found"
    controller = make_controller(
        [tactic(f"apply candidate_{index}") for index in range(threshold)]
        + [give_up()],
        [error] * threshold,
    )
    controller.max_errors = threshold

    run(controller)

    failure_feedback = controller.context_manager.prompts[1:threshold + 1]
    assert all(
        "## PERSISTENT ERROR" not in prompt
        for prompt in failure_feedback[:-1]
    )
    assert "## PERSISTENT ERROR" in failure_feedback[-1]
    assert f"{threshold} consecutive occurrences" in failure_feedback[-1]


def test_persistent_errors_do_not_request_an_unavailable_query_tool():
    error = "The reference needed_lemma was not found"
    controller = make_controller(
        [
            tactic("apply candidate_one"),
            tactic("apply candidate_two"),
            tactic("apply candidate_three"),
            give_up(),
        ],
        [error, error, error],
    )
    controller.context_manager.enable_context_search = False

    run(controller)

    assert all(
        "## PERSISTENT ERROR" not in prompt
        for prompt in controller.context_manager.prompts
    )


def test_different_errors_do_not_masquerade_as_one_persistent_error():
    controller = make_controller(
        [
            tactic("apply first"),
            tactic("apply second"),
            tactic("apply third"),
            give_up(),
        ],
        ["unknown first", "type mismatch", "unknown third"],
    )

    run(controller)

    assert all(
        "## PERSISTENT ERROR" not in prompt
        for prompt in controller.context_manager.prompts
    )


def test_a_success_resets_the_persistent_error_streak():
    error = "The reference needed_lemma was not found"
    controller = make_controller(
        [
            tactic("apply first"),
            tactic("idtac"),
            tactic("apply second"),
            tactic("apply third"),
            give_up(),
        ],
        [],
    )
    controller.coq = SequencedCoq([
        (False, error),
        (True, None),
        (False, error),
        (False, error),
    ])

    def record_success(tactic_text, _before, _after, goals_before, goals_after,
                       hypotheses_before, hypotheses_after):
        return {
            "tactic": tactic_text,
            "goals_before": goals_before,
            "goals_after": goals_after,
            "hypotheses_before": hypotheses_before,
            "hypotheses_after": hypotheses_after,
            "step_number": controller.global_step_id,
        }

    controller._handle_successful_tactic = record_success

    run(controller)

    assert all(
        "## PERSISTENT ERROR" not in prompt
        for prompt in controller.context_manager.prompts
    )


def test_top_five_complete_history_records_are_in_the_initial_decision_context():
    records = [
        {
            "tactic": f"historical_{index}.",
            "goals_before": f"goal before {index}",
            "goals_after": f"goal after {index}",
            "hypotheses_before": f"H{index}: before",
            "hypotheses_after": f"H{index}: after",
            "theorem_name": f"theorem_{index}",
            "step_number": index,
            "source": "agent",
            "similarity_score": 1.0 - index / 10,
        }
        for index in range(6)
    ]
    controller = make_controller([give_up()], [], history=records)

    run(controller)

    initial = controller.context_manager.prompts[0]
    assert "## TOP-5 HISTORICAL TACTICS" in initial
    for index in range(5):
        assert f"historical_{index}." in initial
        assert f"goal before {index}" in initial
        assert f"goal after {index}" in initial
        assert f"H{index}: before" in initial
        assert f"H{index}: after" in initial
        assert f"theorem_{index}" in initial
        assert f"Step: {index}" in initial
    assert "historical_5." not in initial
    assert controller.context_manager.history_requests == [("target", 5)]


def test_top_five_history_is_recomputed_after_the_goal_changes():
    record = {
        "tactic": "historical.",
        "goals_before": "old goal",
        "goals_after": "new goal",
        "hypotheses_before": "H: before",
        "hypotheses_after": "H: after",
        "theorem_name": "historical_theorem",
        "step_number": 1,
        "source": "agent",
    }
    controller = make_controller([tactic("progress"), give_up()], [], history=[record])
    controller.coq = GoalChangingCoq()
    controller._handle_successful_tactic = lambda *args: {
        "tactic": args[0],
        "goals_before": args[3],
        "goals_after": args[4],
        "hypotheses_before": args[5],
        "hypotheses_after": args[6],
        "step_number": controller.global_step_id,
    }

    run(controller)

    assert controller.context_manager.history_requests == [
        ("target", 5),
        ("next target", 5),
    ]
    assert "historical." in controller.context_manager.prompts[0]
    assert "historical." in controller.context_manager.prompts[1]


def test_successful_proof_records_the_complete_state_transition():
    captured = []
    controller = ProofController.__new__(ProofController)
    controller.current_theorem_name = "paper_example"
    controller.context_manager = SimpleNamespace(
        tactic_history=SimpleNamespace(
            add_successful_tactic=lambda **entry: captured.append(entry)
        )
    )
    state = {
        "tactic": "assumption.",
        "goals_before": "P",
        "goals_after": "",
        "hypotheses_before": "HP: P",
        "hypotheses_after": "HP: P",
        "step_number": 4,
        "source": "user",
    }

    controller._record_successful_proof([state])

    assert captured == [
        {
            **state,
            "theorem_name": "paper_example",
        }
    ]
