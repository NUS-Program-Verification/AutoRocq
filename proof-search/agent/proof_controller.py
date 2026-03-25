import os

from pathlib import Path
from typing import Dict, Optional, Any, List
from backend.coq_interface import CoqInterface
from agent.context_manager import ContextManager
from agent.proof_tree import ProofTree
from utils.recorder import create_proof_recorder
from utils.logger import clean_ansi_codes, setup_logger
from utils.coq_utils import hints_from_error, goal_diff

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
        recording_output_dir: str = "data/statistics"
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

        self.max_steps = max_steps
        self.max_errors = max_errors
        
        # Initialize counters and history
        self.global_step_id = 0         # Global ID for tool call / proof step
        self.gen_step_count = 0         # Global step count for tactic / HL / rollback
        self.successful_tactics = []    # Global successful tactics
        self.failed_tactics = []        # Global failed tactics
        self.query_commands = []        # Global query commands
        
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
            self.logger.error(f"❌ Failed to initialize TacticHistoryManager: {e}")
            import traceback
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
                self.logger.warning("⚠️ Failed to restart Coq server")
    
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

    def prove_theorem(self, theorem_name: str = None) -> bool:
        
        """Main entry point for proof generation."""
        
        ####################
        ## Initialization ##
        ####################
        self.current_theorem_name = theorem_name or 'unnamed'
        self.logger.info(f"🚀 Starting proof for: {self.current_theorem_name}")
        self.logger.info(f"⚙️  Max steps: {self.max_steps}")

        proof_file_dir = str(Path(self.coq.file_path).parent)
        prefix = self.current_theorem_name + "_"

        # Start recording
        if self.enable_recording and self.recorder:
            try:
                proof_file = self.coq.proof_file
                if proof_file is None:
                    self.logger.error("proof_file is None")
                    raise ValueError("No proof file available")
                self.recorder.start_proof_recording(
                    proof_file=proof_file,
                    theorem_name=self.current_theorem_name,
                    metadata={
                        'max_steps': self.max_steps,
                        'controller_version': '1.0'
                    }
                )
            except Exception as e:
                self.logger.error(f"❌ Failed to start proof recording: {e}")

        # Reset counters and tracking lists
        self.is_successful = False
        self.global_step_id = 0
        self.gen_step_count = 0
        self.successful_tactics = []
        self.failed_tactics = []
        self.query_commands = []

        # Check if we have an unproven proof
        unproven_proof = self.coq.get_unproven_proof()
        if not unproven_proof:
            self.logger.error("❌ No unproven proof available")
            return False
        
        # Initialize proof tree
        self.proof_tree = ProofTree()
        self.logger.info("🌳 Initialized new ProofTree")

        # Show initial goals
        initial_goals = self.coq.get_goal_str()
        self.logger.info(f"🎯 Initial goals: {initial_goals}")
        
        # Add initial root node to the proof tree
        if not self.proof_tree.root:
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

        if self.enable_recording and self.recorder:
            self.recorder.start_proving_time()
        
        #####################
        ## Main agent loop ##
        #####################
        tactics_with_states = self.main_loop()
        
        #####################
        ##  Final results  ##
        #####################
        completion_message = "Proof completed" if self.is_successful \
                        else "Max steps reached" if self.gen_step_count >= self.max_steps \
                        else "Proof aborted" if self.give_up \
                        else "Unable to proceed"

        # Update history with successful proof
        if self.is_successful:
            self.logger.info(f"🔍 Recording successful proof with {len(tactics_with_states)} tactics")
            self._record_successful_proof(tactics_with_states)
        
        self.proof_tree.save_to_png(str(Path(proof_file_dir) / "proof_tree_final"), prefix=prefix)
        self.proof_tree.save_to_json(str(Path(proof_file_dir) / "proof_tree_final.json"), prefix=prefix)

        if self.enable_recording and self.recorder:
            try:
                final_stats = {
                    'successful_tactics': len(self.successful_tactics),
                    'failed_tactics': len(self.failed_tactics),
                    'query_commands': len(self.query_commands),
                    'steps_taken': self.global_step_id,
                    'steps_to_completion': self.gen_step_count if self.is_successful else None,
                    'successful_tactics_list': self.successful_tactics,  # List of tactics
                    'query_commands_list': self.query_commands,          # List of queries
                }
                self.recorder.end_proof_recording(
                    success=self.is_successful,
                    message=completion_message,
                    final_stats=final_stats
                )
            except Exception as e:
                self.logger.error(f"❌ Failed to end proof recording: {e}")
        
        return self.is_successful


    def main_loop(self) -> List[Dict[str, Any]]:
        """
        Main agent loop. Continuously handles LLM tools with feedback.
        Returns a list of successful tactics with states.
        """
        
        # Currently applied tactics: to be returned by the function
        # Tactics are appended on successes and erased on rollback
        successful_tactics_with_states = []
        
        # Error tracking variables:
        # reset on successful tactic / rollback
        consecutive_queries = 0
        consecutive_errors = 0
        error_tactics = []
        
        def _clear_error_tracking():
            nonlocal consecutive_queries, consecutive_errors, error_tactics
            consecutive_queries = 0
            consecutive_errors = 0
            error_tactics.clear()
        
        # Main variables for LLM prompt construction
        tool_call_id = None
        last_tool_success = False # last action was successful
        role = "user" # initial USER prompt -> TOOL responses
        proof_tree_str = self.proof_tree.get_proof_tree_string()
        prompt = self.context_manager.build_initial_prompt(proof_tree_str)
        
        while self.gen_step_count < self.max_steps:

            # cleanup disabled for short proofs
            # TODO: better context and state management
            # self._check_for_cleanup()
            
            # Early exit if global_step_id becomes too large
            if self.global_step_id > self.max_steps * (self.max_context_search + 1):
                self.gen_step_count = self.max_steps # so that proof completion message is "Max steps reached"
                self.logger.info(f"\n{'='*60}\n📊 [PROOF STEP {self.global_step_id}] {self.gen_step_count}/{self.max_steps}. Exiting...")
                break
            
            self.steps_since_restart += 1
            self.global_step_id += 1
            self.logger.info(f"\n{'='*60}\n📊 [PROOF STEP {self.global_step_id}] {self.gen_step_count}/{self.max_steps}\n{'='*60}")

            proof_state = self._build_proof_state()
            current_goals = proof_state.get('goals', '')
            
            # Sanity check: coq file is consistent with the proof state
            current_step_count = len(successful_tactics_with_states)
            current_step_count_coq = len(self.coq.proof.steps) if self.coq.proof.steps else 0
            self.logger.debug(f"Step count: state={current_step_count}, coq_file={current_step_count_coq}")
            if current_step_count + 1 != current_step_count_coq: # +1 because of 'Proof.'
                self.logger.error(f"Error: Step count mismatch! Exiting early...")
                exit(1) # Fail fast
            
            decision, tool_call_id = self.context_manager.get_action(prompt, role=role, tool_call_id=tool_call_id, tool_success=last_tool_success)
            
            # Handle case where decision parsing failed
            if decision is None:
                self.logger.error(f"❌ Step {self.global_step_id}: Failed to parse LLM decision. Skipping step.")
                prompt = "Failed to parse your response. Please ensure you're calling one of the available functions (plan, query, tactic, or rollback) with valid JSON arguments."
                tool_call_id = None
                role = "user" # fallback to user prompt and retry
                consecutive_errors += 1
                if consecutive_errors > self.max_errors:
                    self.logger.error(f"❌ Step {self.global_step_id}: LLM call failed. Exiting...")
                    self.logger.debug(f"Last few messages: {self.context_manager.chat_session.messages[-5:]}")
                    return []
                else:
                    continue
            
            decision_type = decision.get('type')
            decision_content = decision.get('content')
            
            role = "tool"
            last_tool_success = False # reset for the next tool call
            
            if decision_type == 'plan':
                last_tool_success = True
                prompt = self.context_manager.handle_plan_call(decision_content, tool_call_id)
                if self.context_manager.should_give_up():
                    self.logger.info(f"⚠️  Step {self.global_step_id}: PROOF UNPROVABLE -- giving up!")
                    self.give_up = True
                    return []
                self.logger.info(f"✅ Step {self.global_step_id}: PLAN FUNCTION CALLED!")
            
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
                
                # 'query' is NEVER cached, so never considered successful
                
                self.query_commands.append(decision_content)
                prompt = self.context_manager.handle_query_call(decision_content, tool_call_id)
                
                if consecutive_queries == self.max_context_search:
                    prompt += "\n\n"
                    prompt += "You have hit the maximum number of 'query' calls. Please proceed with the current information until a successful 'tactic', or 'rollback' is applied."

                
                self.logger.info(f"✅ Step {self.global_step_id}: QUERY success: {decision_content}")
                continue
            
            elif decision_type == 'rollback':
                rollback_data = decision_content
                rollback_reason = rollback_data.get('reason', 'No reason provided')
                rollback_steps = rollback_data.get('steps', 1)  # Default to 1 step
                
                self.gen_step_count += 1 # Update generation step count
                
                self.logger.info(f"🔄 Step {self.global_step_id}: ROLLBACK {rollback_steps} step{'s' if rollback_steps != 1 else ''}: {rollback_reason}")
                
                # Execute rollback
                rollback_result = self._execute_rollback(
                    successful_tactics_with_states, 
                    rollback_reason, 
                    proof_tree_str,
                    rb_steps=rollback_steps
                )
                
                if rollback_result['success']:
                    target_index = rollback_result['target_index']  # Index for list slicing
                    target_step_number = rollback_result['target_step_number']  # Actual step number
                    rollback_distance = rollback_result['rollback_distance']
                    
                    # Update successful_tactics_with_states to match rollback (use index)
                    successful_tactics_with_states = successful_tactics_with_states[:target_index]
                    
                    last_tool_success = True
                    _clear_error_tracking()
                    
                    # Update proof tree string
                    proof_tree_str = self.proof_tree.get_proof_tree_string()
                    
                    self.logger.info(f"✅ Rollback successful: {rollback_distance} step{'s' if rollback_distance != 1 else ''} back to index {target_index} (step_number {target_step_number})")
                    
                    prompt = f"Rollback completed successfully. Returned {rollback_distance} step{'s' if rollback_distance != 1 else ''} back to step {target_step_number}.\n\n"
                    prompt += "## CURRENT PROOF TREE:\n"
                    prompt += f"{proof_tree_str}\n\n"
                    prompt += "Now consider a different approach to complete the proof. Update the plan if needed. Avoid repeating the same tactics that led to this rollback."
                else:
                    prompt = f"Rollback failed: {rollback_result.get('message', 'Unknown error')}\nPlease continue with tactics."
                    self.logger.error(f"❌ Rollback failed: {rollback_result.get('message')}")
                
                continue
            
            elif decision_type == 'tactic':
                
                self.gen_step_count += 1 # Update generation step count
                
                tactic_content = self.context_manager.get_tactic(decision_content, tool_call_id)
                
                # Check if a query is supplied as tactic
                if tactic_content.startswith(("Search", "Print", "Check", "About")):
                    prompt = f"You have supplied a 'query' as a 'tactic'. Please call the 'query' tool instead.\n"
                    prompt += self.context_manager.handle_query_call(decision_content, tool_call_id)
                    self.logger.info(f"⚠️  Step {self.global_step_id}: QUERY AS TACTIC!")
                    self.query_commands.append(decision_content)
                    self.gen_step_count -= 1 # undo the increment
                    consecutive_queries += 1
                    consecutive_errors += 1
                    continue

                # Early abort: give up
                if tactic_content in ["Abort.", "abort.", ]:
                    self.logger.info(f"⚠️  Step {self.global_step_id}: ABORTING PROOF -- giving up!")
                    self.give_up = True
                    return []

                # Disallow certain tactics
                if tactic_content in ["Admitted.", "admit.", ]:
                    prompt = "Tactic not allowed. Suggest a *different* tactic.\n"
                    prompt += "If some errors persist, you may consider (1) reviewing your plan, (2) searching/querying for relevant terms, or (3) rolling back to an earlier state."
                    self.logger.info(f"⚠️  Step {self.global_step_id}: ADMITTED TACTIC -- skipped!")
                    consecutive_errors += 1
                    continue
                
                # Repeating failed tactics
                if tactic_content in error_tactics:
                    prompt = "This tactic has been tried and failed. Suggest a *different* tactic.\n"
                    prompt += "If some errors persist, you may consider (1) reviewing your plan, (2) searching/querying for relevant terms, or (3) rolling back to an earlier state."
                    self.logger.info(f"⚠️  Step {self.global_step_id}: REPEATING FAILED TACTIC -- skipped!")
                    consecutive_errors += 1
                    continue
                
                # Save states before tactic application
                subgoals_before = self.coq.get_subgoals()
                goals_before = proof_state.get('goals', '').strip()
                hypotheses_before = proof_state.get('hypotheses', '').strip()

                prompt = "" # reset prompt
                success = self._apply_tactic(tactic_content)
                
                if not success: # Failed tactic application
                    
                    failed_tactic = tactic_content
                    consecutive_errors += 1
                    error_tactics.append(failed_tactic)
                    self.failed_tactics.append(failed_tactic)
                    failed_error = self.coq.get_last_error()
                    self.logger.info(f"⚠️  Step {self.global_step_id}: TACTIC APPLICATION failed")
                    
                    # If errors persist, try hammer ONCE per proof state
                    if consecutive_errors == self.max_errors + 1 and self.enable_hammer:
                        success = self._try_hammer()
                    
                    # If still failed, provide feedback and history
                    if not success:
                        # Feedback with error message
                        prompt += f"Tactic application failed with error: {failed_error}\n" 
                        prompt += hints_from_error(failed_tactic, failed_error)
                        
                        # Add suggestion when errors persist
                        if consecutive_errors > self.max_errors:
                            prompt += "\nIf errors persist, you may consider using other available tools."
                        
                        # Add history feedback
                        prompt += self._provide_history_feedback(consecutive_errors)
                        
                        continue
                    else:
                        # hammer succeeds, fall through with updated prompt
                        prompt += "Application failed with supplied tactic, but hammer succeeded.\n"
                
                assert success, "Unreachable with failed tactic application"
                
                last_tool_success = True
                _clear_error_tracking()
                successful_tactic = tactic_content
                self.logger.info(f"🏆 Tactic applied: '{successful_tactic}'")

                # Get proof state after tactic application
                current_goals_after = self.coq.get_goal_str()
                current_hypotheses_after = self.coq.get_hypothesis()
                subgoals_after = self.coq.get_subgoals() 

                # Invoke successful tactic handling routine
                tactic_with_state = self._handle_successful_tactic(
                    successful_tactic, 
                    subgoals_before, subgoals_after,
                    goals_before, current_goals_after,
                    hypotheses_before, current_hypotheses_after
                )
                successful_tactics_with_states.append(tactic_with_state)
            
                # Get proof completion status; apply Qed if proof is complete
                post_tactic_status = self.coq.get_proof_completion_status()

                # Case 1: Main proof is complete -> exit
                if post_tactic_status['is_complete'] and post_tactic_status['qed_already_applied']:                        
                    self.is_successful = True
                    break
                
                # Case 2: Goal still open -> update proof tree and feedback
                else:
                    prompt += f"Tactic '{successful_tactic}' applied successfully.\n\n"
                    
                    # ALWAYS update proof tree string
                    proof_tree_str = self.proof_tree.get_proof_tree_string()
                    
                    # Only show proof tree if subgoals have been changed
                    # Convert Goal objects to strings for comparison
                    def goal_to_str(goal) -> str:
                        if hasattr(goal, 'ty'):
                            return str(goal.ty).strip()
                        elif isinstance(goal, str):
                            return goal.strip()
                        else:
                            return str(goal).strip()
                    
                    goals_before_str = goal_to_str(goals_before)
                    goals_after_str = goal_to_str(current_goals_after)
                    # subgoals_before_str = "\n".join([goal_to_str(g) for g in subgoals_before])
                    # subgoals_after_str = "\n".join([goal_to_str(g) for g in subgoals_after])
                    # self.logger.debug(f"Goals before: {goals_before_str}")
                    # self.logger.debug(f"Goals after: {goals_after_str}")
                    # self.logger.debug(f"Subgoals before: {subgoals_before_str}")
                    # self.logger.debug(f"Subgoals after: {subgoals_after_str}")
                    
                    if goals_after_str != goals_before_str:
                        prompt += "## CURRENT PROOF TREE:\n"
                        prompt += f"{proof_tree_str}\n"
                    else:
                        prompt += "Goals: No changes.\n"
                    
                    prompt += f"Hypotheses: {current_hypotheses_after if current_hypotheses_after else 'None'}\n"
                
                self.logger.info(f"✅ Step {self.global_step_id}: TACTIC APPLIED SUCCESSFULLY!")
            
            else:
                prompt = f"Invalid function call: {decision_type}"
                self.logger.warning(f"❌ Step {self.global_step_id}: INVALID FUNCTION CALL!")
                continue
        
        return successful_tactics_with_states

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
                    self.logger.info(f"🌳 Branching tactic detected: {len(subgoals_before)} -> {len(subgoals_after)} subgoals")
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
                    self.logger.info(f"🌳 Added branching node: {len(subgoals_after)} subgoals created")
                else:
                    self.logger.warning(f"⚠️  No open subgoals to attach branching tactic [{successful_tactic}] to. Skipping node addition.")

            else:
                # Regular linear step - attach to correct subgoal
                if self.proof_tree.open_subgoals:
                    self.logger.info(f"🌳 Linear tactic: attaching to correct subgoal")
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
                    self.logger.info(f"🌳 Linear tactic: no open subgoals, adding regular node")
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
            self.logger.error(f"💀 Exception during rollback execution: {e}")
            import traceback
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
                self.logger.debug(f"🔧 Hammer is not able to find a proof. Continuing...")
            else:
                self.logger.error(f"🔧 Hammer failed with unknown error: {hammer_error}")
            return False
        
