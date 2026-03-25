#!/usr/bin/env python3
"""
Simple test script to check if three tactics can prove the goal.
"""

import sys
import logging
from pathlib import Path

# Add the parent directory to Python path
sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.coq_interface import CoqInterface
from utils.logger import setup_logger

def test_three_tactics():
    """Test if simpl., simpl., reflexivity. can prove the goal."""
    
    # Setup simple logging
    logger = setup_logger("test", level="INFO", console_output=True)
    
    # File path relative to project root
    file_path = str(Path(__file__).parent.parent / "examples" / "example.v")
    
    try:
        # Load the Coq file
        coq = CoqInterface(file_path)
        coq.load()
        
        # Clear existing tactics
        coq.clear_unproven_proof_steps()
        
        # Show initial goal
        initial_goals = coq.get_goal_str()
        print(f"Initial goal: {initial_goals}")
        
        # Apply the three tactics
        tactics = ["simpl.", "simpl.", "reflexivity."]
        tactics = ["intros n m.", "intros.", "simpl.", "reflexivity.", "reflexivity."]
        tactics = [" intros b.", " destruct b.", " simpl.", " reflexivity.", " simpl.", " reflexivity."]
        
        for i, tactic in enumerate(tactics, 1):
            print(f"\n{'='*60}")
            print(f"Step {i}: Applying {tactic}")
            print(f"{'='*60}")
            
            success = coq.apply_tactic(tactic)
            print(f"Goal after tactic: {coq.get_goal_str()}")
            
            if success:
                # Get comprehensive status using the new method
                status = coq.get_proof_completion_status()
                
                print(f"  ✅ Success!")
                print(f"  📋 Goals: '{status['current_goals']}'")
                print(f"  🔍 is_complete: {status['is_complete']}")
                print(f"  🎯 ready_for_qed: {status['ready_for_qed']}")
                
                if status['ready_for_qed']:
                    print(f"  🎉 PROOF READY FOR QED after step {i}!")
                    return True
                else:
                    print(f"  ⏳ Proof not yet ready, continuing...")
                    
            else:
                error = coq.get_last_error() or "Unknown error"
                print(f"  ❌ Failed: {error}")
                return False
        
        # Final comprehensive check using the new method
        print(f"\n{'='*60}")
        print(f"FINAL STATUS AFTER ALL 3 TACTICS")
        print(f"{'='*60}")
        
        final_status = coq.get_proof_completion_status()
        
        print(f"Final status: {final_status}")
        
        if final_status['ready_for_qed']:
            assert final_status['qed_already_applied']
            return True
        else:
            return False
        
    except Exception as e:
        print(f"Error: {e}")
        return False
    
    finally:
        try:
            coq.close()
        except:
            pass

if __name__ == "__main__":
    print("Testing if three tactics can prove the goal...")
    print("=" * 50)
    
    success = test_three_tactics()
    
    print("=" * 50)
    if success:
        print("🎉 SUCCESS: The three tactics proved the goal!")
        sys.exit(0)
    else:
        print("❌ FAILED: The three tactics did not prove the goal")
        sys.exit(1)