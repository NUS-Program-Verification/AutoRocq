import re

from prover_backends.interface import ProverInterface
from prover_backends.types import TacticEffect
from prover_backends.rocq.text import count_goals, extract_goal_pattern, hints_from_error
from .text import _clean_goals_str
from .prompts import SYSTEM_PROMPT, TACTIC_INSTRUCTION, GUIDELINES, TACTIC_TOOL, QUERY_TOOL
from .search import RocqContextSearch


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

    def __init__(self, interface: ProverInterface):
        self._interface = interface
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
        return self._interface.restart()

    def close(self):
        self._interface.close()

    def has_active_proof(self):
        return self._interface.has_active_proof()

    def get_step_count(self):
        return self._interface.get_step_count()

    def checkpoint(self):
        return self._interface.checkpoint()

    def matches_checkpoint(self, checkpoint):
        return self._interface.matches_checkpoint(checkpoint)

    def restore(self, checkpoint):
        return self._interface.restore(checkpoint)

    def extract_and_reset_tactics(self):
        return self._interface.extract_and_reset_tactics()

    def get_goals(self):
        return self._interface.get_goal_state().goals

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
        if not self._interface.execute(tactic):
            return False
        try:
            state = self._interface.get_goal_state()
            # Allow shelved existential witnesses that later unification can solve.
            if (state.given_up
                    or before_ids.intersection(goal.goal_id for goal in state.shelved)):
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
        return self._interface.completion_status()

    def finalize(self):
        return self._interface.finalize()

    def get_proof_file_content(self):
        return self._interface.get_proof_file_content()

    def extract_proof_context(self, content):
        return self._interface.extract_proof_context(content)

    def _context_search(self):
        if self._search is None:
            self._search = RocqContextSearch(self._interface)
        return self._search

    def search(self, query, goal_context=""):
        return self._context_search().search(query, goal_context)

    def search_by_type(self, query_type, identifier=None, pattern=None, goal_context=""):
        return self._context_search().execute_coq_query(query_type, identifier, pattern, goal_context)
