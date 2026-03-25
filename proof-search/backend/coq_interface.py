# backend/coq_interface.py

import os
import re
import signal
from typing import List, Dict, Any, Optional
from coqpyt.coq.proof_file import ProofFile
from coqpyt.coq.exceptions import InvalidChangeException
from coqpyt.coq.structs import TermType
from pathlib import Path
from contextlib import contextmanager
from utils.logger import setup_logger, clean_ansi_codes

class CoqInterface:
    def __init__(self, file_path: str, workspace: Optional[str] = None, 
                 library_paths: Optional[List[Dict[str, str]]] = None,
                 auto_setup_coqproject: bool = False,
                 coqproject_extra_options: Optional[List[str]] = None,
                 timeout: int = 10):
        """
        Initialize Coq interface.
        
        NEW PARAMETERS:
        - library_paths: List of library mappings [{"path": "/path", "name": "libname"}, ...]
        - auto_setup_coqproject: Whether to automatically create/update _CoqProject
        - coqproject_extra_options: Additional options for _CoqProject
        """
        self.file_path = file_path
        self.workspace = workspace
        
        # Library support attributes
        self.library_paths = library_paths or []
        self.auto_setup_coqproject = auto_setup_coqproject
        self.coqproject_extra_options = coqproject_extra_options or []
        
        self.timeout = timeout
        self.proof_file = None
        self.proof = None
        self.last_error = None
        self.logger = setup_logger("CoqInterface")
        
        # Setup library paths if configured
        if self.auto_setup_coqproject and (self.library_paths or self.coqproject_extra_options):
            self._setup_coqproject()

        self.dangerous_tactic_patterns = [
            r'repeat\s*\(',           # repeat tactics can loop infinitely
            r'do\s+\d{3,}',           # do with large numbers
            r'apply.*with.*-?\d{7,}', # apply with very large numbers
        #   r'rewrite.*\*',           # rewrite with wildcard can be expensive
        ]

    # Add library setup method
    def _setup_coqproject(self):
        """Create or update _CoqProject file with library paths and extra options."""
        try:
            coqproject_path = Path(self.workspace or Path(self.file_path).parent) / "_CoqProject"
            
            self.logger.info(f"Setting up _CoqProject at {coqproject_path}")
            
            # Create _CoqProject content
            content_lines = []
            
            # Add library mappings
            for lib_config in self.library_paths:
                lib_path = lib_config["path"]
                lib_name = lib_config["name"]
                
                # Ensure we use absolute paths for reliability
                if not os.path.isabs(lib_path):
                    workspace_dir = self.workspace or str(Path(self.file_path).parent)
                    lib_path = os.path.abspath(os.path.join(workspace_dir, lib_path))
                
                content_lines.append(f"-R {lib_path} {lib_name}")
                self.logger.info(f"  Added library mapping: {lib_path} -> {lib_name}")
            
            # Add extra options
            for option in self.coqproject_extra_options:
                content_lines.append(option)
                self.logger.info(f"  Added extra option: {option}")
            
            # Write _CoqProject file
            with open(coqproject_path, 'w') as f:
                f.write('\n'.join(content_lines) + '\n')
            
            self.logger.info("✅ _CoqProject file created successfully")
            
        except Exception as e:
            self.logger.error(f"Failed to setup _CoqProject: {e}")
            raise

    def load(self):
        """Open the Coq file, run it, and set up for proof replay."""
        try:
            self.close()
            self.logger.info(f"Loading Coq file: {self.file_path}")
            
            # Create ProofFile with workspace and timeout
            self.proof_file = ProofFile(
                self.file_path, 
                workspace=self.workspace,  # Use the workspace if set
                timeout=self.timeout,
                use_disk_cache=True
            )
            self.proof_file.run()
            
            # Always get the first admitted proof (there should be one)
            self.proof = self.get_unproven_proof()
            
            if not self.proof:
                self.logger.warning("No unproven proof found in file")
                return False
            
            # Pop 'Admitted.' to open the proof for tactic replay
            if self.proof and self.proof.steps and self.proof.steps[-1].text.strip() == "Admitted.":
                self.proof_file.pop_step(self.proof)
                self.logger.info("Removed 'Admitted.' to open proof for replay")
            
            self.logger.info(f"Successfully loaded proof with {len(self.proof.steps)} initial steps")
            
            # Log library loading status
            if self.library_paths:
                self.logger.info(f"Loaded with {len(self.library_paths)} custom library paths")
                for lib_config in self.library_paths:
                    self.logger.info(f"  - {lib_config['name']}: {lib_config['path']}")
            
            return True
            
        except Exception as e:
            self.close()
            self.last_error = f"Failed to load file: {str(e)}"
            self.logger.error(self.last_error)
            return False

    def get_unproven_proof(self):
        """Return the first unproven/admitted proof."""
        try:
            if self.proof_file and self.proof_file.unproven_proofs:
                return self.proof_file.unproven_proofs[0]
            return None
        except Exception as e:
            self.logger.error(f"Error getting unproven proof: {e}")
            return None
    
    def get_context_terms(self):
        """Return all terms currently in the context."""
        try:
            if self.proof_file and self.proof_file.context:
                return self.proof_file.context.terms
            return {}
        except Exception as e:
            self.logger.error(f"Error getting context terms: {e}")
            return {}

    def get_notations(self):
        """Return only notation terms in the context."""
        try:
            terms = self.get_context_terms()
            return [t for t in terms.values() if hasattr(t, 'type') and t.type == TermType.NOTATION]
        except Exception as e:
            self.logger.error(f"Error getting notations: {e}")
            return []
    
    def get_raw_goal_str(self):
        """Return the string representation of the current goal."""
        try:
            # Check if proof_file is loaded
            if not self.proof_file:
                return "(no proof file loaded)"

            # FORCE REFRESH: Reset the goal cache before getting goals
            self.proof_file.__last_end_pos = None
        
            # Force refresh by accessing current_goals
            current_goals = self.proof_file.current_goals
            if current_goals:
                return str(current_goals)
        
            proof = self.get_unproven_proof()
            
            # If no unproven proof, check if this means we're done
            if not proof:
                # Check if there are any unproven proofs left
                if not self.proof_file or not self.proof_file.unproven_proofs:
                    return "Proof finished"
                return "(no current goal)"
            
            if not proof.steps:
                return "(no current goal)"
            
            # Get the last step's goals
            last_step = proof.steps[-1]
            goals = getattr(last_step, "goals", "")
            
            # Check if the last step was Qed - if so, proof should be finished
            last_step_text = last_step.text.strip().lower()
            if last_step_text in ['qed.', 'qed', 'defined.', 'defined']:
                return "Proof finished"
            
            if not goals:
                # No goals might mean proof is finished
                return "Proof finished"
            
            # Handle different goal formats
            if isinstance(goals, list):
                if not goals:
                    return "Proof finished"
                return "\n\n".join(str(g) for g in goals)
            
            goals_str = str(goals).strip()
            
            # Clean up redundant "Goals:" prefixes and formatting
            if goals_str.startswith("Goals:"):
                goals_str = goals_str[6:].strip()
            
            # Remove excessive newlines and clean up formatting
            lines = goals_str.split('\n')
            cleaned_lines = []
            
            for line in lines:
                line = line.strip()
                if line:  # Only keep non-empty lines
                    cleaned_lines.append(line)
            
            # Rejoin with single newlines
            cleaned_goals = '\n'.join(cleaned_lines)
            
            return cleaned_goals if cleaned_goals else "Proof finished"
        
        except Exception as e:
            self.logger.error(f"Error getting goal string: {e}")
            return f"(error retrieving goals: {str(e)})"
    
    def get_raw_hypothesis(self):
        """Return the current hypotheses/context for the active proof state."""
        try:
            proof = self.get_unproven_proof()
            if not proof or not proof.steps:
                return ""
            
            # Get the last step's context/hypotheses
            last_step = proof.steps[-1]
            
            # Try different ways to get hypotheses
            if hasattr(last_step, 'hypotheses'):
                hyp = last_step.hypotheses
            elif hasattr(last_step, 'context'):
                hyp = last_step.context
            else:
                return ""
            
            if not hyp:
                return ""
            
            # Handle different hypothesis formats
            if isinstance(hyp, dict):
                if not hyp:
                    return ""
                hyp_lines = []
                for name, value in hyp.items():
                    hyp_lines.append(f"{name} : {value}")
                return "\n".join(hyp_lines)
            elif isinstance(hyp, list):
                return "\n".join(str(h) for h in hyp)
            else:
                return str(hyp)
                
        except Exception as e:
            self.logger.error(f"Error getting hypotheses: {e}")
            return f"(error retrieving hypotheses: {str(e)})"

    def get_goal_str(self):
        """Get goal string with ANSI codes removed for file output."""
        raw_goals = self.get_raw_goal_str()
        return clean_ansi_codes(raw_goals)

    def get_hypothesis(self):
        """Get hypotheses string with ANSI codes removed for file output."""
        raw_hypotheses = self.get_raw_hypothesis()
        return clean_ansi_codes(raw_hypotheses)

    def is_dangerous_tactic(self, tactic: str) -> bool:
        """Check if a tactic might cause timeout or infinite loops."""
        import re
        tactic_lower = tactic.lower().strip()
        
        for pattern in self.dangerous_tactic_patterns:
            if re.search(pattern, tactic_lower):
                return True
        return False
    
    def sanitize_tactic(self, tactic: str) -> str:
        """Replace dangerous tactic patterns with safer alternatives."""
        import re
        
        original = tactic
        
        # Replace dangerous repeat patterns
        tactic = re.sub(r'repeat\s*\([^)]*Z\.le_[^)]*\)', 'lia', tactic)
        tactic = re.sub(r'repeat\s*\([^)]*apply[^)]*-?\d{7,}[^)]*\)', 'lia', tactic)
        
        # Replace complex arithmetic with lia
        if re.search(r'apply.*Z\.le.*with.*-?\d{7,}', tactic):
            tactic = 'lia'
        
        # Log replacements
        if tactic != original:
            self.logger.info(f"🔧 Sanitized tactic: '{original}' → '{tactic}'")
        
        return tactic
    
    def apply_tactic(self, tactic: str) -> bool:
        """Apply tactic with danger checking."""
        # Sanitize before applying
        tactic = self.sanitize_tactic(tactic)
        
        # Check if still dangerous after sanitization
        if self.is_dangerous_tactic(tactic):
            return False
        
        try:
            self.last_error = None
            
            if not self.proof:
                self.last_error = "No open proof available"
                self.logger.error(self.last_error)
                return False
            
            if not tactic or not tactic.strip():
                self.last_error = "Empty tactic provided"
                self.logger.error(self.last_error)
                return False
            
            # Clean the tactic string
            tactic_clean = tactic.strip().replace('\n', '').replace('\r', '')
            
            # Ensure tactic ends with period (except for { and } which don't need periods)
            # Note: } should be applied as ' }' (with leading space, no period)
            if not tactic_clean.endswith('.') and tactic_clean.strip() not in ['{', '}']:
                tactic_clean += '.'
            
            # Special handling for closing brace: ensure it has a leading space
            if tactic_clean.strip() == '}':
                tactic_clean = ' }'
            
            try:
                # Apply the tactic with proper spacing
                self.logger.info(f"➡️ Applying tactic: {tactic_clean}")
                formatted_tactic = f"\n  {tactic_clean}"
                
                # Get current step count before adding
                steps_before = len(self.proof.steps)

                step = self.proof_file.append_step(self.proof, formatted_tactic)
                
                steps_after = len(self.proof.steps)
                if steps_before + 1 != steps_after:
                    self.logger.error(f"Error: Step count mismatch after applying '{formatted_tactic}'")
                    self.logger.error(f"Error: Step count before={steps_before}, after={steps_after}")
                    exit(1) # Fail fast
                
                # CRITICAL: Force refresh of the current goals after applying tactic
                self.proof_file.__last_end_pos = None
                
                # After applying tactic, check if this completed the proof
                if tactic_clean.lower() in ['qed.', 'qed']:
                    self.logger.info(f"✅ Applied Qed - proof should be complete")
                else:
                    # Check if proof became complete after this tactic
                    goals_after = self.get_goal_str()
                    if goals_after and "proof finished" in goals_after.lower():
                        self.logger.info(f"✅ Tactic '{tactic_clean}' completed the proof!")
                    elif not goals_after or goals_after.strip() in ["", "(no current goal)", "No more goals"]:
                        self.logger.info(f"✅ Tactic '{tactic_clean}' solved all goals!")
                    else:
                        self.logger.debug(f"✅ Tactic applied: '{tactic_clean}'")
            
                return True
            
            except InvalidChangeException as e:
                # Try to get detailed error from the exception itself and other sources
                detailed_error = self._collect_error_from_multiple_sources(tactic_clean, e)
                
                if detailed_error:
                    reduced_error = reduce_error_verbosity(detailed_error)
                    self.last_error = f"Invalid tactic '{tactic_clean}':\n{reduced_error}"
                        
                else:
                    # Fallback to basic error
                    error_clean = reduce_error_verbosity(str(e).replace('\n', ' '))
                    self.last_error = f"Invalid tactic '{tactic_clean}': {error_clean}"
                
                return False
            
        except Exception as e:
            error_clean = str(e).replace('\n', ' ')
            self.last_error = f"Error applying tactic '{tactic}': {error_clean}"
            self.logger.error(self.last_error)
            
            # Abort if Coq server quit
            # (<ErrorCodes.ServerQuit: -32003>, 'Server quit')
            if 'quit' in error_clean.lower():
                assert False, "Coq server quit unexpectedly."
            
            return False

    def _collect_error_from_multiple_sources(self, tactic: str, exception: Exception) -> str:
        """
        Collect detailed error information from multiple sources including the exception itself.
        """
        error_parts = []
        
        # Method 1: Check if the exception has detailed error information
        try:
            exception_str = str(exception)
            if hasattr(exception, 'errors') and exception.errors:
                # This is like InvalidAddException in the test code
                for error in exception.errors:
                    if hasattr(error, 'message'):
                        error_parts.append(error.message)
                    else:
                        error_parts.append(str(error))
            elif len(exception_str) > 50:  # Substantial error message
                error_parts.append(exception_str)
        except Exception as e:
            self.logger.debug(f"Error extracting from exception: {e}")
        
        # Method 2: Check proof file diagnostics
        try:
            if hasattr(self.proof_file, 'diagnostics') and self.proof_file.diagnostics:
                for diagnostic in self.proof_file.diagnostics:
                    if hasattr(diagnostic, 'message') and diagnostic.message:
                        # Check if this diagnostic might be related to our tactic
                        msg = diagnostic.message
                        if (any(keyword in msg.lower() for keyword in [
                            'unify', 'environment', 'unable', 'error', 'cannot'
                        ]) or tactic.lower().replace('.', '') in msg.lower()):
                            error_parts.append(msg)
        except Exception as e:
            self.logger.debug(f"Error checking proof file diagnostics: {e}")
        
        # Method 3: Check proof file errors  
        try:
            if hasattr(self.proof_file, 'errors') and self.proof_file.errors:
                for error in self.proof_file.errors:
                    if hasattr(error, 'message') and error.message:
                        error_parts.append(error.message)
        except Exception as e:
            self.logger.debug(f"Error checking proof file errors: {e}")
        
        # Method 4: REMOVED - was causing "Syntax error: illegal begin of vernac."
        # The manual error capture was working but causing extra syntax errors
        # Since we're already getting perfect error collection (100% success rate),
        # we don't need this method anymore.
        
        # Combine and deduplicate error parts
        if error_parts:
            # Remove duplicates while preserving order
            unique_parts = []
            seen = set()
            for part in error_parts:
                # Also clean up any "Syntax error: illegal begin of vernac." from the parts
                cleaned_part = part.replace('Syntax error: illegal begin of vernac.', '').strip()
                if cleaned_part and cleaned_part not in seen:
                    unique_parts.append(cleaned_part)
                    seen.add(cleaned_part)
            
            if unique_parts:
                return '\n'.join(unique_parts)
        
        return None
    
    def get_last_error(self) -> str:
        """Get the last error message from Coq operations."""
        if self.last_error:
            return self.last_error
        return None

    def print_steps(self):
        """Print all steps of the current proof."""
        try:
            if not self.proof:
                self.logger.error("No open proof!")
                return
            
            self.logger.info("== Current proof steps ==")
            for i, step in enumerate(self.proof.steps):
                self.logger.info(f"Step {i+1}: {step.text.strip()}")
                
        except Exception as e:
            self.logger.error(f"Error printing steps: {e}")

    def print_goals(self):
        """Print current goals (if any) of the proof."""
        try:
            goals = self.get_goal_str()
            self.logger.info("Current goals:")
            self.logger.info(goals)
        except Exception as e:
            self.logger.error(f"Error printing goals: {e}")

    def is_proof_complete(self) -> bool:
        """Check if the current proof is complete."""
        try:
            proof = self.get_unproven_proof()
            if not proof:
                self.logger.warning("No unproven proof found")
                return False
            
            if not proof.steps:
                return False
            
            # Check if last step is Qed/Defined
            last_step_text = proof.steps[-1].text.strip().lower()
            if last_step_text in ['qed.', 'qed', 'defined.', 'defined']:
                self.logger.debug(f"Found Qed/Defined step: {last_step_text}")
                return True
            
            # Get current goals
            goals = self.get_goal_str()
            
            # Check for "Proof finished" specifically
            if goals and "proof finished" in goals.lower():
                self.logger.debug("Found 'Proof finished' indicator")
                return True
            
            if goals and "no more goals, but there are some goals you gave up" in goals.lower():
                self.logger.debug("Found incomplete proof with given up goals")
                return False
            
            # Check various indicators of completion
            if not goals or goals.strip() in ["", "(no current goal)", "no more goals", "proof completed"]:
                self.logger.debug("No goals remaining - proof complete")
                return True
            
            # Check if goals string indicates completion
            goals_lower = goals.lower().strip()
            completion_indicators = [
                "proof finished",
                "no more subgoals",
                "proof complete",
                "proof is completed",
                "no more goals"
            ]
            
            for indicator in completion_indicators:
                if indicator in goals_lower:
                    self.logger.debug(f"Found completion indicator: {indicator}")
                    return True
            
            # Check the proof file's internal state
            try:
                # After Qed is applied, the proof might not be in unproven_proofs anymore
                if not self.proof_file.unproven_proofs:
                    self.logger.debug("No unproven proofs remaining - all complete")
                    return True
                    
                # Check if our current proof is still unproven
                if proof not in self.proof_file.unproven_proofs:
                    self.logger.debug("Current proof no longer in unproven list - complete")
                    return True
                    
            except Exception as e:
                self.logger.debug(f"Error checking proof file state: {e}")
        
            # Goal still remaining
            return False
            
        except Exception as e:
            self.logger.error(f"Error checking proof completion: {e}")
            # Conservative approach: if we can't check, assume incomplete
            return False

    # this version is wrong because it can poped one more step
    def reset_by_step(self, target_step: int) -> bool:
        """
        Reset proof state to a specific step by popping steps back.
        Much faster than reload+replay since it just removes steps.
    
        Args:
            target_step: Target step number (1-based) to reset to
    
        Returns:
            True if reset was successful, False otherwise
        """
        try:
            if not self.proof:
                self.last_error = "No open proof available for step reset"
                self.logger.error(self.last_error)
                return False
    
            current_steps = len(self.proof.steps)
    
            # Find the index of the "Proof." step (should not be popped)
            proof_step_index = -1
            for i, step in enumerate(self.proof.steps):
                if step.text.strip() == "Proof.":
                    proof_step_index = i
                    break
    
            if proof_step_index == -1:
                self.last_error = "No 'Proof.' step found; cannot safely reset"
                self.logger.error(self.last_error)
                return False
    
            min_steps = proof_step_index + 1  # Don't pop below this
    
            # Validate target step
            if target_step < min_steps:
                self.last_error = f"Invalid target step {target_step} - must be >= {min_steps} (the 'Proof.' step)"
                self.logger.error(self.last_error)
                return False
    
            if target_step > current_steps:
                self.last_error = f"Invalid target step {target_step} - current proof has {current_steps} steps"
                self.logger.error(self.last_error)
                return False
    
            if target_step == current_steps:
                self.logger.info(f"Already at target step {target_step} - no reset needed")
                return True
    
            # Calculate steps to remove
            steps_to_remove = current_steps - target_step
    
            self.logger.info(f"Resetting proof from step {current_steps} to step {target_step}")
            self.logger.info(f"Will pop {steps_to_remove} steps (but never below 'Proof.')")
            # Pop steps back to target, but never pop "Proof."
            successful_pops = 0
            failed_pops = 0
    
            for i in range(steps_to_remove):
                if len(self.proof.steps) <= min_steps:
                    self.logger.info("Reached 'Proof.' step; will not pop further.")
                    break
                try:
                    if self.proof.steps:
                        step_to_remove = self.proof.steps[-1]
                        step_text = step_to_remove.text.strip()[:50]
                        self.logger.debug(f"Popping step {len(self.proof.steps)}: {step_text}...")
                    self.proof_file.pop_step(self.proof)
                    successful_pops += 1
                except Exception as pop_error:
                    failed_pops += 1
                    self.logger.warning(f"Failed to pop step {len(self.proof.steps)}: {pop_error}")
                    if failed_pops > 3:
                        self.logger.error(f"Too many pop failures ({failed_pops}) - stopping reset")
                        break
        
            # Verify final state
            final_steps = len(self.proof.steps)
            #print(f"final steps after reset: {final_steps}, target was {target_step}")
            if final_steps == target_step:
                self.logger.info(f"✅ Successfully reset to step {target_step}")
                self.logger.info(f"📊 Removed {successful_pops} steps, {failed_pops} failures")
                try:
                    goals = self.get_goal_str()
                    self.logger.debug(f"🎯 Goals after reset: {goals[:100]}...")
                except Exception as goal_error:
                    self.logger.debug(f"Could not get goals after reset: {goal_error}")
                return True
            else:
                self.last_error = f"Reset incomplete: wanted step {target_step}, got step {final_steps}"
                self.logger.error(self.last_error)
                return False
    
        except Exception as e:
            self.last_error = f"Error during step reset: {str(e)}"
            self.logger.error(self.last_error)
            return False


    def reset(self):
        """Reset to the initial state for this file (close/reload) - DEPRECATED."""
        try:
            self.logger.warning("reset() is deprecated - use reset_by_step() for specific step or clear_unproven_proof_steps() for full reset")
            return self.load()
        except Exception as e:
            self.logger.error(f"Error during reset: {e}")
            return False

    def get_current_step_number(self) -> int:
        """Get the current step number (1-based)."""
        try:
            if not self.proof or not self.proof.steps:
                return 0
            return len(self.proof.steps)
        except Exception as e:
            self.logger.error(f"Error getting current step number: {e}")
            return 0

    def can_reset_to_step(self, target_step: int) -> bool:
        """Check if we can reset to a specific step without actually doing it."""
        try:
            if not self.proof:
                return False
            
            current_steps = len(self.proof.steps)
            return 1 <= target_step <= current_steps
            
        except Exception as e:
            self.logger.error(f"Error checking if can reset to step: {e}")
            return False

    def get_step_info(self, step_number: int) -> Dict[str, Any]:
        """Get information about a specific step."""
        try:
            if not self.proof or not self.proof.steps:
                return {"error": "No proof available"}
            
            if step_number < 1 or step_number > len(self.proof.steps):
                return {"error": f"Invalid step number {step_number}"}
            
            step = self.proof.steps[step_number - 1]  # Convert to 0-based
            
            return {
                "step_number": step_number,
                "text": step.text.strip(),
                "goals_before": getattr(step, 'goals_before', 'Unknown'),
                "goals_after": getattr(step, 'goals', 'Unknown'),
                "success": True
            }
            
        except Exception as e:
            return {"error": f"Error getting step info: {str(e)}"}

    def clear_unproven_proof_steps(self) -> bool:
        """
        Clear existing proof steps from an unproven proof.
        If the proof is already complete with Qed, restart it as unproven.
        """
        try:
            # change the Qed to Admitted if it exists
            self.logger.info("Clearing unproven proof steps")
            if not self.proof_file:
                self.logger.error("No proof file loaded")
                return False
            self.ensure_admitted(self.file_path)
            proof = self.get_unproven_proof()
            
            if not proof:
                self.logger.debug("No unproven proof found")
                # Try to create an unproven version from the complete proof
                return self._convert_complete_to_unproven()
            
            # Check if the proof is already complete (ends with Qed)
            if proof.steps:
                last_step_text = proof.steps[-1].text.strip().lower()
                if last_step_text in ['qed.', 'qed', 'defined.', 'defined']:
                    self.logger.info("Found complete proof with Qed - converting to unproven")
                    return self._convert_complete_to_unproven()
            
            # If we have steps but no Qed, clear them normally
            if proof.steps:
                self.logger.info(f"Clearing {len(proof.steps)} existing proof steps")
                
                # Find the initial "Proof." step
                proof_step_index = -1
                for i, step in enumerate(proof.steps):
                    if step.text.strip() == "Proof.":
                        proof_step_index = i
                        break
                
                if proof_step_index == -1:
                    self.logger.warning("No 'Proof.' step found")
                    return False
                
                # Keep popping steps until we only have steps up to and including "Proof."
                initial_steps = proof_step_index + 1  # Include the "Proof." step
                steps_removed = 0
                
                while len(proof.steps) > initial_steps:
                    try:
                        self.proof_file.pop_step(proof)
                        steps_removed += 1
                    except Exception as e:
                        self.logger.warning(f"Error removing step: {e}")
                        break
                
                self.logger.info(f"Cleared {steps_removed} proof steps, {len(proof.steps)} steps remaining")
                return True
            else:
                self.logger.debug("No proof steps to clear")
                return True
                
        except Exception as e:
            self.last_error = f"Error clearing proof steps: {str(e)}"
            self.logger.error(self.last_error)
            return False

    def _convert_complete_to_unproven(self) -> bool:
        """Convert a complete proof (with Qed) to an unproven proof."""
        try:
            self.logger.info("Converting complete proof to unproven format")
            
            # Step 1: Use the clear_all_proof_scripts method to modify the file
            if not self.clear_all_proof_scripts():
                self.logger.error("Failed to clear proof scripts from file")
                return False
            
            # Step 2: Reload the file with the cleared scripts
            self.close()  # Close current session
            
            if not self.load():  # Reload with cleared scripts
                self.logger.error("Failed to reload file after clearing scripts")
                return False
            
            self.logger.info("✅ Successfully converted complete proof to unproven format")
            return True
            
        except Exception as e:
            self.logger.error(f"Error converting complete proof to unproven: {e}")
            return False

    def clear_all_proof_scripts(self) -> bool:
        """
        Overwrite the .v file to remove all proof scripts, leaving only the statement 
        and 'Proof.' for each proof, plus 'Admitted.' so Coq can parse.
        """
        try:
            # Ensure file_path is a Path object
            file_path = Path(self.file_path) if isinstance(self.file_path, str) else self.file_path
            
            # Read the original file
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Create backup
            backup_path = file_path.with_suffix('.v.backup')
            with open(backup_path, 'w', encoding='utf-8') as f:
                f.write(content)
            self.logger.debug(f"Created backup at {backup_path}")
            
            lines = content.split('\n')
            output = []
            in_proof = False
            
            for line in lines:
                line_stripped = line.strip()
                
                # Check if we're starting a proof
                if re.match(r'^\s*Proof\s*\.', line):
                    in_proof = True
                    output.append(line)  # Keep the Proof. line
                    output.append('  Admitted.')  # Add Admitted immediately after with proper indentation
                    continue
                
                # Check if we're ending a proof
                if in_proof and re.match(r'^\s*(Qed\s*\.|Admitted\s*\.|Defined\s*\.)', line):
                    in_proof = False
                    continue  # Skip the original ending
                
                # Skip all lines inside proof except Proof. itself
                if in_proof:
                    continue
                
                # Keep all non-proof lines
                output.append(line)
        
            # Write the modified content
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(output))
            
            self.logger.info("✅ Successfully cleared all proof scripts from file")
            return True
            
        except Exception as e:
            self.last_error = f"Error clearing proof scripts: {str(e)}"
            self.logger.error(self.last_error)
            return False

    def close(self):
        """Close the Coq interface and clean up resources."""
        try:
            if hasattr(self, 'proof_file') and self.proof_file:
                try:
                    # Close the proof file
                    if hasattr(self.proof_file, 'close'):
                        self.proof_file.close()
                    self.logger.debug("Proof file closed")
                except Exception as e:
                    self.logger.warning(f"Error closing proof file: {e}")
                    self.force_close() # force kill
                finally:
                    self.proof_file = None
            
            if hasattr(self, 'proof') and self.proof:
                self.proof = None
            
        except Exception as e:
            self.logger.warning(f"Error during CoqInterface close: {e}")
            # Don't raise - just log and continue
    
    def force_close(self):
        try:
            self.logger.info("Forcing coq-lsp shutdown...")
            self.proof_file.coq_lsp_client.lsp_endpoint.stop()
        except Exception as e:
            self.logger.warning(f"Error during forceful close: {e}")
    
    def in_proof(self) -> bool:
        """Check if we're currently in an active proof."""
        try:
            return self.proof is not None and len(self.proof.steps) > 0
        except Exception as e:
            self.logger.error(f"Error checking proof status: {e}")
            return False

    def _clean_coqpyt_module_names(self, text: str) -> str:
        """Replace temporary coqpyt module names with 'Top.'"""
        import re
        # Pattern: coqpyt_aux_<32_hex_chars>
        pattern = r'coqpyt_aux_[0-9a-f]{32}'
        return re.sub(pattern, 'Top', text)

    def search(self, query: str) -> str:
        """Execute any Coq query command (Search, Print, Locate, About, Check, Print Assumptions) using aux_file."""
        try:
            self.last_error = None
            
            # Clean and normalize the query
            query = query.strip()
            if not query.endswith('.'):
                query += '.'
            
            # Ensure we have aux_file access
            if not hasattr(self.proof_file, "_ProofFile__aux_file"):
                self.last_error = "aux_file not accessible"
                return "aux_file not accessible"
            
            aux_file = self.proof_file._ProofFile__aux_file
            
            # Save the line count before adding the query
            line_before = len(aux_file.read().split("\n"))
            
            # Append the query to aux_file
            aux_file.append(f"\n{query}")
            aux_file.didChange()
            
            import time
            time.sleep(0.1)  # Wait for LSP to process
            
            # Extract command type and parameters
            parts = query.split()
            if not parts:
                return "Empty query"
            
            cmd_type = parts[0].lower()
            
            # Handle different command types
            if cmd_type == "search":
                # Use existing Search logic
                search_term = query[6:].strip().rstrip('.')
                if not search_term:
                    return "No search term provided"
                
                # Get search results
                all_results = []
                try:
                    queries = aux_file._AuxFile__get_queries("Search")
                    for query_obj in queries:
                        if hasattr(query_obj, 'query') and query_obj.query == search_term:
                            #print("Found matching search query : ", query_obj.query)
                            for result in query_obj.results:
                                message = result.message
                                line_num = result.range.start.line
                                
                                # Filter out non-search-result messages
                                # Skip proof goals and other contextual information
                                if line_num >= line_before:
                                    # Search results typically contain lemma/theorem names with ':'
                                    # Skip common proof goal indicators
                                    skip_prefixes = ['wp_goal:', 'Goals:', 'Proof.', 'Subgoal', 
                                                   'forall (', 'let ', 'This subproof', 
                                                   'Error:', 'Warning:']
                                    
                                    # Check if this looks like a proof goal rather than a search result
                                    is_proof_goal = any(message.strip().startswith(prefix) for prefix in skip_prefixes)
                                    
                                    # Search results should have a colon (name: type) and not be proof goals
                                    has_colon = ':' in message
                                    
                                    if has_colon and not is_proof_goal:
                                        # Additional check: search results typically start with an identifier
                                        # not with keywords like 'forall', 'let', etc.
                                        first_word = message.strip().split()[0] if message.strip() else ""
                                        if first_word and not first_word.lower() in ['forall', 'let', 'exists', 'fun']:
                                            all_results.append(message)
                                            self.logger.debug(f"Added search result: {message[:80]}...")
                                        else:
                                            self.logger.debug(f"Skipped (starts with keyword): {message[:80]}...")
                                    else:
                                        self.logger.debug(f"Skipped (proof goal or no colon): {message[:80]}...")
                except Exception as e:
                    self.logger.warning(f"Error extracting search results: {e}")
                
                # Return the collected results
                if all_results:
                    result_text = "\n".join(all_results)
                    self.logger.debug(f"Search found {len(all_results)} results")
                    return self._clean_coqpyt_module_names(result_text)
                else:
                    return "No results found."
            
            elif cmd_type in ["print", "locate", "about", "check"]:
                # Handle Print, Locate, About, Check commands
                try:
                    # Extract identifier
                    if cmd_type == "print" and len(parts) >= 3 and parts[1].lower() == "assumptions":
                        # Handle "Print Assumptions [identifier]"
                        cmd_for_diagnostics = "Print Assumptions"
                        identifier = parts[2].rstrip('.') if len(parts) >= 3 else ""
                    else:
                        # Handle regular commands: Print/Locate/About/Check identifier
                        cmd_for_diagnostics = cmd_type.title()
                        identifier = ' '.join(parts[1:]).rstrip('.') if len(parts) >= 2 else ""
                    
                    # Try get_diagnostics
                    current_lines = len(aux_file.read().split('\n'))
                    result = aux_file.get_diagnostics(cmd_for_diagnostics, identifier, current_lines - 1)
                    
                    if result and result.strip():
                        self.logger.debug(f"{cmd_type} command successful")
                        return self._clean_coqpyt_module_names(result)
                    else:
                        # If diagnostics didn't work, try checking file content changes
                        new_content = aux_file.read()
                        new_lines = new_content.split('\n')
                        
                        if len(new_lines) > line_before + 1:
                            # Extract potential output
                            output_lines = new_lines[line_before + 1:]
                            output = '\n'.join(line for line in output_lines if line.strip() and line.strip() != query.strip()).strip()
                            if output:
                                self.logger.debug(f"{cmd_type} command found content")
                                return self._clean_coqpyt_module_names(output)
                    
                        return "No results found."
                        
                except Exception as e:
                    self.logger.warning(f"Error executing {cmd_type} command: {e}")
                    return f"Error executing {cmd_type}: {str(e)}"
            
            else:
                # Unknown command type
                return f"Unsupported query type: {cmd_type}"
                
        except Exception as e:
            self.last_error = f"Query error: {str(e)}"
            self.logger.error(self.last_error)
            return self.last_error

    @staticmethod
    def ensure_admitted(filename):
        """Utility method to ensure a file has 'Admitted.' instead of 'Qed.'"""
        try:
            with open(filename, 'r') as f:
                lines = f.readlines()
            
            modified = False
            for i in reversed(range(len(lines))):
                if lines[i].strip() == "Qed.":
                    lines[i] = "Admitted.\n"
                    modified = True
                    break
            
            if modified:
                with open(filename, "w") as f:
                    f.writelines(lines)
                    
            return modified
            
        except Exception as e:
            return False

    def get_proof_status(self) -> Dict[str, Any]:
        """Get comprehensive status of the current proof."""
        try:
            return {
                "has_proof": self.proof is not None,
                "proof_steps": len(self.proof.steps) if self.proof else 0,
                "is_complete": self.is_proof_complete(),
                "current_goals": self.get_goal_str(),
                "has_error": self.last_error is not None,
                "last_error": self.last_error
            }
        except Exception as e:
            return {
                "has_proof": False,
                "proof_steps": 0,
                "is_complete": False,
                "current_goals": f"Error: {str(e)}",
                "has_error": True,
                "last_error": str(e)
            }

    def is_ready_for_qed(self) -> bool:
        """
        Check if the proof is ready for Qed by actually trying to apply it.
        If Qed succeeds, keep it. If Qed fails, pop it back out.
        """
        try:
            proof = self.get_unproven_proof()
            if not proof or not proof.steps:
                return False
            
            # Check if Qed is already applied
            last_step_text = proof.steps[-1].text.strip().lower()
            if last_step_text in ['qed.', 'qed', 'defined.', 'defined']:
                self.logger.debug("Qed already applied")
                return True  # Already has Qed, so it was ready
            
            # Save the current step count so we can revert if needed
            original_step_count = len(proof.steps)
                        
            try:
                # Try to apply Qed
                formatted_qed = "\n  Qed."
                self.proof_file.append_step(self.proof, formatted_qed)
                
                # If we get here, Qed was successfully applied
                self.logger.info("✅ Qed applied successfully - proof is complete! Keeping Qed in file.")
                
                return True
            
            except Exception as qed_error:
                
                # Make sure we didn't accidentally add a step due to the failed attempt
                if len(proof.steps) > original_step_count:
                    try:
                        self.proof_file.pop_step(self.proof)
                        self.logger.debug("Cleaned up failed Qed attempt")
                    except Exception as cleanup_error:
                        self.logger.warning(f"Error cleaning up failed Qed: {cleanup_error}")
            
            return False
            
        except Exception as e:
            self.logger.error(f"Error checking if ready for Qed: {e}")
            return False

    def get_proof_completion_status(self) -> dict:
        """
        Get comprehensive information about proof completion status.
        Returns a dictionary with detailed status information.
        """
        try:
            proof = self.get_unproven_proof()
            goals = self.get_goal_str()
            
            status = {
                'has_proof': proof is not None,
                'step_count': len(proof.steps) if proof else 0,
                'current_goals': goals,
                'is_complete': self.is_proof_complete(),
                'ready_for_qed': self.is_ready_for_qed(),
                'qed_already_applied': False
            }
            
            if proof and proof.steps:
                last_step_text = proof.steps[-1].text.strip().lower()
                status['qed_already_applied'] = last_step_text in ['qed.', 'qed', 'defined.', 'defined']
            
            # Qed should have been applied if is_ready_for_qed()
            assert status['qed_already_applied'] == status['ready_for_qed']
        
            return status
            
        except Exception as e:
            self.logger.error(f"Error getting proof completion status: {e}")
            return {
                'has_proof': False,
                'step_count': 0,
                'current_goals': f"Error: {str(e)}",
                'is_complete': False,
                'ready_for_qed': False,
                'qed_already_applied': False,
                'error': str(e)
            }

    # Add method to get proof status with library info
    def get_proof_status_with_libraries(self) -> Dict[str, Any]:
        """Get comprehensive status including library information."""
        status = self.get_proof_status()  # Use existing method
        
        # Add library information
        status.update({
            "library_paths": self.library_paths,
            "workspace": self.workspace,
            "auto_setup_coqproject": self.auto_setup_coqproject
        })
        
        return status

    def get_proof_file_content(self) -> str:
        """
        Return the current content of the proof file after cleaning ANSI codes.
        This includes all statements, definitions, and current proof steps.
        """
        try:
            if not self.proof_file:
                self.logger.error("No proof file loaded")
                return ""
            
            # Get the raw content from the proof file
            raw_content = ""
            
            # Method 1: Try to get content from the proof file object
            if hasattr(self.proof_file, 'content'):
                raw_content = str(self.proof_file.content)
            elif hasattr(self.proof_file, '_content'):
                raw_content = str(self.proof_file._content)
            elif hasattr(self.proof_file, 'read'):
                raw_content = self.proof_file.read()
            else:
                # Method 2: Fallback to reading from file path
                try:
                    with open(self.file_path, 'r', encoding='utf-8') as f:
                        raw_content = f.read()
                    self.logger.debug("Read content from file path as fallback")
                except Exception as file_error:
                    self.logger.warning(f"Failed to read from file path: {file_error}")
                    return f"Error: Cannot access proof file content - {str(file_error)}"
            
            # Clean ANSI codes from the content
            clean_content = clean_ansi_codes(raw_content)
            
            # Log successful content retrieval
            content_lines = len(clean_content.split('\n'))
            content_chars = len(clean_content)
            self.logger.debug(f"Retrieved proof file content: {content_lines} lines, {content_chars} characters")
            
            return clean_content
            
        except Exception as e:
            error_msg = f"Error getting proof file content: {str(e)}"
            self.logger.error(error_msg)
            return f"Error: {error_msg}"
        
    # Add proper context manager support
    def __enter__(self):
        """Enter the context manager - return self for use in with statement."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Exit the context manager - clean up resources."""
        self.close()
        return False  # Don't suppress exceptions
    
    def get_subgoals(self) -> list:
        """
        Return a list of current subgoals with their hypotheses using the official coqpyt API.
        Returns ALL goals including both focused goals and stack goals.
        Each goal includes its hypotheses which are crucial for understanding the proof context.
        
        Following the structure from coqpyt:
        current_goals -> GoalAnswer object
        current_goals.goals -> GoalConfig object
        current_goals.goals.goals -> List[Goal] (focused goals)
        current_goals.goals.stack -> List[Tuple[List[Goal], List[Goal]]] (backgrounded goals)
        
        Each Goal object has:
        - ty: the goal conclusion (string)
        - hyps: List[Hyp] where each Hyp has names (List[str]) and ty (string)
        """
        try:
            if not self.proof_file:
                self.logger.debug("No proof file available")
                return []
            
            # FORCE REFRESH: Reset the goal cache before getting goals
            # This is CRITICAL to get current state after tactic application
            self.proof_file.__last_end_pos = None
            
            # Get CURRENT goals directly from proof_file (not from cached step.goals)
            current_goals = self.proof_file.current_goals
            
            if not current_goals:
                self.logger.debug("No current goals available")
                return []
            
            # current_goals is a GoalAnswer object
            goal_answer = current_goals
            
            # GoalAnswer has a 'goals' attribute which is a GoalConfig object
            if not hasattr(goal_answer, 'goals') or not goal_answer.goals:
                self.logger.debug("No goals in GoalAnswer")
                return []
            
            goal_config = goal_answer.goals
            
            # GoalConfig has:
            # - goals: List[Goal] (focused goals)
            # - stack: List[Tuple[List[Goal], List[Goal]]] (backgrounded goals)
            all_goals = []
            
            # Get focused goals
            if hasattr(goal_config, 'goals') and isinstance(goal_config.goals, list):
                all_goals.extend(goal_config.goals)
                self.logger.debug(f"Found {len(goal_config.goals)} focused goals")
            
            # Get stack goals (goals that were pushed to background)
            if hasattr(goal_config, 'stack') and isinstance(goal_config.stack, list):
                for stack_entry in goal_config.stack:
                    # Each stack entry is a tuple (before_goals, after_goals)
                    if isinstance(stack_entry, tuple) and len(stack_entry) == 2:
                        before_goals, after_goals = stack_entry
                        # Add both before and after goals from the stack
                        if isinstance(before_goals, list):
                            all_goals.extend(before_goals)
                        if isinstance(after_goals, list):
                            all_goals.extend(after_goals)
                self.logger.debug(f"Found {len(goal_config.stack)} stack entries")
        
            # Log goal details including hypotheses
            for i, goal in enumerate(all_goals):
                if hasattr(goal, 'hyps'):
                    hyps_count = len(goal.hyps)
                    self.logger.debug(f"Goal {i+1}: has {hyps_count} hypotheses")
                else:
                    self.logger.debug(f"Goal {i+1}: no hypotheses attribute")
        
            self.logger.debug(f"Total subgoals (focused + stack): {len(all_goals)}")
            return all_goals
            
        except Exception as e:
            self.logger.error(f"Error getting subgoals: {e}")
            import traceback
            traceback.print_exc()
            return []
    '''
    def get_subgoals(self) -> list:
        """
        Return a list of current subgoals (as strings).
        """
        try:
            # Get the most recent goals
            goals_str = self.get_goal_str()
            
            # Handle "Proof finished" case
            if "proof finished" in goals_str.lower() or not goals_str.strip():
                return []
                
            # Clean up the goals string
            goals_str = goals_str.replace("Goals:", "").strip()
            
            # Split by lines of dashes (Coq uses these to separate subgoals)
            parts = re.split(r'-{10,}', goals_str)
            
            # Remove empty and whitespace-only entries, and "Bullet: None"
            subgoals = []
            for p in parts:
                cleaned = p.strip()
                if cleaned and "Bullet: None" not in cleaned and cleaned != "Goals:":
                    subgoals.append(cleaned)
                    
            self.logger.debug(f"Extracted {len(subgoals)} subgoals: {[sg[:50] + '...' if len(sg) > 50 else sg for sg in subgoals]}")
            return subgoals
            
        except Exception as e:
            self.logger.error(f"Error getting subgoals: {e}")
            return []
    '''
    def restart_coq_server(self):
        """
        Restart the Coq server to clear memory and reset state.
        Preserves the current file path and workspace configuration.
        """
        try:
            self.logger.info("🔄 Restarting Coq server to clear memory...")
            
            # Save current configuration
            current_file = self.file_path
            current_workspace = getattr(self, 'workspace', None)
            
            # Close existing proof file (NOT self.proof which is a ProofTerm)
            if self.proof_file:
                self.proof_file.close()
                self.proof_file = None
            
            # Clear the proof reference
            self.proof = None
            
            # Small delay to ensure cleanup
            import time
            time.sleep(0.5)
            
            # Reinitialize with same configuration
            if current_workspace:
                self.proof_file = ProofFile(
                    current_file,
                    timeout=self.timeout,
                    workspace=current_workspace,
                    use_disk_cache=False
                )
            else:
                self.proof_file = ProofFile(
                    current_file,
                    timeout=self.timeout,
                    use_disk_cache=False
                )
            
            # Run the proof file to restore to initial state
            self.proof_file.run()
            
            # Get the unproven proof again
            self.proof = self.get_unproven_proof()
            
            self.logger.info("✅ Coq server restarted successfully")
            return True
            
        except Exception as e:
            self.logger.error(f"❌ Failed to restart Coq server: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
            return False

    @contextmanager
    def timeout_protection(self, seconds=30):
        """Context manager to timeout long-running operations."""
        def timeout_handler(signum, frame):
            raise TimeoutError(f"Operation timed out after {seconds} seconds")
        
        # Set the signal handler
        old_handler = signal.signal(signal.SIGALRM, timeout_handler)
        signal.alarm(seconds)
        
        try:
            yield
        finally:
            # Restore the old signal handler
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old_handler)
    

def reduce_error_verbosity(error: str) -> str:
    """Reduce the verbosity of the of common error patterns."""
    
    if "Unable to unify" in error:
        return "Unable to unify" + error.split("Unable to unify")[1]
    
    elif "In environment" in error and "The term" in error:
        prefix = error.split("In environment")[0]
        suffix = error.split("The term")[1]
        return prefix + "\nThe term " + suffix
    
    else:
        return error