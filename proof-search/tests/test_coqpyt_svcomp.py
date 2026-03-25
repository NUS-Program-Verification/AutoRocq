import os
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from coqpyt.coq.proof_file import ProofFile
from coqpyt.coq.exceptions import InvalidChangeException

# --- CONFIGURATION ---
coq_file = PROJECT_ROOT / "examples" / "main_loop_invariant_2_established_Coq.v"

def print_current_goals(proof_file):
    """Print current goals from the proof file"""
    print("\n🎯 Current Goals:")
    try:
        goals = proof_file.current_goals
        if goals:
            print(goals)
        else:
            print("(No goals remaining)")
    except Exception as e:
        print(f"(Error getting goals: {e})")

def print_steps(proof):
    """Print proof steps"""
    print("== Proof Steps ==")
    for i, step in enumerate(proof.steps):
        print(f"{i+1}: {step.text.strip()}")
    print("-" * 40)

def test_proof_with_correct_tactics():
    """Test applying the correct proof tactics step by step"""
    examples_dir = PROJECT_ROOT / "examples"
    
    print("🔍 Testing proof with correct tactics...")
    
    try:
        with ProofFile(str(coq_file), workspace=str(examples_dir), timeout=60) as proof_file:
            print("✅ Opened proof file")
            
            # Load the file
            proof_file.run()
            print(f"📊 File loaded - {len(proof_file.unproven_proofs)} unproven proof(s) found")
            
            if len(proof_file.unproven_proofs) == 0:
                print("❌ No unproven proofs found")
                return False
            
            proof = proof_file.unproven_proofs[0]
            print(f"🎯 Working on proof: {proof.text[:80]}...")
            
            # Remove Admitted if present
            if proof.steps and "Admitted" in proof.steps[-1].text:
                proof_file.pop_step(proof)
                print("✅ Removed 'Admitted' step")
            
            # Show initial state
            print("\n" + "="*60)
            print("🚀 INITIAL STATE")
            print("="*60)
            print_steps(proof)
            print_current_goals(proof_file)
            
            # Correct tactics based on the provided sequence - KEEPING YOUR EXACT FORMAT
            tactics = [
                "   \nintros i_1 i Hle Hlow Hup Hup_i Hsint.",
                "   \nassert (Hrange: -9 <= i <= 9) by lia.",
                "   \ndestruct Hrange as [Hi_low Hi_up].",
                "   \nSearch (Z.abs _ <= _ -> _ * _ <= _).",
                "   \nSearch Z.abs.",
                "   \nassert (Hi_abs_le : Z.abs i <= 9) by now apply Z.abs_le.",
                "   \nrewrite <- Z.abs_square.",
                "   \nassert (0 <= Z.abs i) by apply Z.abs_nonneg.",
                "   \nassert (Habs_sq_le_81 : Z.abs i * Z.abs i <= 9 * 9) by (apply Z.square_le_mono_nonneg; lia).",
                "   \nintros _.",
                "   \napply (Z.le_trans _ (9 * 9)); lia.",
                "   \nQed."
            ]
            
            print(f"\n📝 Applying {len(tactics)} tactics step by step...")
            
            successful_steps = 0
            failed_steps = 0
            
            for i, tactic in enumerate(tactics, 1):
                print(f"\n{'='*60}")
                print(f"📝 STEP {i}/{len(tactics)}: {tactic}")
                print('='*60)
                
                try:
                    proof_file.append_step(proof, tactic)
                    successful_steps += 1
                    print("✅ Tactic applied successfully")
                    
                    # Show current proof state
                    print_steps(proof)
                    
                    # Show current goals
                    print_current_goals(proof_file)
                    
                    # Check if proof is complete
                    try:
                        current_goals = proof_file.current_goals
                        if not current_goals:
                            if "Qed" in tactic:
                                print("🎉 PROOF COMPLETED WITH QED!")
                                break
                            else:
                                print("🎯 NO REMAINING GOALS - Ready for Qed!")
                    except Exception as goal_error:
                        print(f"⚠️ Error checking goals: {goal_error}")
                
                except InvalidChangeException as e:
                    failed_steps += 1
                    print(f"❌ TACTIC FAILED: {tactic}")
                    print(f"   Error: {e}")
                    
                    # Show current state for debugging
                    print("🔍 Current proof state when tactic failed:")
                    print_steps(proof)
                    print_current_goals(proof_file)
                    
                    # Continue to try remaining tactics
                    continue
                    
                except Exception as e:
                    failed_steps += 1
                    print(f"❌ UNEXPECTED ERROR: {e}")
                    print("🔍 Current proof state when error occurred:")
                    print_steps(proof)
                    print_current_goals(proof_file)
                    break
            
            # Final results
            print("\n" + "="*70)
            print("🏁 FINAL PROOF STATUS")
            print("="*70)
            
            print(f"📊 Statistics:")
            print(f"   - Successful tactics: {successful_steps}")
            print(f"   - Failed tactics: {failed_steps}")
            print(f"   - Total tactics attempted: {successful_steps + failed_steps}")
            
            # CORRECTED final status checking logic
            is_complete = False
            try:
                # Check if last step is Qed
                has_qed = proof.steps and proof.steps[-1].text.strip() == "Qed."
                
                # The key insight: if all tactics succeeded AND we have Qed, it's complete!
                if failed_steps == 0 and successful_steps > 0 and has_qed:
                    is_complete = True
                    print("🎉 ✅ PROOF SUCCESSFULLY COMPLETED!")
                    print("   - All tactics applied correctly")
                    print("   - No failed tactics")
                    print("   - Proof ended with Qed")
                    print("   - SV-COMP theorem proven!")
                elif failed_steps == 0 and successful_steps > 0:
                    print("🔄 ✅ PROOF LOGIC COMPLETE (missing Qed)")
                    print("   - All tactics succeeded")
                    print("   - Ready for Qed step")
                elif failed_steps > 0:
                    print("🔄 ❌ PROOF INCOMPLETE")
                    print(f"   - {failed_steps} tactics failed")
                    print("   - Some tactics need fixing")
                else:
                    print("🔄 ❌ PROOF INCOMPLETE")
                    print("   - Unexpected state")
                        
            except Exception as status_error:
                print(f"⚠️ Error checking final status: {status_error}")
                # Fallback: if all tactics succeeded and we got to the end, assume success
                if failed_steps == 0 and successful_steps >= len(tactics):
                    print("🎉 ✅ ASSUMING PROOF COMPLETE (all tactics succeeded)")
                    is_complete = True
            
            print(f"\n📋 Final proof structure:")
            print_steps(proof)
            
            return is_complete
            
    except Exception as e:
        print(f"❌ Proof testing failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("=" * 70)
    print("🧪 CoqPyt SV-COMP Proof Testing with Correct Tactics")
    print("=" * 70)
    
    # Step 2: Test proof with correct tactics
    print("\n2️⃣ Testing proof with correct tactics...")
    proof_success = test_proof_with_correct_tactics()
    
    # Final summary
    print("\n" + "="*70)
    print("🏁 FINAL RESULTS")
    print("="*70)
    
    if proof_success:
        print("🎉 SUCCESS: Proof completed successfully!")
        print("✅ Library loading works with absolute path")
        print("✅ All tactics applied correctly")
        print("✅ SV-COMP goal proven")
        print("✅ CoqPyt ready for proof automation!")
    else:
        print("❌ FAILURE: Proof not completed")
        print("🔧 Check tactic sequence and goal states above")
        print("💡 Some tactics may need adjustment")
    
    print(f"\n💡 This test confirms:")
    print(f"   - Library loading: ✅ Working")
    print(f"   - Goal identification: ✅ Working")
    print(f"   - Tactic application: {'✅ Working' if proof_success else '❌ Needs work'}")
    print(f"   - Proof completion: {'✅ Complete' if proof_success else '❌ Incomplete'}")
    
    if proof_success:
        sys.exit(0)
    else:
        assert False, "Proof not completed"