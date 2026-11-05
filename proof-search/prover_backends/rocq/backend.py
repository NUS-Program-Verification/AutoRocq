import re
from dataclasses import dataclass

from prover_backends.rocq.session import RocqSession, RocqSessionDesync
from prover_backends.types import CompletionStatus, Goal, TacticEffect
from prover_backends.rocq.text import count_goals, extract_goal_pattern, extract_essential_proof_content, hints_from_error
from .text import _clean_goals_str
from .prompts import SYSTEM_PROMPT, TACTIC_INSTRUCTION, GUIDELINES, TACTIC_TOOL, QUERY_TOOL
from .search import RocqContextSearch


@dataclass(frozen=True)
class _Checkpoint:
    owner: object
    steps: tuple[str, ...]


class RocqBackend:
    """Adapt a Rocq session to the agent's prover-independent contract."""

    system_prompt = SYSTEM_PROMPT
    tactic_instruction = TACTIC_INSTRUCTION
    prompt_guidelines = GUIDELINES
    tactic_tool = TACTIC_TOOL
    query_tool = QUERY_TOOL
    default_tactic = "reflexivity"
    automation_tactic = "hammer."
    interactive_prompt = "autorocq> "
    history_filename = ".autorocq_history"
    query_help = "run a Rocq query, e.g. 'search Search Z.add' or 'search Print Z.add_comm'"
    proof_start_label = "Proof."
    extract_goal_pattern = staticmethod(extract_goal_pattern)
    count_goals = staticmethod(count_goals)
    error_hint = staticmethod(hints_from_error)

    def __init__(self, interface: RocqSession):
        self._interface = interface
        self._identity = object()
        self._search = None
        self._last_error = None

    @property
    def source_path(self):
        return self._interface.source_path

    @property
    def file_path(self):
        return self._interface.file_path

    def load(self):
        return self._interface.load()

    def restart(self):
        return self._interface.restart_coq_server()

    def close(self):
        self._interface.close()

    def has_active_proof(self):
        return self._interface.get_unproven_proof() is not None

    def _proof(self):
        proof = self._interface.proof or self._interface.get_unproven_proof()
        if proof is None:
            raise RocqSessionDesync("Cannot inspect Rocq state without an active proof")
        return proof

    def get_step_count(self):
        return len(self._proof().steps) - 1

    def _steps(self):
        proof = self._proof()
        return proof, tuple(step.text for step in proof.steps)

    def checkpoint(self):
        return _Checkpoint(self._identity, self._steps()[1])

    def matches_checkpoint(self, checkpoint):
        return (isinstance(checkpoint, _Checkpoint)
                and checkpoint.owner is self._identity
                and self._steps()[1] == checkpoint.steps)

    def restore(self, checkpoint):
        if not isinstance(checkpoint, _Checkpoint) or checkpoint.owner is not self._identity:
            raise RocqSessionDesync("Checkpoint belongs to a different Rocq session")
        proof, steps = self._steps()
        if steps[:len(checkpoint.steps)] != checkpoint.steps:
            raise RocqSessionDesync("Checkpoint is no longer an ancestor of the current proof")
        while len(proof.steps) > len(checkpoint.steps):
            count = len(proof.steps)
            self._interface.proof_file.pop_step(proof)
            if len(proof.steps) != count - 1:
                raise RocqSessionDesync("Rocq did not remove the expected proof step")
        self._interface.proof = proof
        self._interface._invalidate_goal_caches()
        if not self.matches_checkpoint(checkpoint):
            raise RocqSessionDesync("Rocq did not restore the requested checkpoint")

    def extract_and_reset_tactics(self):
        if not self.has_active_proof():
            return []
        proof, steps = self._steps()
        tactics = [step.strip() for step in steps[1:]]
        self.restore(_Checkpoint(self._identity, steps[:1]))
        return tactics

    @staticmethod
    def normalize_goal(goal):
        return Goal(goal.goal_id, str(goal.ty).strip(), RocqSession.format_hypotheses(goal))

    def get_goals(self):
        if self._interface._last_step_is_terminator(self._interface._current_proof()):
            return []
        answer = self._interface._get_current_goals_cached()
        if answer is None or answer.goals is None:
            raise RocqSessionDesync("Rocq goal state is unavailable")
        return [self.normalize_goal(goal) for goal in self._interface.get_subgoals()]

    def get_goal_str(self):
        return self._interface.get_goal_str()

    def get_hypothesis(self):
        return self._interface.get_hypothesis()

    def display_state(self):
        return _clean_goals_str(self.get_goal_str())

    @staticmethod
    def normalize_tactic(tactic):
        tactic = tactic.strip()
        structural = tactic in ('{', '}', '-', '+', '*') or re.fullmatch(r'\d+\s*:\s*\{', tactic)
        if tactic and not tactic.endswith('.') and not structural:
            tactic += '.'
        return tactic

    @staticmethod
    def classify_command(command):
        if command.startswith(("Search", "Print", "Check", "About")):
            return "query"
        if command in ("Abort.", "abort."):
            return "abort"
        if command in ("Admitted.", "admit."):
            return "admission"
        return "tactic"

    @staticmethod
    def tactic_effect(tactic):
        if (re.match(r"^\s*(?:cycle\b|focus\s+\d+\b|unfocus\b)", tactic, re.IGNORECASE)
                or re.fullmatch(r"\s*(?:\d+\s*:\s*)?[{}]\s*\.?\s*", tactic)):
            return TacticEffect("focus")
        if re.match(r"^\s*all\s*:", tactic, re.IGNORECASE):
            return TacticEffect("all")
        selector = re.match(r"^\s*(\d+)\s*:", tactic)
        return TacticEffect("single", int(selector.group(1)) - 1 if selector else 0)

    def apply_tactic(self, tactic):
        self._last_error = None
        if re.match(r"^\s*abort\b", tactic, re.IGNORECASE):
            self._last_error = "Abort is not a proof step and cannot enter the proof tree"
            return False
        if self.classify_command(self.normalize_tactic(tactic)) == "admission":
            self._last_error = "Admitted not allowed"
            return False
        if re.search(r"(?:^|[;.])\s*(?:shelve|shelve_unifiable|unshelve|give_up)\b", tactic, re.IGNORECASE):
            self._last_error = "Tactics that hide or restore shelved goals are not supported by proof-tree tracking"
            return False
        checkpoint = self.checkpoint()
        before_ids = {goal.goal_id for goal in self.get_goals()}
        if not self._interface.apply_tactic(tactic):
            self.restore(checkpoint)
            return False
        try:
            answer = self._interface._get_current_goals_cached()
            if answer is None or answer.goals is None:
                if self.completion_status().finalized:
                    return True
                raise RocqSessionDesync("Rocq goal state is unavailable after tactic")
            # Allow shelved existential witnesses that later unification can solve.
            if (answer.goals.given_up
                    or before_ids.intersection(goal.goal_id for goal in answer.goals.shelf)):
                self._last_error = "Tactic was reverted because a goal was shelved or given up"
            elif re.match(r"^\s*all\s*:", tactic, re.IGNORECASE) and self.get_goals():
                self._last_error = "The 'all:' tactical was reverted because it did not close every open goal"
            if self._last_error:
                self.restore(checkpoint)
                return False
        except Exception:
            self.restore(checkpoint)
            raise
        return True

    def get_last_error(self):
        return self._last_error or self._interface.get_last_error()

    @staticmethod
    def include_in_history_feedback(tactic):
        return tactic not in ('{', '}')

    def completion_status(self):
        status = self._interface.get_proof_completion_status()
        return CompletionStatus(status['ready_for_qed'], status['is_complete'] and status['qed_already_applied'])

    def finalize(self):
        checkpoint = self.checkpoint()
        if self._interface.apply_qed():
            return True
        self.restore(checkpoint)
        return False

    def get_proof_file_content(self):
        return self._interface.get_proof_file_content()

    def extract_proof_context(self, content):
        interface = self._interface
        return extract_essential_proof_content(
            interface.logger, content, proof=interface.proof,
            file_context=getattr(interface.proof_file, 'context', None),
            file_path=interface.file_path,
        )

    def _context_search(self):
        if self._search is None:
            self._search = RocqContextSearch(self._interface)
        return self._search

    def search(self, query, goal_context=""):
        return self._context_search().search(query, goal_context)

    def search_by_type(self, query_type, identifier=None, pattern=None, goal_context=""):
        return self._context_search().execute_coq_query(query_type, identifier, pattern, goal_context)
