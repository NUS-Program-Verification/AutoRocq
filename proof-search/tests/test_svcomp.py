import sys
from pathlib import Path

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

def print_steps(coq_interface):
    """Print proof steps using CoqInterface"""
    print("== Proof Steps ==")
    try:
        if coq_interface.proof and coq_interface.proof.steps:
            for i, step in enumerate(coq_interface.proof.steps):
                print(f"{i+1}: {step.text.strip()}")
        else:
            print("No steps available")
    except Exception as e:
        print(f"Error getting steps: {e}")
    print("-" * 40)

def clean_proof_file(file_path):
    """Clean the proof file using shared utility."""
    print("\n🧹 CLEANING PROOF FILE...")
    print("="*60)
    
    success = reset_coq_file_to_admitted(file_path, backup=True)
    if success:
        print("✅ File cleaned successfully - reset to 'Proof. Admitted.'")
    else:
        print("❌ Failed to clean file")
    return success

def test_proof_with_correct_tactics():
    """Test applying the correct proof tactics step by step using proof search agent APIs"""
    print("🔍 Testing proof with correct tactics using agent APIs...")
    
    try:
        # **CRITICAL: Clean the proof file first before loading**
        print("🧹 Step 1: Clean the proof file to remove any completed proof")
        clean_success = clean_proof_file(coq_file)
        if not clean_success:
            print("❌ Failed to clean proof file - cannot proceed")
            return False
        
        # Load configuration from file (this includes library_paths and auto_setup_coqproject)
        config = ProofAgentConfig.from_file(str(config_file))
        print(f"✅ Loaded configuration from {config_file}")
        print(f"📚 Library paths configured: {len(config.coq.library_paths)}")
        
        # Initialize CoqInterface using configuration (agent will auto-create _CoqProject)
        coq_interface = CoqInterface(
            file_path=str(coq_file),
            workspace=config.coq.workspace or str(coq_file.parent),
            library_paths=config.coq.library_paths,
            auto_setup_coqproject=config.coq.auto_setup_coqproject,
            coqproject_extra_options=config.coq.coqproject_extra_options,
            timeout=config.coq.timeout
        )
        
        try:
            print("✅ Created CoqInterface with auto-configured libraries")
            
            # Load the cleaned file using agent API
            success = coq_interface.load()
            if not success:
                print(f"❌ Failed to load cleaned file: {coq_interface.get_last_error()}")
                return False
            
            print("✅ Cleaned file loaded successfully")
            
            # Get proof status using agent API after loading cleaned file
            status = coq_interface.get_proof_status()
            print(f"📊 Proof status after cleaning: loaded={status.get('has_proof')}, steps={status.get('proof_steps')}")
            
            if not status.get("has_proof", False):
                print("❌ No proof loaded properly after cleaning")
                return False
            
            print(f"🎯 Working on clean proof with {status['proof_steps']} initial steps")
            
            # Show initial state after cleaning
            print("\n" + "="*60)
            print("🚀 INITIAL STATE (AFTER CLEANING)")
            print("="*60)
            print_steps(coq_interface)
            print_current_proof_state(coq_interface)  # Show both goals and hypotheses
            
            # Correct tactics based on the provided sequence - KEEPING YOUR EXACT FORMAT
            tactics = [
                "   \nintros i_1 i Hle Hlow Hup Hup_i Hsint.",
                "   \nassert (Hrange: -9 <= i <= 9) by lia.",
                "   \ndestruct Hrange as [Hi_low Hi_up].",
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
                print(f"📝 STEP {i}/{len(tactics)}: {tactic.strip()}")
                print('='*60)
                
                # Apply tactic using CoqInterface API
                success = coq_interface.apply_tactic(tactic)
                
                if success:
                    successful_steps += 1
                    print("✅ Tactic applied successfully")
                    
                    # Show current proof steps
                    print_steps(coq_interface)
                    
                    # Show COMPLETE proof state (hypotheses + goals) after tactic
                    print_current_proof_state(coq_interface)
                    
                    # Check if proof is complete using agent API
                    try:
                        goals_str = coq_interface.get_goal_str()
                        if goals_str == "No current goals" or not goals_str.strip():
                            if "Qed" in tactic:
                                print("🎉 PROOF COMPLETED WITH QED!")
                                break
                            else:
                                print("🎯 NO REMAINING GOALS - Ready for Qed!")
                    except Exception as goal_error:
                        print(f"⚠️ Error checking goals: {goal_error}")
                
                else:
                    failed_steps += 1
                    error_msg = coq_interface.get_last_error()
                    print(f"❌ TACTIC FAILED: {tactic.strip()}")
                    print(f"   Error: {error_msg}")
                    
                    # Show current state for debugging using agent APIs
                    print("🔍 Proof state when tactic failed:")
                    print_steps(coq_interface)
                    print_current_proof_state(coq_interface)  # Show both for debugging
                    
                    # Continue to try remaining tactics
                    continue
        
        finally:
            # Always clean up
            coq_interface.close()
            
    except Exception as e:
        print(f"❌ Proof testing failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("=" * 70)
    print("🧪 Proof Search Agent SV-COMP Testing (Config-Based with File Cleaning)")
    print("=" * 70)
    
    # Check if config file exists
    if not config_file.exists():
        print(f"❌ Config file not found: {config_file}")
        print("💡 Please create the config file with library_paths configuration")
        sys.exit(1)
    
    # Test proof with correct tactics using agent APIs and config
    print("🧪 Testing proof with agent APIs using config file...")
    test_proof_with_correct_tactics()