"""
InteractiveSessionManager: REPL wrapper around ProofController for collaborative
human-agent proof development.

Commands:
  step              — agent takes one tactic/rollback action
  run               — agent runs until subgoal changes, failure, or proof complete
  tactic <tac>      — apply user-supplied tactic
  hint <text>       — inject natural-language hint into next agent step
  rollback [n]      — undo last n tactics (user or agent, default 1)
  search <cmd>      — run a Rocq query (e.g. Search Z.add, Print Z.add_comm, Check Z.add)
  status            — display current proof state
  tree              — display proof tree
  explain           — show agent reasoning trace
  help              — show this help
  quit              — exit
"""

from pathlib import Path
from typing import Optional

from agent.proof_controller import ProofController
from agent import visualizer
from utils.logger import setup_logger

_COMMANDS = [
    "step", "run", "tactic ", "hint ", "rollback", "search ",
    "status", "tree", "explain", "help", "quit",
]


class InteractiveSessionManager:
    def __init__(self, controller: ProofController):
        self.controller: ProofController = controller
        self._gen = None
        self._done: bool = False
        self.logger = setup_logger("InteractiveSession")
        self._readline_available = False
        self._history_file: Optional[Path] = None
        self._setup_readline()

    def _setup_readline(self):
        try:
            import readline
        except ImportError:
            return # not available on Windows

        self._readline_available = True
        self._history_file = Path.home() / ".autorocq_history"

        if self._history_file.exists():
            try:
                readline.read_history_file(str(self._history_file))
            except OSError:
                pass

        readline.set_completer(self._completer)
        readline.parse_and_bind("tab: complete")

    def _completer(self, text: str, state: int) -> Optional[str]:
        matches = [c for c in _COMMANDS if c.startswith(text)]
        return matches[state] if state < len(matches) else None

    def _save_readline_history(self):
        if not self._readline_available or self._history_file is None:
            return
        try:
            import readline
            readline.write_history_file(str(self._history_file))
        except ImportError:
            pass # not available on Windows
        except OSError:
            pass

    #####################
    ## Public API      ##
    #####################

    def start(self, theorem_name: Optional[str] = None):
        """Initialize the proof session and run the REPL."""
        self.logger.debug(f"Starting interactive session: theorem={theorem_name!r}")

        preexisting = self._extract_and_reset_tactics()

        if not self.controller._init_proof_session(theorem_name):
            print("❌ Failed to initialize proof session.")
            return False

        self._gen = self.controller.step_generator()
        self._done = False

        if preexisting:
            print(f"🔄 Replaying {len(preexisting)} pre-existing tactic(s)...")
            self.logger.debug(f"Pre-existing tactics to replay: {preexisting}")
            for tactic in preexisting:
                self._do_user_tactic(tactic, silent=True)
                if self._done:
                    break

        self._display_state()
        if not self._done:
            print("Interactive mode. Type 'help' for available commands.")
            self._do_help()
            self._repl()

        self.controller._finish_proof(self.controller._tactics_with_states)
        return self.controller.is_successful

    #####################
    ## REPL            ##
    #####################

    def _repl(self):
        while not self._done:
            try:
                raw = input("autorocq> ").strip()
            except (EOFError, KeyboardInterrupt) as e:
                self.logger.debug(f"REPL interrupted: {e}")
                self._do_quit()
                return

            if not raw:
                continue

            cmd, _, arg = raw.partition(" ")
            self.logger.debug(f"User Command: {raw!r}")
            match cmd:
                case "step":
                    self._do_step()
                case "run":
                    self._do_run()
                case "tactic":
                    self._do_user_tactic(arg.strip())
                case "hint":
                    self._do_hint(arg.strip())
                case "rollback":
                    n = 1
                    if arg.strip():
                        try:
                            n = int(arg.strip())
                            if n <= 0:
                                raise ValueError
                        except ValueError:
                            print("Usage: rollback [n]  (n must be a positive integer)")
                            continue
                    self._do_rollback(n)
                case "search":
                    self._do_search(arg.strip())
                case "status":
                    self._display_state()
                case "tree":
                    self._do_tree()
                case "explain":
                    self._do_explain()
                case "help":
                    self._do_help()
                case "quit":
                    self._do_quit()
                    return
                case _:
                    print(f"Unknown command: {cmd!r}")
                    self._do_help()

    #####################
    ## Commands        ##
    #####################

    def _do_step(self):
        result = self._advance_one()
        if result is None:
            return
        self._report(result)
        if result['type'] != 'done':
            self._display_state()

    def _do_run(self):
        goals_before = self.controller.coq.get_goal_str()
        while not self._done:
            result = self._advance_one()
            if result is None:
                return
            self._report(result)
            if result['type'] == 'done':
                return
            if result['type'] == 'rollback':
                self._display_state()
                return
            if result.get('proof_complete'):
                return
            current_goals = self.controller.coq.get_goal_str()
            if current_goals != goals_before:
                self._display_state()
                return

    def _do_user_tactic(self, tactic: str, silent: bool = False):
        if not tactic:
            print("Usage: tactic <tactic_string>")
            return

        if not tactic.endswith('.'):
            tactic += '.'

        subgoals_before = self.controller.coq.get_subgoals()
        goals_before = self.controller.coq.get_goal_str()
        hyps_before = self.controller.coq.get_hypothesis()

        success = self.controller.coq.apply_tactic(tactic)
        if not success:
            error = self.controller.coq.get_last_error()
            self.logger.debug(f"User Tactic failed: {tactic!r} — {error}")
            print(f"Tactic failed: {error}")
            return

        goals_after = self.controller.coq.get_goal_str()
        hyps_after = self.controller.coq.get_hypothesis()
        subgoals_after = self.controller.coq.get_subgoals()

        self.controller.global_step_id += 1
        tactic_with_state = self.controller._handle_successful_tactic(
            tactic, subgoals_before, subgoals_after,
            goals_before or '', goals_after or '',
            hyps_before or '', hyps_after or ''
        )
        tactic_with_state['source'] = 'user'
        self.controller._tactics_with_states.append(tactic_with_state)
        self.logger.debug(f"User Tactic applied: {tactic!r}")

        if not silent:
            print(f"✅ Tactic applied: {tactic}")

        status = self.controller.coq.get_proof_completion_status()
        if status.get('is_complete') and status.get('qed_already_applied'):
            print("🎉 Proof complete!")
            self.controller.is_successful = True
            self._done = True
        elif not silent:
            self._display_state()

    def _do_hint(self, hint: str):
        if not hint:
            print("Usage: hint <text>")
            return
        self.logger.debug(f"User Hint queued: {hint!r}")
        self.controller._pending_hints.append(hint)
        print("Hint queued for next agent step.")

    def _do_rollback(self, n: int):
        history = self.controller._tactics_with_states
        if not history:
            print("No tactics to roll back.")
            return

        actual_n = min(n, len(history))
        if actual_n < n:
            print(f"Warning: only {len(history)} tactic(s) applied; rolling back all.")

        remaining = history[:-actual_n]
        target_step_number = remaining[-1]['step_number'] if remaining else 0

        # Pop steps from CoqPyt
        proof = self.controller.coq.get_unproven_proof()
        if proof:
            for _ in range(actual_n):
                self.controller.coq.proof_file.pop_step(proof)
        self.controller.coq.proof = self.controller.coq.get_unproven_proof()

        # Update proof tree
        if self.controller.proof_tree is not None:
            self.controller.proof_tree.delete_subtree_by_step_number(target_step_number)

        self.controller._tactics_with_states[:] = remaining

        self.logger.debug(f"User rollback: {actual_n} tactic(s)")
        print(f"Rolled back {actual_n} tactic(s).")
        self._display_state()

    def _do_search(self, cmd: str):
        if not cmd:
            print("Usage: search <Rocq command>  (e.g. search Search Z.add  |  search Print Z.add_comm)")
            return
        cs = self.controller.context_manager.context_search
        if cs is None:
            print("Context search is disabled in this session.")
            return
        goal_context = self.controller.coq.get_goal_str() or ""
        result = cs.search(cmd, goal_context=goal_context)
        if result and result.content:
            print(result.content)
        else:
            print(f"No results for '{cmd}'.")

    def _do_explain(self):
        print(visualizer.render_explain(self.controller.context_manager))

    def _do_help(self):
        print("Commands:")
        print("  step              — agent takes one action (tactic or rollback)")
        print("  run               — agent runs until subgoal changes, rollback, or proof complete")
        print("  tactic <tac>      — apply a user-supplied tactic")
        print("  hint <text>       — inject hint into next agent step")
        print("  rollback [n]      — undo last n tactics, user or agent (default 1)")
        print("  search <cmd>      — run a Rocq query, e.g. 'search Search Z.add' or 'search Print Z.add_comm'")
        print("  status            — display current proof state")
        print("  tree              — display proof tree")
        print("  explain           — show agent reasoning trace")
        print("  help              — show this help")
        print("  quit              — exit")

    def _do_tree(self):
        print(visualizer.render_tree(self.controller.proof_tree))

    def _do_quit(self):
        self._save_readline_history()
        self._done = True

    ###########################
    ## Internal helpers      ##
    ###########################

    def _extract_and_reset_tactics(self) -> list:
        """Extract and pop pre-existing tactics so _init_proof_session sees a clean state."""
        coq = self.controller.coq
        proof = coq.get_unproven_proof()
        if not proof or len(proof.steps) <= 1:
            return []

        tactics = [step.text.strip() for step in proof.steps[1:]]

        for _ in range(len(tactics)):
            coq.proof_file.pop_step(proof)

        coq.proof = coq.get_unproven_proof()
        return tactics

    def _advance_one(self):
        if self._gen is None or self._done:
            return None
        try:
            result = next(self._gen)
            if result.get('type') == 'done' or result.get('proof_complete'):
                self._done = True
            return result
        except StopIteration:
            self._done = True
            return {'type': 'done', 'success': self.controller.is_successful}

    def _display_state(self):
        goals = self.controller.coq.get_goal_str() or ""
        print(visualizer.render_state(goals))

    def _report(self, result):
        t = result.get('type')
        if t == 'tactic':
            tactic = result.get('tactic', '?')
            success = result.get('success', False)
            print(visualizer.render_action('tactic', tactic, success), end='')
            if success and result.get('proof_complete'):
                print("🎉 Proof complete!")
            elif not success:
                print(f"  — {result.get('error', '')}")
        elif t == 'rollback':
            if result.get('success'):
                print(f"Agent rolled back {result.get('distance', '?')} step(s).")
            else:
                print("Agent rollback failed.")
        elif t == 'done':
            if result.get('success'):
                print("🎉 Proof complete!")
            else:
                print("Session ended (max steps reached or proof failed).")
