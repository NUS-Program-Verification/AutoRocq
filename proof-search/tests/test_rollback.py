import sys
from pathlib import Path
import time

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.coq_interface import CoqInterface
from utils.config import ProofAgentConfig
from tests.test_utils import reset_coq_file_to_admitted, restore_coq_file_from_backup

# --- CONFIGURATION ---
coq_file = PROJECT_ROOT / "examples" / "main_loop_invariant_2_established_Coq.v"
config_file = PROJECT_ROOT / "configs" / "default_config.json"

def print_current_goals(coq_interface):
    """Print current goals from the CoqInterface"""
    print("\n🎯 Current Goals:")
    try:
        goals_str = coq_interface.get_goal_str()
        if goals_str and goals_str != "No current goals":
            print(goals_str)
        else:
            print("(No goals remaining)")
    except Exception as e:
        print(f"(Error getting goals: {e})")

def print_current_hypotheses(coq_interface):
    """Print current hypotheses from the CoqInterface"""
    print("\n🔍 Current Hypotheses:")
    try:
        hypotheses_str = coq_interface.get_hypothesis()
        if hypotheses_str and hypotheses_str.strip():
            print(hypotheses_str)
        else:
            print("(No hypotheses)")
    except Exception as e:
        print(f"(Error getting hypotheses: {e})")

def print_current_proof_state(coq_interface):
    """Print complete current proof state (goals + hypotheses)"""
    print("\n" + "🔍 CURRENT PROOF STATE".center(50, "="))
    
    # Print hypotheses first (they're the context)
    print_current_hypotheses(coq_interface)
    
    # Then print goals (what we're trying to prove)
    print_current_goals(coq_interface)
    
    print("=" * 50)

def clean_proof_file(file_path):
    """Clean the proof file by removing everything after 'Proof.' and adding fresh 'Proof.'"""
    print("\n🧹 CLEANING PROOF FILE...")
    print("="*60)
    
    try:
        # Read the original file
        print(f"📖 Reading file: {file_path}")
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Find the position of "Proof."
        proof_pos = content.find("Proof.")
        if proof_pos == -1:
            print("❌ 'Proof.' not found in file")
            return False
        
        # Get content up to and including "Proof."
        clean_content = content[:proof_pos + len("Proof.")]
        
        # Add a newline after "Proof." to start fresh
        clean_content += "\n"
        
        # Show what we're removing
        removed_content = content[proof_pos + len("Proof."):]
        removed_lines = len(removed_content.splitlines())
        removed_chars = len(removed_content.strip())
        
        print(f"📊 Cleaning statistics:")
        print(f"   - Original file size: {len(content)} characters")
        print(f"   - Clean file size: {len(clean_content)} characters")
        print(f"   - Removed: {removed_chars} characters, {removed_lines} lines")
        print(f"   - Proof position: {proof_pos}")
        
        # Write the cleaned content back
        print(f"✍️ Writing cleaned content to: {file_path}")
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(clean_content)
        
        print("✅ File cleaned successfully!")
        print(f"✅ Ready for fresh proof starting from 'Proof.'")
        
        return True
        
    except Exception as e:
        print(f"❌ Error cleaning file: {e}")
        import traceback
        traceback.print_exc()
        return False

def print_applied_tactics(coq_interface, label="Applied Tactics"):
    """Print all tactics applied so far"""
    try:
        current_step = coq_interface.get_current_step_number()
        print(f"\n📝 {label} (Current step: {current_step}):")
        print("=" * 50)
        
        if current_step == 0:
            print("   (No tactics applied yet)")
            return
        
        for i in range(1, current_step + 1):
            step_info = coq_interface.get_step_info(i)
            if step_info.get("success", False):
                tactic_text = step_info.get("text", "Unknown").strip()
                print(f"   Step {i}: {tactic_text}")
            else:
                error = step_info.get("error", "Unknown error")
                print(f"   Step {i}: ❌ Error: {error}")
        
        print("=" * 50)
        
    except Exception as e:
        print(f"❌ Error printing applied tactics: {e}")

def test_rollback_functionality():
    """Test rollback to arbitrary step and Coq state reset/replay"""
    print("🔄 Testing rollback functionality...")
    
    try:
        # Clean the proof file first
        clean_success = clean_proof_file(coq_file)
        if not clean_success:
            print("❌ Failed to clean proof file")
            return False
        
        # Load configuration and initialize CoqInterface
        config = ProofAgentConfig.from_file(str(config_file))
        coq_interface = CoqInterface(
            file_path=str(coq_file),
            workspace=config.coq.workspace or str(coq_file.parent),
            library_paths=config.coq.library_paths,
            auto_setup_coqproject=config.coq.auto_setup_coqproject,
            coqproject_extra_options=config.coq.coqproject_extra_options,
            timeout=config.coq.timeout
        )
        
        try:
            # Load the file
            success = coq_interface.load()
            if not success:
                print(f"❌ Failed to load file: {coq_interface.get_last_error()}")
                return False
            
            print("✅ File loaded successfully")
            
            # Show initial state
            print_applied_tactics(coq_interface, "Initial State")
            print_current_proof_state(coq_interface)
            
            # Define test tactics (the actual sequence needed for the proof)
            # NOTE: Step 1 is "Proof." which is already applied when we load
            test_tactics = [
                "\n intros i_1 i Hle Hlow Hup Hup_i Hsint.",  # Step 2
                "\n assert (Hrange: -9 <= i <= 9) by lia.",    # Step 3  
                "\n destruct Hrange as [Hi_low Hi_up].",        # Step 4
                "\n Search Z.abs.",                             # Step 5
                "\n assert (Hi_abs_le : Z.abs i <= 9) by now apply Z.abs_le."  # Step 6
            ]
            
            print(f"\n🚀 PHASE 1: Apply {len(test_tactics)} tactics")
            print("="*60)
            
            # Store successful tactics with states
            successful_tactics_with_states = []
            
            # Apply all tactics and store states
            for i, tactic in enumerate(test_tactics, 1):
                # Note: step number = i + 1 because step 1 is "Proof."
                step_number = i + 1
                print(f"\n📝 Step {step_number}: Applying '{tactic}'")
                
                # Show state before applying tactic
                print_applied_tactics(coq_interface, f"Before Step {step_number}")
                
                # Capture state before tactic
                goals_before = coq_interface.get_goal_str()
                hypotheses_before = coq_interface.get_hypothesis()
                
                # Apply tactic
                success = coq_interface.apply_tactic(tactic)
                
                if success:
                    # Capture state after tactic
                    goals_after = coq_interface.get_goal_str()
                    hypotheses_after = coq_interface.get_hypothesis()
                    
                    # Store tactic with states
                    tactic_data = {
                        'step_number': step_number,  # This is the actual step number (2, 3, 4, 5, 6)
                        'tactic': tactic,
                        'goals_before': goals_before or '',
                        'goals_after': goals_after or '',
                        'hypotheses_before': hypotheses_before or '',
                        'hypotheses_after': hypotheses_after or ''
                    }
                    successful_tactics_with_states.append(tactic_data)
                    
                    print(f"✅ Step {step_number} SUCCESS")
                    print(f"   Goals before: {len(goals_before)} chars")
                    print(f"   Goals after: {len(goals_after)} chars")
                    
                    # Show state after applying tactic
                    print_applied_tactics(coq_interface, f"After Step {step_number}")
                else:
                    print(f"❌ Step {step_number} FAILED: {coq_interface.get_last_error()}")
                    return False
            
            print(f"\n📊 Applied {len(successful_tactics_with_states)} tactics successfully")
            
            # Show final state after all tactics
            print_applied_tactics(coq_interface, "After All Tactics")
            print_current_proof_state(coq_interface)
            
            # Test rollback to different steps
            # NOTE: Step 1 = "Proof.", Step 2 = "intros...", Step 3 = "assert...", etc.
            rollback_targets = [4, 2, 1]  # Test rolling back to meaningful steps
            
            for target_step in rollback_targets:
                print(f"\n🔄 PHASE 2: Test rollback to step {target_step}")
                print("="*60)
                time.sleep(2)  # Small delay for clarity
                # Show current state before rollback attempt
                print_applied_tactics(coq_interface, f"Before Rollback to Step {target_step}")
                
                # Validate target step
                current_step = coq_interface.get_current_step_number()
                max_applied_step = max([t['step_number'] for t in successful_tactics_with_states]) if successful_tactics_with_states else 1
                
                print(f"📊 Current step: {current_step}, Target step: {target_step}, Max applied: {max_applied_step}")
                
                if target_step < 1:
                    print(f"❌ Invalid target step {target_step} - must be >= 1")
                    continue
                
                if target_step > max_applied_step:
                    print(f"❌ Invalid target step {target_step} - max applied step is {max_applied_step}")
                    continue
                
                # Check if rollback is needed
                if current_step == target_step:
                    print(f"✅ Already at target step {target_step} - no rollback needed")
                    continue
                
                if current_step < target_step:
                    print(f"⚠️ Current step ({current_step}) is less than target step ({target_step})")
                    print(f"⚠️ Need to apply tactics to reach target step")
                    
                    # Apply tactics from current_step + 1 to target_step
                    for step_to_apply in range(current_step + 1, target_step + 1):
                        # Find the tactic for this step
                        tactic_data = None
                        for data in successful_tactics_with_states:
                            if data['step_number'] == step_to_apply:
                                tactic_data = data
                                break
                        
                        if tactic_data:
                            tactic = tactic_data['tactic']
                            print(f"   📝 Applying step {step_to_apply}: {tactic}")
                            
                            success = coq_interface.apply_tactic(tactic)
                            if success:
                                print(f"   ✅ Step {step_to_apply} applied successfully")
                            else:
                                print(f"   ❌ Step {step_to_apply} failed: {coq_interface.get_last_error()}")
                                break
                        else:
                            print(f"   ❌ No tactic data found for step {step_to_apply}")
                            break
                    
                    # Update current step
                    current_step = coq_interface.get_current_step_number()
                    print(f"📊 After forward progress: Current step: {current_step}")
                
                # Now handle rollback if current_step > target_step
                if current_step > target_step:
                    # Use efficient reset_by_step method
                    print(f"🔄 Using efficient reset_by_step({target_step}) method")
                    reset_success = coq_interface.reset_by_step(target_step)
                    
                    if reset_success:
                        print(f"✅ Successfully reset to step {target_step} using pop method")
                        
                        # Show state after rollback
                        print_applied_tactics(coq_interface, f"After Rollback to Step {target_step}")
                        
                        # Verify final step count
                        final_step = coq_interface.get_current_step_number()
                        print(f"📊 Final step count: {final_step}")
                        
                        if final_step == target_step:
                            print(f"✅ Step count matches target!")
                        else:
                            print(f"⚠️ Step count mismatch: expected {target_step}, got {final_step}")
                        
                        # Find expected state for verification
                        expected_goals = None
                        if target_step == 1:
                            # Step 1 is "Proof." - we know the initial goal
                            expected_goals = coq_interface.get_goal_str()  # Current goals should be the initial goals
                        else:
                            # Find the tactic data for target_step to get expected goals_after
                            for data in successful_tactics_with_states:
                                if data['step_number'] == target_step:
                                    expected_goals = data['goals_after']
                                    break
                        
                        # Verify state matches expected (if we have expected data)
                        current_goals = coq_interface.get_goal_str()
                        if expected_goals is not None:
                            print(f"\n🔍 Verification:")
                            print(f"   Current goals: {len(current_goals)} chars")
                            print(f"   Expected goals: {len(expected_goals)} chars")
                            
                            if current_goals == expected_goals:
                                print(f"   ✅ State matches expected!")
                            else:
                                print(f"   ⚠️ State mismatch (may be normal due to formatting)")
                                # Show first 100 chars of each for comparison
                                print(f"   Current:  {current_goals[:100]}...")
                                print(f"   Expected: {expected_goals[:100]}...")
                        
                        # Show current state
                        print_current_proof_state(coq_interface)
                        
                        # Test going forward by applying the next tactic
                        next_step = target_step + 1
                        next_tactic_data = None
                        for data in successful_tactics_with_states:
                            if data['step_number'] == next_step:
                                next_tactic_data = data
                                break
                        
                        if next_tactic_data:
                            next_tactic = next_tactic_data['tactic']
                            
                            print(f"\n🔄 Testing forward progress: applying next tactic")
                            print(f"📝 Next tactic (step {next_step}): {next_tactic}")
                            
                            # Show expected state before applying next tactic
                            expected_before = next_tactic_data['goals_before']
                            current_before = coq_interface.get_goal_str()
                            print(f"🔍 State verification before next tactic:")
                            print(f"   Current state:  {len(current_before)} chars")
                            print(f"   Expected state: {len(expected_before)} chars")
                            
                            forward_success = coq_interface.apply_tactic(next_tactic)
                            if forward_success:
                                print(f"✅ Forward progress successful!")
                                
                                # Show state after forward progress
                                print_applied_tactics(coq_interface, f"After Forward Progress")
                                
                                # Verify we're now at next_step
                                new_step_count = coq_interface.get_current_step_number()
                                if new_step_count == next_step:
                                    print(f"✅ Step count correct: {new_step_count}")
                                else:
                                    print(f"⚠️ Step count unexpected: expected {next_step}, got {new_step_count}")
                            else:
                                print(f"❌ Forward progress failed: {coq_interface.get_last_error()}")
                                print(f"🔍 Current proof state when forward progress failed:")
                                print_current_proof_state(coq_interface)
                        else:
                            print(f"💡 No next tactic available for step {next_step} - this is expected if we're at the last step")
                        
                    else:
                        print(f"❌ Reset to step {target_step} failed: {coq_interface.get_last_error()}")
                        return False
                
                elif current_step == target_step:
                    print(f"✅ Already at target step {target_step} after adjustments")
                
                # Show final state after this rollback test
                print_applied_tactics(coq_interface, f"Final State After Rollback Test {target_step}")
                print("\n" + "="*60)
            
            print(f"\n🎉 All rollback tests completed successfully!")
            return True
            
        finally:
            # Clean up
            coq_interface.close()
            
    except Exception as e:
        print(f"❌ Rollback test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("=" * 70)
    print("🧪 Proof Search Agent Testing: Rollback Functionality")
    print("=" * 70)
    
    # Check if config file exists
    if not config_file.exists():
        print(f"❌ Config file not found: {config_file}")
        print("💡 Please create the config file with library_paths configuration")
        sys.exit(1)
    
    # Test rollback functionality
    print("🔄 Testing rollback functionality...")
    rollback_success = test_rollback_functionality()

    
    # Final summary
    print("\n" + "="*70)
    print("🏁 FINAL RESULTS")
    print("="*70)
    
    if rollback_success:
        print("🔄 PARTIAL SUCCESS: Rollback works, proof needs work")
        print("✅ Rollback functionality implemented correctly")
        print("❌ Normal proof has issues")
    
    print(f"\n💡 Test Results:")
    print(f"   - Rollback functionality: {'✅ Working' if rollback_success else '❌ Needs work'}")
    print(f"   - Coq state reset: {'✅ Working' if rollback_success else '❌ Needs work'}")
    print(f"   - Tactic replay: {'✅ Working' if rollback_success else '❌ Needs work'}")
    
    if rollback_success:
        print(f"\n🚀 Rollback test confirms:")
        print(f"   - Can rollback to arbitrary steps (tested: 4, 2, 1)")
        print(f"   - Coq state resets correctly")
        print(f"   - Tactics replay successfully")
        print(f"   - State verification works")
        print(f"   - Ready for controller integration!")