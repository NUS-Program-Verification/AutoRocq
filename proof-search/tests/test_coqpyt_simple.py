import sys
from pathlib import Path

# Add the current directory to path to import coqpyt
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from coqpyt.coq.proof_file import ProofFile
from coqpyt.coq.exceptions import InvalidChangeException
from tests.test_utils import reset_coq_file_to_admitted, restore_coq_file_from_backup, get_example_file


def test_simple_tactics():
    """Simple test focusing on proof states using context manager for proper cleanup."""
    
    file_path = get_example_file()
    print(f"Loading file: {file_path}")
    
    # Reset the file to have an unproven proof (Proof. Admitted.)
    if not reset_coq_file_to_admitted(file_path, backup=True):
        print("WARNING: Could not reset file to Admitted state")
    
    try:
        # Use context manager to ensure proper cleanup
        with ProofFile(str(file_path), timeout=60) as proof_file:
            print("Loading file")
            
            proof_file.run()
            
            if proof_file.proofs:
                for i, p in enumerate(proof_file.proofs):
                    status = "unproven" if p in proof_file.unproven_proofs else "proven"
                    print(f"  Proof {i}: {p.text[:50]}... [{status}], {len(p.steps)} steps")
            
            # Get unproven proof
            if not proof_file.unproven_proofs:
                if not proof_file.proofs:
                    print("ERROR: No proofs at all in file!")
                    return False
                # Use first proof
                unproven = proof_file.proofs[0]
            else:
                unproven = proof_file.unproven_proofs[0]
            
            print(f"Working on proof with {len(unproven.steps)} step(s)")
            
            # Remove Admitted/Qed if present
            while unproven.steps and unproven.steps[-1].text.strip() in ["Admitted.", "Qed."]:
                print(f"Removing: {unproven.steps[-1].text.strip()}")
                proof_file.pop_step(unproven)
            
            # Show initial state
            print(f"\nInitial state: {len(unproven.steps)} step(s)")
            try:
                goals = proof_file.current_goals
                print(f"Goals: {goals}")
            except Exception as e:
                print(f"Could not get goals: {e}")
            
            # Test tactics
            tactics = ["  intros b.", "  destruct b.", "  simpl.", "  reflexivity."]
            
            successful = 0
            for i, tactic in enumerate(tactics, 1):
                print(f"\n[Step {i}] Applying: {tactic.strip()}")
                
                steps_before = len(unproven.steps)
                
                # Apply tactic
                try:
                    proof_file.append_step(unproven, tactic)
                    steps_after = len(unproven.steps)
                    
                    if steps_after > steps_before:
                        print(f"  OK (steps: {steps_before} -> {steps_after})")
                        successful += 1
                        
                    # Check goals
                    try:
                        goals = proof_file.current_goals
                        goals_str = str(goals) if goals else ""
                        if not goals_str.strip() or "No more goals" in goals_str:
                            print("  No more goals!")
                            break
                    except:
                        pass
                            
                except InvalidChangeException as e:
                    print(f"  INVALID: {e}")
                    break
                except Exception as e:
                    print(f"❌ Error: {e}")
                    break
            
            # Try Qed
            try:
                proof_file.append_step(unproven, "Qed.")
                print("\nApplied Qed. - PROOF COMPLETE!")
                successful += 1
            except Exception as e:
                print(f"\nCould not apply Qed: {e}")
            
            # Summary
            print(f"\n{'='*50}")
            print(f"RESULT: {successful} tactics applied, {len(unproven.steps)} steps")
            print(f"{'='*50}")
            
            return successful > 0
    
    finally:
        # Restore original file
        restore_coq_file_from_backup(file_path)


if __name__ == "__main__":
    print("=" * 60)
    print("CoqPyt Simple Tactics Test")
    print("=" * 60)
    
    try:
        success = test_simple_tactics()
        
        print("\n" + "=" * 60)
        print("TEST PASSED" if success else "TEST FAILED")
        print("=" * 60)
        
        sys.exit(0 if success else 1)
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
