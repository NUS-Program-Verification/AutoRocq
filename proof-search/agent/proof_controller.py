import os

from pathlib import Path
from typing import Dict, Optional, Any, List
from backend.coq_interface import CoqInterface
from agent.context_manager import ContextManager
from agent.proof_tree import ProofTree
from agent import visualizer
from utils.recorder import create_proof_recorder
from utils.logger import clean_ansi_codes, setup_logger
from utils.coq_utils import hints_from_error, goal_diff
from utils.config import InteractiveConfig

class ProofController:
    """
    Main controller for the proof agent. Orchestrates the proof search process
    by coordinating between tactic generation, execution, and state management.
    """
    
    def __init__(
        self,
        coq_interface: CoqInterface,
        context_manager: ContextManager,
        max_steps: int = 50,
        max_errors: int = 3,
        enable_recording: bool = True,
        enable_error_feedback: bool = True,
        enable_hammer: bool = False,
        max_context_search: int = 3,
        history_file: str = "tactic_history.json",
        recording_output_dir: str = "data/statistics",
        interactive: Optional[InteractiveConfig] = None
    ):
        
        self.steps_since_restart = 0
        self.max_steps_before_restart = 200

        # Setup logger
        self.logger = setup_logger("ProofController")

        self.max_context_search = max_context_search
        self.enable_error_feedback = enable_error_feedback
        self.enable_hammer = enable_hammer
        
        self.coq = coq_interface
        self.context_manager = context_manager
        self.coq_chat_session = context_manager.chat_session
        
        self.is_successful = False
        self.give_up = False

        self.proof_tree = None

        # Interactive mode
        self.interactive = interactive or InteractiveConfig()

        self.max_steps = max_steps
        self.max_errors = max_errors

        # Initialize counters and history
        self.global_step_id = 0         # Global ID for tool call / proof step
        self.gen_step_count = 0         # Global step count for tactic / HL / rollback
        self.successful_tactics = []    # Global successful tactics
        self.failed_tactics = []        # Global failed tactics
        self.query_commands = []        # Global query commands

        # Interactive session state
        self._pending_hints: List[str] = []        # User hints to inject into next prompt
        self._tactics_with_states: List[Dict] = [] # All applied tactics (user + agent); source field distinguishes them
        
        # Initialize proof recorder
        self.enable_recording = enable_recording
        if self.enable_recording:
            try:
                self.recorder = create_proof_recorder(
                    output_dir=recording_output_dir,
                    auto_save=True
                )
            except Exception as e:
                self.logger.error(f"❌ Failed to initialize proof recorder: {e}")
                self.recorder = None
                self.enable_recording = False
        else:
            self.recorder = None
            self.logger.info(f"📊 Proof recording disabled")

        
        # Initialize tactic history manager with proper error handling and path consistency
        try:
            # Normalize the history file path to ensure consistency
            if not os.path.isabs(history_file):
                # Convert relative path to absolute path in the data directory
                current_dir = Path(__file__).parent.parent  # Go up to proof-search directory
                history_path = str(current_dir / "data" / history_file)
            else:
                history_path = history_file
            
            self.logger.info(f"📁 Normalized history path: {history_path}")
            
            # ALWAYS try to get it from context_manager first to avoid multiple instances
            if context_manager.tactic_history:
                existing_path = str(context_manager.tactic_history.history_file)
                self.logger.info(f"📁 ContextManager has existing history: {existing_path}")
                
                # Check if paths match (normalize both for comparison)
                if os.path.normpath(existing_path) == os.path.normpath(history_path):
                    self.tactic_history = context_manager.tactic_history
                    self.logger.info(f"✅ Using existing TacticHistoryManager from ContextManager (paths match)")
                else:
                    self.logger.warning(f"⚠️ Path mismatch - existing: {existing_path}, requested: {history_path}")
                    # Use existing one but log the discrepancy
                    self.tactic_history = context_manager.tactic_history
                    self.logger.warning(f"⚠️ Using existing TacticHistoryManager despite path mismatch")
                    
            else:
                # Create new instance only if context_manager doesn't have one
                from agent.history_recorder import TacticHistoryManager
                
                # Ensure the directory exists
                os.makedirs(os.path.dirname(history_path), exist_ok=True)
                
                self.tactic_history = TacticHistoryManager(history_path)
                self.logger.info(f"✅ Created new TacticHistoryManager: {history_path}")
                
                # Share it back to context_manager to avoid duplication
                if not context_manager.tactic_history:
                    context_manager.tactic_history = self.tactic_history
                    self.logger.info(f"📤 Shared TacticHistoryManager back to ContextManager")
                
            # Test the history manager
            stats = self.tactic_history.get_statistics()
            actual_path = str(self.tactic_history.history_file)
            self.logger.info(f"📊 Tactic history initialized: {stats.get('total_entries', 0)} existing entries")
            self.logger.info(f"📁 Final history file path: {actual_path}")
            
            # Verify file exists or can be created
            if Path(actual_path).exists():
                file_size = Path(actual_path).stat().st_size
                self.logger.info(f"📄 History file exists: {file_size} bytes")
            else:
                self.logger.info(f"📄 History file will be created on first save: {actual_path}")
            
        except Exception as e:
            import traceback
            self.logger.error(f"❌ Failed to initialize TacticHistoryManager: {e}")
            self.logger.error(f"📋 Full error trace: {traceback.format_exc()}")
            self.tactic_history = None         
    
    #####################
    ## Cleanup methods ##
    #####################
    
    def _check_for_cleanup(self):
        """Periodic memory cleanup and server restart."""
        if self.steps_since_restart > self.max_steps_before_restart:
            self.logger.info(f"🔄 Preventive maintenance after {self.steps_since_restart} steps")
            
            # Clean up large states first
            self._cleanup_large_states()
            
            if self.coq.restart_coq_server():
                self.steps_since_restart = 0
                # Reload current state
                self._reload_current_proof_state()
            else:
                self.logger.error("❌ Failed to restart Coq server")
    
    def _cleanup_large_states(self):
        """Clean up large proof states that might cause memory issues."""
        try:
            # Clear chat history if it gets too long
            if self.coq_chat_session:
                if hasattr(self.coq_chat_session, 'messages'):
                    messages = self.coq_chat_session.messages
                    if len(messages) > 20:  # Keep only last 20 messages
                        self.coq_chat_session.messages = messages[-20:]
                        self.logger.info("🧹 Cleaned up chat session history")
                
            # Clear query command history
            if len(self.query_commands) > 10:
                self.query_commands = self.query_commands[-10:]
                self.logger.info("🧹 Cleaned up query command history")
                
        except Exception as e:
            self.logger.warning(f"⚠️ Error during cleanup: {e}")
        
    def _reload_current_proof_state(self):
        """Reload the current proof state after server restart."""
        try:
            # Store current file path if not already stored
            file_path = self.coq.proof_file.path
            self.logger.info(f"🔄 Reloading proof file: {file_path}")
            
            success = self.coq.load()
            if success:
                self.logger.info("✅ Proof file reloaded successfully")
                
                return True
            else:
                self.logger.error("❌ Failed to reload proof file")
                return False
        
        except Exception as e:
            self.logger.error(f"❌ Error during proof state reload: {e}")
            return False

    #####################
    ##  Proof methods  ##
    #####################

    def _init_proof_session(self, theorem_name: str = None) -> bool:
        """
        Initialize all state for a new proof attempt.
        Called by both prove_theorem() and InteractiveSessionManager.
        Returns False if initialization fails (e.g., no unproven proof found).
        """
        self.current_theorem_name = theorem_name or 'unnamed'
        self.logger.info(f"🚀 Starting proof for: {self.current_theorem_name}")
        self.logger.info(f"⚙️  Max steps: {self.max_steps}")

        # Start recording
        if self.enable_recording and self.recorder:
            try:
                proof_file = self.coq.proof_file
                if proof_file is None:
                    raise ValueError("No proof file available")
                self.recorder.start_proof_recording(
                    proof_file=proof_file,
                    theorem_name=self.current_theorem_name,
                    metadata={'max_steps': self.max_steps, 'controller_version': '1.0'}
                )
            except Exception as e:
                self.logger.error(f"❌ Failed to start proof recording: {e}")

        # Reset counters
        self.is_successful = False
        self.give_up = False
        self.global_step_id = 0
        self.gen_step_count = 0
        self.successful_tactics = []
        self.failed_tactics = []
        self.query_commands = []
        self._pending_hints = []
        self._tactics_with_states = []

        # Check for unproven proof
        unproven_proof = self.coq.get_unproven_proof()
        if not unproven_proof:
            self.logger.error("❌ No unproven proof available")
            return False

        self._init_proof_tree()
        self.logger.info("🌳 Initialized new ProofTree")

        if self.enable_recording and self.recorder:
            self.recorder.start_proving_time()

        return True

    def _finish_proof(self, tactics_with_states: List[Dict[str, Any]]):
        """
        Finalize a proof attempt: record history, save tree, end recording.
        Called by prove_theorem() and InteractiveSessionManager.
        """
        proof_file_dir = str(Path(self.coq.file_path).parent)
        prefix = self.current_theorem_name + "_"

        completion_message = (
            "Proof completed" if self.is_successful
            else "Max steps reached" if self.gen_step_count >= self.max_steps
            else "Proof aborted" if self.give_up
            else "Unable to proceed"
        )

        if self.is_successful:
            self.logger.info(f"🔍 Recording successful proof with {len(tactics_with_states)} tactics")
            self._record_successful_proof(tactics_with_states)

        self.proof_tree.save_to_png(str(Path(proof_file_dir) / "proof_tree_final"), prefix=prefix)
        self.proof_tree.save_to_json(str(Path(proof_file_dir) / "proof_tree_final.json"), prefix=prefix)

        if self.enable_recording and self.recorder:
            try:
                self.recorder.end_proof_recording(
                    success=self.is_successful,
                    message=completion_message,
                    final_stats={
                        'successful_tactics': len(self.successful_tactics),
                        'failed_tactics': len(self.failed_tactics),
                        'query_commands': len(self.query_commands),
                        'steps_taken': self.global_step_id,
                        'steps_to_completion': self.gen_step_count if self.is_successful else None,
                        'successful_tactics_list': self.successful_tactics,
                        'query_commands_list': self.query_commands,
                    }
                )
            except Exception as e:
                self.logger.error(f"❌ Failed to end proof recording: {e}")


    def prove_theorem(self, theorem_name: str = None) -> bool:
        """Main entry point for autonomous proof generation."""
        if not self._init_proof_session(theorem_name):
            return False

        tactics_with_states = self.main_loop()

        self._finish_proof(tactics_with_states)
        return self.is_successful


    def main_loop(self) -> List[Dict[str, Any]]:
        """
        Main agent loop for autonomous (non-interactive) mode.
        Drives step_generator() to completion and returns the accumulated tactics.
        """
        for _ in self.step_generator():
            pass
        return self._tactics_with_states


    def step_generator(self):
        """
        Generator version of the agent loop. Yields a result dict after each
        tactic attempt or rollback. Plans and queries are executed transparently.

        Yield format:
          {'type': 'tactic', 'tactic': str, 'success': bool, 'error': str|None,
           'goals_after': str, 'proof_complete': bool}
          {'type': 'rollback', 'success': bool, 'distance': int}
          {'type': 'done', 'success': bool}

        Requires _init_proof_session() to have been called first.
        self._tactics_with_states is updated in-place so callers always see current state.
        """
        # self._tactics_with_states holds all applied tactics (user + agent, in order).
        # source field on each entry distinguishes them. Using an instance variable
        # means external user rollback is visible when the generator resumes.

        consecutive_queries = 0
        consecutive_errors = 0
        error_tactics = []

        def _clear_error_tracking():
            nonlocal consecutive_queries, consecutive_errors, error_tactics
            consecutive_queries = 0
            consecutive_errors = 0
            error_tactics.clear()

        tool_call_id = None
        last_tool_success = False
        role = "user"
        proof_tree_str = self.proof_tree.get_proof_tree_string()
        prompt = self.context_manager.build_initial_prompt(proof_tree_str)

        while self.gen_step_count < self.max_steps:
            if self.global_step_id > self.max_steps * (self.max_context_search + 1):
                self.gen_step_count = self.max_steps  # so that proof completion message is "Max steps reached"
                self.logger.info(f"\n{'='*60}\n📊 [PROOF STEP {self.global_step_id}] {self.gen_step_count}/{self.max_steps}. Exiting...")
                break

            # Inject pending user hints
            if self._pending_hints:
                hints_text = "\n".join(f"- {h}" for h in self._pending_hints)
                prompt += f"\n\n## USER GUIDANCE:\n{hints_text}\n"
                self._pending_hints.clear()

            self.steps_since_restart += 1
            self.global_step_id += 1
            self.logger.info(f"\n{'='*60}\n📊 [PROOF STEP {self.global_step_id}] {self.gen_step_count}/{self.max_steps}\n{'='*60}")

            proof_state = self._build_proof_state()

            current_step_count = len(self._tactics_with_states)
            current_step_count_coq = len(self.coq.proof.steps) if self.coq.proof.steps else 0
            expected_coq_steps = current_step_count + 1  # +1 for Proof.
            self.logger.debug(f"Step count: total={current_step_count}, coq_file={current_step_count_coq}")
            if expected_coq_steps != current_step_count_coq:
                self.logger.error(f"Error: Step count mismatch! expected={expected_coq_steps} != coq={current_step_count_coq}. Exiting early...")
                exit(1)

            decision, tool_call_id = self.context_manager.get_action(prompt, role=role, tool_call_id=tool_call_id, tool_success=last_tool_success)

            if decision is None:
                self.logger.error(f"❌ Step {self.global_step_id}: Failed to parse LLM decision. Skipping step.")
                prompt = "Failed to parse your response. Please ensure you're calling one of the available functions."
                tool_call_id = None
                role = "user"
                consecutive_errors += 1
                if consecutive_errors > self.max_errors:
                    self.logger.error(f"❌ Step {self.global_step_id}: LLM call failed. Exiting...")
                    self.logger.debug(f"Last few messages: {self.context_manager.chat_session.messages[-5:]}")
                    break
                continue

            decision_type = decision.get('type')
            decision_content = decision.get('content')
            role = "tool"
            last_tool_success = False

            if decision_type == 'plan':
                last_tool_success = True
                prompt = self.context_manager.handle_plan_call(decision_content, tool_call_id)
                print(visualizer.render_action('plan', decision_content))
                if self.context_manager.should_give_up():
                    self.logger.warning(f"⚠️  Step {self.global_step_id}: PROOF UNPROVABLE -- giving up!")
                    self.give_up = True
                    break
                self.logger.info(f"✅ Step {self.global_step_id}: PLAN FUNCTION CALLED!")
                continue  # plan is transparent

            elif decision_type == 'query':
                consecutive_queries += 1
                if consecutive_queries > self.max_context_search:
                    prompt = "You have hit the maximum number of 'query' calls. Please proceed with the current information until a successful 'tactic', or 'rollback' is applied."
                    self.logger.info(f"⚠️  Step {self.global_step_id}: QUERY MAX REACHED ({self.max_context_search})")
                    continue
                if consecutive_queries > 1 and decision_content == self.query_commands[-1]:
                    prompt = "You have just queried this information. Please provide a different query."
                    self.logger.info(f"⚠️  Step {self.global_step_id}: REPEATED QUERY -- skipped!")
                    continue
                self.query_commands.append(decision_content)
                prompt = self.context_manager.handle_query_call(decision_content, tool_call_id)
                print(visualizer.render_action('query', decision_content))
                if consecutive_queries == self.max_context_search:
                    prompt += "\n\nYou have hit the maximum number of 'query' calls. Please proceed with the current information until a successful 'tactic', or 'rollback' is applied."
                self.logger.info(f"✅ Step {self.global_step_id}: QUERY success: {decision_content}")
                continue  # query is transparent

            elif decision_type == 'rollback':
                rollback_data = decision_content
                rollback_reason = rollback_data.get('reason', 'No reason provided')
                rollback_steps = rollback_data.get('steps', 1)
                self.gen_step_count += 1
                self.logger.info(f"🔄 Step {self.global_step_id}: ROLLBACK {rollback_steps} step{'s' if rollback_steps != 1 else ''}: {rollback_reason}")

                agent_only = [t for t in self._tactics_with_states if t.get('source') != 'user']
                rollback_result = self._execute_rollback(
                    agent_only, rollback_reason, proof_tree_str, rb_steps=rollback_steps
                )

                if rollback_result['success']:
                    target_index = rollback_result['target_index']
                    target_step_number = rollback_result['target_step_number']
                    rollback_distance = rollback_result['rollback_distance']
                    # Keep tactics at or before the target step number
                    if target_index > 0:
                        self._tactics_with_states[:] = [t for t in self._tactics_with_states
                                                        if t['step_number'] <= target_step_number]
                    else:
                        self._tactics_with_states[:] = []
                    last_tool_success = True
                    _clear_error_tracking()
                    proof_tree_str = self.proof_tree.get_proof_tree_string()
                    self.logger.info(f"✅ Rollback successful: {rollback_distance} step{'s' if rollback_distance != 1 else ''} back to index {target_index} (step_number {target_step_number})")
                    print(visualizer.render_action('rollback', rollback_data))
                    prompt = (
                        f"Rollback completed successfully. Returned {rollback_distance} step{'s' if rollback_distance != 1 else ''} back to step {target_step_number}.\n\n"
                        f"## CURRENT PROOF TREE:\n{proof_tree_str}\n\n"
                        "Now consider a different approach to complete the proof. Update the plan if needed. Avoid repeating the same tactics that led to this rollback."
                    )
                    yield {'type': 'rollback', 'success': True, 'distance': rollback_distance}
                else:
                    prompt = f"Rollback failed: {rollback_result.get('message', 'Unknown error')}\nPlease continue with tactics."
                    self.logger.error(f"❌ Rollback failed: {rollback_result.get('message')}")
                    yield {'type': 'rollback', 'success': False, 'distance': 0}
                continue

            elif decision_type == 'tactic':
                self.gen_step_count += 1
                tactic_content = self.context_manager.get_tactic(decision_content, tool_call_id)

                if tactic_content.startswith(("Search", "Print", "Check", "About")):
                    prompt = f"You have supplied a 'query' as a 'tactic'. Please call the 'query' tool instead.\n"
                    prompt += self.context_manager.handle_query_call(decision_content, tool_call_id)
                    self.logger.info(f"⚠️  Step {self.global_step_id}: QUERY AS TACTIC!")
                    self.query_commands.append(decision_content)
                    self.gen_step_count -= 1
                    consecutive_queries += 1
                    consecutive_errors += 1
                    continue

                # Early abort: give up
                if tactic_content in ["Abort.", "abort.", ]:
                    self.logger.warning(f"⚠️  Step {self.global_step_id}: ABORTING PROOF -- giving up!")
                    self.give_up = True
                    break

                if tactic_content in ["Admitted.", "admit."]:
                    prompt = "Tactic not allowed. Suggest a *different* tactic.\n"
                    prompt += "If some errors persist, you may consider (1) reviewing your plan, (2) searching/querying for relevant terms, or (3) rolling back to an earlier state."
                    self.logger.info(f"⚠️  Step {self.global_step_id}: ADMITTED TACTIC -- skipped!")
                    consecutive_errors += 1
                    yield {'type': 'tactic', 'tactic': tactic_content, 'success': False,
                           'error': 'Admitted not allowed', 'goals_after': '', 'proof_complete': False}
                    continue

                if tactic_content in error_tactics:
                    prompt = "This tactic has been tried and failed. Suggest a *different* tactic.\n"
                    prompt += "If some errors persist, you may consider (1) reviewing your plan, (2) searching/querying for relevant terms, or (3) rolling back to an earlier state."
                    self.logger.info(f"⚠️  Step {self.global_step_id}: REPEATING FAILED TACTIC -- skipped!")
                    consecutive_errors += 1
                    yield {'type': 'tactic', 'tactic': tactic_content, 'success': False,
                           'error': 'Repeated failed tactic', 'goals_after': '', 'proof_complete': False}
                    continue

                subgoals_before = self.coq.get_subgoals()
                goals_before = proof_state.get('goals', '').strip()
                hypotheses_before = proof_state.get('hypotheses', '').strip()

                prompt = ""
                success = self._apply_tactic(tactic_content)

                print(visualizer.render_action('tactic', tactic_content, success))

                if not success:
                    consecutive_errors += 1
                    error_tactics.append(tactic_content)
                    self.failed_tactics.append(tactic_content)
                    failed_error = self.coq.get_last_error()
                    self.logger.info(f"⚠️  Step {self.global_step_id}: TACTIC APPLICATION failed")

                    if consecutive_errors == self.max_errors + 1 and self.enable_hammer:
                        success = self._try_hammer()

                    if not success:
                        prompt += f"Tactic application failed with error: {failed_error}\n"
                        prompt += hints_from_error(tactic_content, failed_error)
                        if consecutive_errors > self.max_errors:
                            prompt += "\nIf errors persist, you may consider using other available tools."
                        prompt += self._provide_history_feedback(consecutive_errors)
                        yield {'type': 'tactic', 'tactic': tactic_content, 'success': False,
                               'error': failed_error, 'goals_after': goals_before, 'proof_complete': False}
                        continue
                    else:
                        prompt += "Application failed with supplied tactic, but hammer succeeded.\n"

                # Tactic succeeded
                last_tool_success = True
                _clear_error_tracking()
                self.logger.info(f"🏆 Tactic applied: '{tactic_content}'")

                current_goals_after = self.coq.get_goal_str()
                current_hypotheses_after = self.coq.get_hypothesis()
                subgoals_after = self.coq.get_subgoals()

                tactic_with_state = self._handle_successful_tactic(
                    tactic_content, subgoals_before, subgoals_after,
                    goals_before, current_goals_after, hypotheses_before, current_hypotheses_after
                )
                tactic_with_state['source'] = 'agent'
                self._tactics_with_states.append(tactic_with_state)

                post_tactic_status = self.coq.get_proof_completion_status()
                proof_complete = post_tactic_status['is_complete'] and post_tactic_status['qed_already_applied']

                self.logger.info(f"✅ Step {self.global_step_id}: TACTIC APPLIED SUCCESSFULLY!")

                if proof_complete:
                    self.is_successful = True
                    yield {'type': 'tactic', 'tactic': tactic_content, 'success': True,
                           'error': None, 'goals_after': '', 'proof_complete': True}
                    break
                else:
                    proof_tree_str = self.proof_tree.get_proof_tree_string()
                    goals_after_str = str(current_goals_after).strip() if current_goals_after else ''
                    goals_before_str = goals_before

                    prompt += f"Tactic '{tactic_content}' applied successfully.\n\n"
                    if goals_after_str != goals_before_str:
                        prompt += f"## CURRENT PROOF TREE:\n{proof_tree_str}\n"
                    else:
                        prompt += "Goals: No changes.\n"
                    prompt += f"Hypotheses: {current_hypotheses_after if current_hypotheses_after else 'None'}\n"

                    yield {'type': 'tactic', 'tactic': tactic_content, 'success': True,
                           'error': None, 'goals_after': goals_after_str, 'proof_complete': False}

            else:
                prompt = f"Invalid function call: {decision_type}"
                self.logger.error(f"❌ Step {self.global_step_id}: INVALID FUNCTION CALL!")
                continue

        yield {'type': 'done', 'success': self.is_successful}

    ############################
    ##  Proof tree / state   ##
    ############################

    def _init_proof_tree(self):
        """Initialize a fresh proof tree with a root node from current Coq state."""
        self.proof_tree = ProofTree()
        initial_goals = self.coq.get_goal_str()
        self.logger.info(f"🎯 Initial goals: {initial_goals}")
        initial_hypotheses = self.coq.get_hypothesis()
        self.proof_tree.add_node(
            tactic="Proof.",
            goals_before=initial_goals.strip() if initial_goals else '',
            goals_after=initial_goals.strip() if initial_goals else '',
            hypotheses_before=initial_hypotheses.strip() if initial_hypotheses else '',
            hypotheses_after=initial_hypotheses.strip() if initial_hypotheses else '',
            step_number=0,
            subgoals_after=self.coq.get_subgoals()
        )

    #####################
    ##  Proof helpers  ##
    #####################

    def _record_successful_proof(self, tactics_with_states: List[Dict[str, Any]]):
        """
        Record a successful tactic application sequence in history.
        This function should only be called if the sequence is a complete proof.
        """
        # Record each tactic in the sequence
        for state in tactics_with_states:
            self.context_manager.tactic_history.add_successful_tactic(
                tactic=state['tactic'],
                goals_before=state['goals_before'],
                goals_after=state['goals_after'],
                hypotheses_before=state['hypotheses_before'],
                hypotheses_after=state['hypotheses_after'],
                theorem_name=self.current_theorem_name,
                step_number=state['step_number']
            )

    def _handle_successful_tactic(self, successful_tactic, subgoals_before, subgoals_after, goals_before, goals_after, hypotheses_before, hypotheses_after) -> Dict[str, Any]:
        """
        Handle successful tactic by updating proof tree. 
        Returns all the information about the tactic application as a dictionary.
        """
        try:
            self.successful_tactics.append(successful_tactic)
            # Update proof tree
            tactic_with_state = self._update_proof_tree(subgoals_before, subgoals_after, successful_tactic, goals_before, goals_after, hypotheses_before, hypotheses_after)
            # Update in recorder
            if self.enable_recording and self.recorder:
                self.recorder.update_proof_statistics(
                    successful_tactics=len(self.successful_tactics),
                    failed_tactics=len(self.failed_tactics),
                    query_commands=len(self.query_commands),
                    total_steps=self.global_step_id
                )
            
            return tactic_with_state
            
        except Exception as e:
            self.logger.error(f"❌ Error handling successful tactic: {e}")
            return False

    def _update_proof_tree(self, subgoals_before, subgoals_after, successful_tactic, goals_before, goals_after, hypotheses_before, hypotheses_after) -> Dict[str, Any]:
        """
        Maintain proof tree by adding nodes for branching / linear tactics.
        Returns the tactic_with_state dictionary.
        """
        try:
            # Helper function to convert Goal object to string
            def goal_to_str(goal) -> str:
                """Convert Goal object to string for comparison."""
                if hasattr(goal, 'ty'):
                    return str(goal.ty).strip()
                elif isinstance(goal, str):
                    return goal.strip()
                else:
                    return str(goal).strip()
                     
            creates_branching = len(subgoals_after) > len(subgoals_before)

            if creates_branching:
                if self.proof_tree.open_subgoals:
                    self.logger.debug(f"🌳 Branching tactic detected: {len(subgoals_before)} -> {len(subgoals_after)} subgoals")
                    # Add branching node with intermediate subgoal nodes
                    node = self.proof_tree.add_branching_node(
                        tactic=successful_tactic,
                        goals_before=goals_before,
                        goals_after=goals_after.strip() if goals_after else '',
                        hypotheses_before=hypotheses_before,
                        hypotheses_after=hypotheses_after.strip() if hypotheses_after else '',
                        step_number=self.global_step_id,
                        subgoals=subgoals_after
                    )
                    self.logger.debug(f"🌳 Added branching node: {len(subgoals_after)} subgoals created")
                else:
                    self.logger.warning(f"⚠️  No open subgoals to attach branching tactic [{successful_tactic}] to. Skipping node addition.")

            else:
                # Regular linear step - attach to correct subgoal
                if self.proof_tree.open_subgoals:
                    self.logger.debug(f"🌳 Linear tactic: attaching to correct subgoal")
                    # Use the smart attachment method
                    node = self.proof_tree.attach_to_correct_subgoal(
                        tactic=successful_tactic,
                        goals_before=goals_before,
                        goals_after=goals_after.strip() if goals_after else '',
                        hypotheses_before=hypotheses_before,
                        hypotheses_after=hypotheses_after.strip() if hypotheses_after else '',
                        step_number=self.global_step_id,
                        subgoals_before=subgoals_before,
                        subgoals_after=subgoals_after
                    )                                 
                else:
                    # No open subgoals - add as regular node
                    self.logger.debug(f"🌳 Linear tactic: no open subgoals, adding regular node")
                    if self.proof_tree.open_subgoals:
                        node = self.proof_tree.add_node(
                            tactic=successful_tactic,
                            goals_before=goals_before,
                            goals_after=goals_after.strip() if goals_after else '',
                            hypotheses_before=hypotheses_before,
                            hypotheses_after=hypotheses_after.strip() if hypotheses_after else '',
                            step_number=self.global_step_id,
                            subgoals_after=subgoals_after
                        )
                    else:
                        self.logger.warning(f"⚠️  No open subgoals to attach tactic [{successful_tactic}] to. Skipping node addition.") 
        
        except Exception as tree_error:
            import traceback
            self.logger.error(f"❌ Error updating proof tree: {tree_error}")
            self.logger.error(f"📋 Tree update traceback: {traceback.format_exc()}")
        
        # --- End proof tree update ---
        return {
            'tactic': successful_tactic,
            'goals_before': goals_before.strip() if goals_before else '',
            'goals_after': goals_after.strip() if goals_after else '',
            'hypotheses_before': hypotheses_before.strip() if hypotheses_before else '',
            'hypotheses_after': hypotheses_after.strip() if hypotheses_after else '',
            'step_number': self.global_step_id
        }

    def _build_proof_state(self) -> Dict[str, Any]:
        """Build current proof state for tactic generation."""
        return {
            "goals": self.coq.get_goal_str(),
            "hypotheses": self.coq.get_hypothesis(),
            "step_number": self.global_step_id,
            "successful_tactics": self.successful_tactics[-5:],  # Last 5 successful tactics
            "failed_tactics": self.failed_tactics[-3:],  # Last 3 failed tactics
        }

    def _apply_tactic(self, tactic: str) -> bool:
        """Apply a single tactic to the current proof state."""
        return self.coq.apply_tactic(tactic)
   
    def _execute_rollback(self, successful_tactics_with_states: List[Dict], reason: str, proof_tree_str: str, rb_steps: int) -> Dict[str, Any]:
        """
        Execute rollback using the number of steps to rollback.
        
        Args:
            successful_tactics_with_states: List of successful tactic records
            reason: Reason for rollback (from LLM)
            proof_tree_str: Current proof tree string
            rb_steps: Number of steps to rollback
            
        Returns:
            Dict with rollback result including success status and target step
        """
        try:
            if not successful_tactics_with_states:
                return {
                    'success': False,
                    'message': 'Cannot rollback - no successful tactics to rollback to'
                }
            
            self.logger.info(f"📊 Current state: {len(successful_tactics_with_states)} successful tactics")
            
            # Determine rollback target
            current_step_count = len(successful_tactics_with_states)
                        
            # Validate rollback steps
            if rb_steps <= 0:
                return {
                    'success': False,
                    'message': f'Invalid rollback steps: {rb_steps} (must be positive)'
                }
            
            # Calculate target index in successful_tactics_with_states
            target_index = max(0, current_step_count - rb_steps)
            rollback_distance = current_step_count - target_index
                        
            # Get the actual step_number from the proof tree at this index
            # This is critical because successful_tactics_with_states may have gaps
            # (failed tactics are not included, so indices != step_numbers)
            if target_index > 0 and target_index <= len(successful_tactics_with_states):
                target_step_number = successful_tactics_with_states[target_index - 1]['step_number']

                self.logger.info(f"🎯 Target: index {target_index} → step_number {target_step_number}")
            else:
                target_step_number = 1  # Rollback to very beginning
                target_index = 0
                self.logger.info(f"🎯 Target: beginning (step_number 1)")
            
            # Log warnings for edge cases
            if rb_steps > current_step_count:
                self.logger.warning(f"⚠️ Requested {rb_steps} steps but only {current_step_count} available. Rolling back to step 1.")
                target_index = 0
                target_step_number = 1
                rollback_distance = current_step_count
            
            # For debugging
            if target_index > 0:
                kept_steps = [t['step_number'] for t in successful_tactics_with_states[:target_index]]
                removed_steps = [t['step_number'] for t in successful_tactics_with_states[target_index:]]
                self.logger.debug(f"📋 Keeping step_numbers: {kept_steps}")
                self.logger.debug(f"📋 Removing step_numbers: {removed_steps}")
            
            reasoning = f'Rollback by {rb_steps} step{"s" if rb_steps != 1 else ""}'
            
            # Step 2: Update proof tree - delete subtree beyond target step_number
            if self.proof_tree:
                self.logger.debug(f"🌳 Proof tree BEFORE rollback:")
                proof_tree_str_before = self.proof_tree.get_proof_tree_string()
                self.logger.debug(f"\n{proof_tree_str_before[:200]}...\n")
                
                tree_result = self.proof_tree.delete_subtree_by_step_number(target_step_number)
                if tree_result:
                    self.logger.debug(f"🌳 Proof tree updated: kept step_number {target_step_number}, removed descendants")
                else:
                    self.logger.warning(f"⚠️ Failed to update proof tree for step_number {target_step_number}")
                
                self.logger.debug(f"🌳 Proof tree AFTER rollback:")
                proof_tree_str_after = self.proof_tree.get_proof_tree_string()
                self.logger.debug(f"\n{proof_tree_str_after[:200]}...\n")
            
            # Step 4: Rollback Coq proof state by popping steps
            if rollback_distance > 0:
                self.logger.info(f"🔙 Popping {rollback_distance} proof steps from Coq")
                
                # Get the current unproven proof from CoqInterface
                proof = self.coq.get_unproven_proof()
                if proof:
                    try:
                        for i in range(rollback_distance):
                            steps_before = len(proof.steps)
                            self.logger.debug(f"Step to pop: {proof.steps[-1].step}")
                            self.coq.proof_file.pop_step(proof)
                            steps_after = len(proof.steps)
                            if steps_before != steps_after + 1:
                                raise Exception(f"Error: Step count mismatch after pop_step(). Steps before: {steps_before}, Steps after: {steps_after}")
                    except Exception as pop_error:
                        self.logger.error(f"{pop_error}. Exiting early...")
                        exit(1) # Fail fast
                
                # Step 4b: Refresh CoqInterface's cached proof object
                # Get a fresh proof object that reflects the current file state
                self.coq.proof = self.coq.get_unproven_proof()
                if self.coq.proof:
                    self.logger.debug(f"🔄 Refreshed proof object: now has {len(self.coq.proof.steps)} steps")
                else:
                    self.logger.warning(f"⚠️ No proof object after rollback refresh")
            
            # Step 5: Record rollback in recorder if enabled
            if self.enable_recording and self.recorder:
                try:
                    self.recorder.record_rollback(
                        at_step=self.global_step_id,
                        rollback_steps=rollback_distance,
                        target_step=target_step_number,
                        reason=reason
                    )

                except Exception as record_error:
                    self.logger.warning(f"⚠️ Failed to record rollback: {record_error}")
            
            return {
                'success': True,
                'target_index': target_index,  # Index in successful_tactics list for slicing
                'target_step_number': target_step_number,  # Actual step number in proof tree
                'rollback_distance': rollback_distance,
                'message': f'Rolled back {rollback_distance} steps to step_number {target_step_number}',
                'source': 'llm',
                'reasoning': reasoning
            }
            
        except Exception as e:
            import traceback
            self.logger.error(f"💀 Exception during rollback execution: {e}")
            self.logger.error(f"📋 Rollback traceback: {traceback.format_exc()}")
            return {
                'success': False,
                'message': f'Rollback execution failed: {str(e)}'
            }


    def _provide_history_feedback(self, consecutive_errors: int) -> str:
        # Add suggestions from history ONCE per proof state
        if not self.context_manager.enable_history_context:
            return ""
        if consecutive_errors != self.max_errors + 1:
            return ""
        if not self.coq.get_goal_str():
            return ""
        
        clean_goal_str = clean_ansi_codes(self.coq.get_goal_str())
        feedback = ""

        # Suggest similar tactics
        similar_proof_states = self.context_manager.get_similar_history(clean_goal_str, n=5)
        if similar_proof_states:
            feedback += "\nHere are some tactics found in history, formatted as '<id>. <tactic> \\n <proof goal diff>':\n\n"
            for i, entry in enumerate(similar_proof_states, 1):
                tactic = clean_ansi_codes(str(entry.get('tactic', 'Unknown'))).strip()
                if tactic in ('', '{', '}', 'Unknown'):
                    continue
                goals_before = clean_ansi_codes(str(entry.get('goals_before', '')))
                diff_str = goal_diff(clean_goal_str, goals_before)
                feedback += f"   {i}. {tactic}\n{diff_str[:100]}{'...' if len(diff_str) > 100 else ''}\n"

        return feedback


    def _try_hammer(self) -> bool:
        """
        Try to apply hammer to the current proof state.
        """
        success = self._apply_tactic("hammer.")
        if success:
            self.logger.info(f"🔧 Hammer applied successfully")
            return True
        else:
            hammer_error = self.coq.get_last_error()
            if "ATPs failed to find a proof" in hammer_error:
                self.logger.info(f"🔧 Hammer is not able to find a proof. Continuing...")
            else:
                self.logger.warning(f"🔧 Hammer failed with unknown error: {hammer_error}")
            return False
        
