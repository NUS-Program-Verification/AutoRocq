import os
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.coq_interface import CoqInterface
from utils.config import ProofAgentConfig

# --- CONFIGURATION ---
coq_file = PROJECT_ROOT / "examples" / "main_loop_invariant_2_established_Coq.v"
config_file = PROJECT_ROOT / "configs" / "default_config.json"

def test_intros_tactic():
    """Test how intros. tactic affects subgoals and goals"""
    print("🔍 Testing intros. tactic effects on subgoals and goals...")
    
    try:
        # Load configuration from file
        config = ProofAgentConfig.from_file(str(config_file))
        print(f"✅ Loaded configuration from {config_file}")
        
        # Initialize CoqInterface using configuration
        coq_interface = CoqInterface(
            file_path=str(coq_file),
            workspace=config.coq.workspace or str(coq_file.parent),
            library_paths=config.coq.library_paths,
            auto_setup_coqproject=config.coq.auto_setup_coqproject,
            coqproject_extra_options=config.coq.coqproject_extra_options,
            timeout=config.coq.timeout
        )
        
        try:
            print("✅ Created CoqInterface")
            
            # Load the file
            success = coq_interface.load()
            if not success:
                print(f"❌ Failed to load file: {coq_interface.get_last_error()}")
                return False
            
            print("✅ File loaded successfully")

            # Get proof status
            status = coq_interface.get_proof_status()
            print(f"\n📊 Proof status: loaded={status.get('has_proof')}, steps={status.get('proof_steps')}")
            
            if not status.get("has_proof", False):
                print("❌ No proof loaded")
                return False
            
            # Clear existing proof steps to start fresh
            print("\n🔄 Clearing existing proof steps...")
            if not coq_interface.clear_unproven_proof_steps():
                print("❌ Failed to clear proof steps")
                return False
            
            print("✅ Proof steps cleared")
            
            # Verify the proof is clean - should only have "Proof." step
            if coq_interface.proof and coq_interface.proof.steps:
                step_count = len(coq_interface.proof.steps)
                print(f"📊 Proof steps after clearing: {step_count}")
                if step_count == 1:
                    first_step = coq_interface.proof.steps[0].text.strip()
                    print(f"   First step: '{first_step}'")
                    if first_step == "Proof.":
                        print("✅ Proof is clean - only contains 'Proof.'")
                    else:
                        print(f"⚠️  Warning: First step is not 'Proof.': '{first_step}'")
                else:
                    print(f"⚠️  Warning: Expected 1 step (Proof.), but found {step_count} steps")
                    for i, step in enumerate(coq_interface.proof.steps):
                        print(f"   Step {i+1}: {step.text.strip()}")
            else:
                print("⚠️  Warning: No proof steps found after clearing")
            
            # Show initial state BEFORE intros
            print("\n" + "="*80)
            print("📊 STATE BEFORE APPLYING intros.")
            print("="*80)
            
            subgoals_before = coq_interface.get_subgoals()
            goals_before = coq_interface.get_goal_str()
            hypotheses_before = coq_interface.get_hypothesis()
            
            print(f"\n🎯 Goals (raw string):")
            print(goals_before)
            print(f"\n🔍 Hypotheses:")
            print(hypotheses_before if hypotheses_before else "(None)")
            print(f"\n📋 Subgoals (structured list, {len(subgoals_before)} total):")
            for i, subgoal in enumerate(subgoals_before):
                print(f"\n  Subgoal {i+1}:")
                if hasattr(subgoal, 'ty'):
                    print(f"    Goal Type: {subgoal.ty}")
                    if hasattr(subgoal, 'hyps') and subgoal.hyps:
                        print(f"    Hypotheses ({len(subgoal.hyps)}):")
                        for hyp in subgoal.hyps:
                            names = ', '.join(hyp.names) if hasattr(hyp, 'names') else '?'
                            ty = hyp.ty if hasattr(hyp, 'ty') else '?'
                            print(f"      {names} : {ty}")
                    else:
                        print(f"    Hypotheses: (None)")
                else:
                    print(f"    {subgoal}")
            
            # Apply intros. tactic
            print("\n" + "="*80)
            print("⚡ APPLYING TACTIC: intros.")
            print("="*80)
            
            success = coq_interface.apply_tactic("intros.")
            if not success:
                error = coq_interface.get_last_error()
                print(f"❌ Failed to apply intros.: {error}")
                return False
            
            print("✅ intros. applied successfully")
            
            # Show state AFTER intros
            print("\n" + "="*80)
            print("📊 STATE AFTER APPLYING intros.")
            print("="*80)
            
            subgoals_after = coq_interface.get_subgoals()
            goals_after = coq_interface.get_goal_str()
            hypotheses_after = coq_interface.get_hypothesis()
            
            print(f"\n🎯 Goals (raw string):")
            print(goals_after)
            print(f"\n🔍 Hypotheses:")
            print(hypotheses_after if hypotheses_after else "(None)")
            print(f"\n📋 Subgoals (structured list, {len(subgoals_after)} total):")
            for i, subgoal in enumerate(subgoals_after):
                print(f"\n  Subgoal {i+1}:")
                if hasattr(subgoal, 'ty'):
                    print(f"    Goal Type: {subgoal.ty}")
                    if hasattr(subgoal, 'hyps') and subgoal.hyps:
                        print(f"    Hypotheses ({len(subgoal.hyps)}):")
                        for hyp in subgoal.hyps:
                            names = ', '.join(hyp.names) if hasattr(hyp, 'names') else '?'
                            ty = hyp.ty if hasattr(hyp, 'ty') else '?'
                            print(f"      {names} : {ty}")
                    else:
                        print(f"    Hypotheses: (None)")
                else:
                    print(f"    {subgoal}")
            
            # Compare and analyze changes
            print("\n" + "="*80)
            print("🔍 COMPARISON: BEFORE vs AFTER")
            print("="*80)
            
            # Compare goal strings
            print("\n📋 COMPARISON 1: Goal Strings (get_goal_str())")
            print("-" * 80)
            goals_before_clean = str(goals_before).strip()
            goals_after_clean = str(goals_after).strip()
            print(f"BEFORE ({len(goals_before_clean)} chars):\n{goals_before_clean}\n")
            print(f"AFTER ({len(goals_after_clean)} chars):\n{goals_after_clean}\n")
            if goals_before_clean == goals_after_clean:
                print("❌ RESULT: Goals strings are IDENTICAL")
            else:
                print("✅ RESULT: Goals strings are DIFFERENT")
            
            # Compare subgoals structure
            print("\n" + "-" * 80)
            print("📋 COMPARISON 2: Subgoals Structure (get_subgoals())")
            print("-" * 80)
            print(f"Number of subgoals: {len(subgoals_before)} → {len(subgoals_after)}")
            
            if len(subgoals_before) > 0 and len(subgoals_after) > 0:
                subgoal_before = subgoals_before[0]
                subgoal_after = subgoals_after[0]
                
                # Compare goal types
                if hasattr(subgoal_before, 'ty') and hasattr(subgoal_after, 'ty'):
                    ty_before = str(subgoal_before.ty).strip()
                    ty_after = str(subgoal_after.ty).strip()
                    
                    print(f"\nSubgoal Goal Type:")
                    print(f"  BEFORE ({len(ty_before)} chars):")
                    print(f"    {ty_before}")
                    print(f"  AFTER ({len(ty_after)} chars):")
                    print(f"    {ty_after}")
                    
                    if ty_before == ty_after:
                        print("  ❌ RESULT: Goal types are IDENTICAL")
                    else:
                        print("  ✅ RESULT: Goal types are DIFFERENT")
                
                # Compare hypotheses count
                hyps_before = len(subgoal_before.hyps) if hasattr(subgoal_before, 'hyps') and subgoal_before.hyps else 0
                hyps_after = len(subgoal_after.hyps) if hasattr(subgoal_after, 'hyps') and subgoal_after.hyps else 0
                print(f"\nHypotheses count: {hyps_before} → {hyps_after}")
                
                if hyps_after > hyps_before:
                    print(f"  ✅ RESULT: Added {hyps_after - hyps_before} new hypotheses")
                    if hasattr(subgoal_after, 'hyps') and subgoal_after.hyps:
                        print(f"  New hypotheses:")
                        for hyp in subgoal_after.hyps[hyps_before:]:
                            names = ', '.join(hyp.names) if hasattr(hyp, 'names') else '?'
                            ty = hyp.ty if hasattr(hyp, 'ty') else '?'
                            print(f"    {names} : {ty}")
                elif hyps_after == hyps_before:
                    print(f"  ❌ RESULT: Hypotheses count is UNCHANGED")
                else:
                    print(f"  ⚠️  RESULT: Hypotheses count DECREASED (unexpected)")
            else:
                print("⚠️  Cannot compare: missing subgoals")
            
            print("\n" + "="*80)
            print("✅ TEST COMPLETED")
            print("="*80)
            
            return True
        
        finally:
            # Always clean up
            coq_interface.close()
            
    except Exception as e:
        print(f"❌ Testing failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("=" * 80)
    print("🧪 Subgoals and Goals Change Tester (intros. tactic)")
    print("=" * 80)
    print(f"📄 File: {coq_file}")
    print(f"⚙️ Config: {config_file}")
    print("=" * 80)
    
    # Check if files exist
    if not config_file.exists():
        print(f"❌ Config file not found: {config_file}")
        sys.exit(1)
    
    if not coq_file.exists():
        print(f"❌ Proof file not found: {coq_file}")
        sys.exit(1)
    
    # Run the test
    success = test_intros_tactic()
    
    # Final summary
    print("\n" + "="*80)
    print("🏁 SUMMARY")
    print("="*80)
    
    if success:
        print("✅ Test executed successfully - check output above for changes")
    else:
        print("❌ Test failed")
    
