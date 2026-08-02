import logging
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.coq_interface import CoqInterface  # noqa: E402


class _FakeProofFile:
    def __init__(self):
        self.invalidate_calls = 0
        self.current_goals_calls = 0

        class _FakeGoalConfig:
            goals = []
            stack = []

        class _FakeGoalAnswer:
            def __init__(self):
                self.goals = _FakeGoalConfig()

            def __str__(self):
                return "fake-goals"

        self._goal_answer = _FakeGoalAnswer()

    def invalidate_goal_cache(self):
        self.invalidate_calls += 1

    @property
    def current_goals(self):
        self.current_goals_calls += 1
        return self._goal_answer


class _FakeStep:
    def __init__(self, text):
        self.text = text


def _new_coq(proof_steps):
    coq = object.__new__(CoqInterface)
    coq.proof_file = _FakeProofFile()
    coq.proof = type("FakeProof", (), {"steps": list(proof_steps)})()
    coq.logger = logging.getLogger("test_coq_interface_goal_cache")
    coq.__dict__["_CoqInterface__goal_cache_key"] = None
    coq.__dict__["_CoqInterface__cached_goals"] = None
    return coq


def test_get_goal_str_and_get_subgoals_share_goal_cache():
    coq = _new_coq([_FakeStep("intro.")])

    first = coq.get_goal_str()
    second = coq.get_subgoals()

    assert first == "fake-goals"
    assert second == []
    assert coq.proof_file.current_goals_calls == 1
    assert coq.proof_file.invalidate_calls == 1


def test_goal_cache_refreshes_after_proof_mutates():
    coq = _new_coq([_FakeStep("intro.")])

    coq.get_goal_str()
    coq.proof.steps.append(_FakeStep("apply."))
    coq.get_goal_str()

    assert coq.proof_file.current_goals_calls == 2
