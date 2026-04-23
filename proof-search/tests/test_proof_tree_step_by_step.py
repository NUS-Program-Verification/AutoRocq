#!/usr/bin/env python3
"""
Test script to visualize proof tree evolution step by step.
Uses ProofController._apply_tactic() which maintains the proof tree automatically.
"""

import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.coq_interface import CoqInterface
from agent.context_manager import ContextManager
from agent.proof_tree import ProofTree
from agent.proof_controller import ProofController
from utils.config import ProofAgentConfig
from tests.test_utils import reset_coq_file_to_admitted

# --- CONFIGURATION ---
coq_file = PROJECT_ROOT / "examples" / "hex2bin_assert_3.v"
config_file = PROJECT_ROOT / "configs" / "default_config.json"


def test_proof_tree_evolution():
    """
    Test proof tree visualization by applying tactics step by step
    using ProofController._apply_tactic() which maintains the proof tree automatically.
    """
    
    print("🧪 Testing Proof Tree Evolution Step by Step")
    print("=" * 80)
    print(f"📁 File: {coq_file}")
    print(f"📄 Config: {config_file}")
    print("=" * 80)
    
    # Create output directory for proof tree visualizations
    output_dir = PROJECT_ROOT / "examples" / "proof_tree_debug"
    output_dir.mkdir(exist_ok=True)
    print(f"📁 Proof tree PNGs will be saved to: {output_dir}")
    
    # Clean the file first
    print("\n🧹 Cleaning proof file...")
    if not reset_coq_file_to_admitted(coq_file, backup=True):
        print("❌ Failed to clean file")
        return False
    print("✅ File cleaned successfully")
    
    # Load configuration
    config = ProofAgentConfig.from_file(str(config_file))
    print(f"✅ Loaded configuration from {config_file}")
    
    # Create CoqInterface
    coq_interface = CoqInterface(
        file_path=str(coq_file),
        workspace=config.coq.workspace or str(coq_file.parent),
        library_paths=config.coq.library_paths,
        auto_setup_coqproject=config.coq.auto_setup_coqproject,
        timeout=config.coq.timeout
    )
    
    try:
        coq_interface.load()
        print("✅ CoqInterface loaded")
        
        # Create ContextManager
        context_manager = ContextManager(
            coq_interface=coq_interface,
            api_key=config.llm.api_key
        )
        print("✅ ContextManager created")
        
        # Create ProofController - this maintains the proof tree
        controller = ProofController(
            coq_interface=coq_interface,
            context_manager=context_manager,
            max_steps=100,
            enable_recording=False
        )
        print("✅ ProofController created")
        
        # Initialize proof controller
        controller.current_theorem_name = "hex2bin_assert_3"
        controller.step_count = 0
        controller.successful_tactics = []
        
        print(f"\n📋 Starting proof: {controller.current_theorem_name}")
        print("=" * 80)
        
        # Initialize proof tree
        controller.proof_tree = ProofTree()
        print("🌳 Initialized new ProofTree")

        # Add initial root node to the proof tree
        initial_goals = coq_interface.get_goal_str()
        if not controller.proof_tree.root:
            initial_hypotheses = coq_interface.get_hypothesis()
            controller.proof_tree.add_node(
                tactic="Proof.",
                goals_before=initial_goals.strip() if initial_goals else '',
                goals_after=initial_goals.strip() if initial_goals else '',
                hypotheses_before=initial_hypotheses.strip() if initial_hypotheses else '',
                hypotheses_after=initial_hypotheses.strip() if initial_hypotheses else '',
                step_number=0,
                subgoals_after=coq_interface.get_subgoals()
            )
        
        # Print initial proof tree
        print("\n" + "🌳" * 30)
        tree_string = controller.proof_tree.get_proof_tree_string()
        print(tree_string)
        print("🌳" * 30)
        
        # Save initial proof tree PNG using save_to_png
        png_path = str(output_dir / "proof_tree_step_0")
        controller.proof_tree.save_to_png(png_path, prefix="")
        print(f"💾 Saved initial proof tree PNG: {png_path}.png")
        
        # Define tactics to test
        tactics = [
            "intros t t1 t2 a i i1 i2 a1 a2.",
            "intros.",
            "assert (lor_disjoint_sum: forall x y:int, 0 <= x <= 15 -> (exists k:int, y = 16 * k) -> x + y = lor x y)",
            "{",
            "intros x0 y [Hx0_low Hx0_up] [k Hy_eq].",
            "subst y.",
            "rewrite Z.mul_comm.",
        ]
        
        for i, tactic in enumerate(tactics, 1):
            print(f"\n{'=' * 80}")
            print(f"📝 Step {i}: Applying tactic")
            print(f"   {tactic}")
            print('=' * 80)
            
            # Get state before for display
            subgoals_before = coq_interface.get_subgoals()
            goals_before = coq_interface.get_goal_str()
            hypotheses_before = coq_interface.get_hypothesis()
            
            print(f"\n📊 Before tactic:")
            print(f"   Subgoals count: {len(subgoals_before)}")
            
            # USE ProofController._apply_tactic()
            success = controller._apply_tactic(tactic)
            
            if not success:
                error = coq_interface.get_last_error()
                raise Exception(f"\n❌ Tactic failed: {error}")
            
            # Get state after for display
            subgoals_after = coq_interface.get_subgoals()
            goals_after = coq_interface.get_goal_str()
            hypotheses_after = coq_interface.get_hypothesis()
            
            print(f"\n✅ Tactic applied successfully!")
            print(f"📊 After tactic:")
            print(f"   Subgoals count: {len(subgoals_after)}")
            print(f"   Change: {len(subgoals_before)} → {len(subgoals_after)}")
            
            # Set global step id for the proof tree
            controller.global_step_id = i
            # _handle_successful_tactic updates proof tree
            tactic_with_state = controller._handle_successful_tactic(
                tactic,
                subgoals_before,
                subgoals_after,
                goals_before,
                goals_after,
                hypotheses_before,
                hypotheses_after
            )
            
            # Print the proof tree using get_proof_tree_string()
            print("\n" + "🌳" * 30)
            tree_string = controller.proof_tree.get_proof_tree_string()
            print(tree_string)
            print("🌳" * 30)
            
            # Save proof tree PNG using save_to_png
            png_path = str(output_dir / f"proof_tree_step_{i}")
            controller.proof_tree.save_to_png(png_path, prefix="")
            print(f"\n💾 Saved proof tree PNG: {png_path}.png")
        
        # Print final statistics
        print("\n" + "=" * 80)
        print("📊 Final Proof Tree Statistics:")
        print("=" * 80)
        tree_dict = controller.proof_tree.to_dict()
        if 'metadata' in tree_dict:
            metadata = tree_dict['metadata']
            print(f"   Open subgoals: {metadata.get('open_subgoals_count', 0)}")
            print(f"   Total steps applied: {controller.step_count}")
        
        # Print final full tree
        print("\n" + "=" * 80)
        print("🌳 FINAL PROOF TREE:")
        print("=" * 80)
        final_tree = controller.proof_tree.get_proof_tree_string()
        print(final_tree)
        
        # Save final proof tree PNG
        final_png_path = str(output_dir / "proof_tree_final")
        controller.proof_tree.save_to_png(final_png_path, prefix="hex2bin_assert_3_")
        print(f"\n💾 Saved final proof tree PNG: {final_png_path}.png")
        
        print("\n🎉 Test completed successfully!")
        return True
        
    except Exception as e:
        print(f"\n❌ Test failed with exception: {e}")
        import traceback
        traceback.print_exc()
        return False
        
    finally:
        coq_interface.close()
        print("\n✅ CoqInterface closed")


if __name__ == "__main__":
    print("🚀 Proof Tree Step-by-Step Visualization Test")
    print("   Using ProofController._apply_tactic() to maintain proof tree")
    print("=" * 80)
    
    success = test_proof_tree_evolution()
    
    print("\n" + "=" * 80)
    if success:
        print("🎉 TEST PASSED!")
        print("✅ Examined all tactics successfully")
        print("✅ Proof tree maintained automatically by ProofController._apply_tactic()")
        print("✅ Check examples/proof_tree_debug/ for PNG visualizations")
    else:
        print("❌ TEST FAILED!")
    
    print("=" * 80)
    
    sys.exit(0 if success else 1)