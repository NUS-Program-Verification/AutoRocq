import os
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.coq_interface import CoqInterface
from agent.context_manager import ContextManager
from agent.proof_controller import ProofController
from utils.config import ProofAgentConfig

# --- CONFIGURATION ---
coq_file = PROJECT_ROOT / "examples" / "main_loop_invariant_2_established_Coq.v"
config_file = PROJECT_ROOT / "configs" / "default_config.json"

def clean_proof_file(file_path):
    """Clean the proof file by removing everything after 'Proof.'"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        proof_pos = content.find("Proof.")
        if proof_pos == -1:
            print("❌ 'Proof.' not found in file")
            return False
        
        clean_content = content[:proof_pos + len("Proof.")] + "\n"
        
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(clean_content)
        
        print("✅ Proof file cleaned successfully")
        return True
        
    except Exception as e:
        print(f"❌ Error cleaning file: {e}")
        return False

def test_prove_theorem():
    """Test the prove_theorem API with controller"""
    print("\n🧪 TESTING PROVE_THEOREM API")
    print("=" * 50)
    
    try:
        # Clean the proof file first
        print("🧹 Step 1: Clean proof file")
        if not clean_proof_file(coq_file):
           return False
        
        # Load configuration
        print("📖 Step 2: Load configuration")
        config = ProofAgentConfig.from_file(str(config_file))
        print(f"✅ Configuration loaded")
        
        # Create CoqInterface
        print("🔧 Step 3: Create CoqInterface")
        coq_interface = CoqInterface(
            file_path=str(coq_file),
            workspace=config.coq.workspace or str(coq_file.parent),
            library_paths=config.coq.library_paths,
            auto_setup_coqproject=config.coq.auto_setup_coqproject,
            timeout=config.coq.timeout
        )
        
        try:
            # Load the file
            print("📂 Step 4: Load Coq file")
            if not coq_interface.load():
                print(f"❌ Failed to load file: {coq_interface.get_last_error()}")
                return False
            print("✅ Coq file loaded")
            
            # Create ContextManager
            print("🤖 Step 5: Create ContextManager")
            context_manager = ContextManager(
                coq_interface,
                api_key=config.llm.api_key,
                enable_history_context=getattr(config, "enable_history_context", True)
            )
            print("✅ ContextManager created")
            
            # Create controller with updated parameters
            print("🎮 Step 6: Create proof controller")
            controller = ProofController(
                coq_interface=coq_interface,
                context_manager=context_manager,
                max_steps=15,  # Enough steps for our sequence
                enable_context_search=False,  # Disable for simple test
            )
            print("✅ Controller created")
            
            # Show initial state
            print("\n📊 Initial proof state:")
            initial_goals = coq_interface.get_goal_str()
            print(f"   Goals: {initial_goals[:100]}...")
            
            # Use prove_theorem API
            print("\n🚀 Step 7: Call prove_theorem API")
            print("=" * 50)
            success = controller.prove_theorem("wp_goal")
            
            # Show results
            print("\n🏁 PROOF RESULTS")
            print("=" * 50)
            
            print(f"✅ Success: {success}")
            print(f"📊 Steps taken: {controller.step_count}/{controller.max_steps}")
            
            if controller.successful_tactics:
                print(f"✅ Successful tactics ({len(controller.successful_tactics)}):")
                for i, tactic in enumerate(controller.successful_tactics, 1):
                    print(f"   {i}. {tactic}")
            
            if controller.failed_tactics:
                print(f"❌ Failed tactics ({len(controller.failed_tactics)}):")
                for i, tactic in enumerate(controller.failed_tactics, 1):
                    print(f"   {i}. {tactic}")
            
            # Verify proof completion
            final_status = coq_interface.get_proof_completion_status()
            print(f"\n🎯 Final proof status:")
            print(f"   Complete: {final_status.get('is_complete', False)}")
            print(f"   Ready for Qed: {final_status.get('ready_for_qed', False)}")
            
            return success
            
        finally:
            coq_interface.close()
            
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("=" * 70)
    print("🧪 SIMPLE CONTROLLER PROVE_THEOREM TEST")
    print("=" * 70)
    
    # Check prerequisites
    if not coq_file.exists():
        print(f"❌ Coq file not found: {coq_file}")
        sys.exit(1)
        
    if not config_file.exists():
        print(f"❌ Config file not found: {config_file}")
        sys.exit(1)
    
    # Run the test
    success = test_prove_theorem()
    
    # Final summary
    print(f"\n{'='*70}")
    print("🏁 FINAL RESULTS")
    print(f"{'='*70}")
    
    if success:
        print("🎉 SUCCESS: prove_theorem API worked correctly!")
        print("✅ Controller orchestrated the proof successfully")
        print("✅ Theorem proven using controller architecture")
        print("\n💡 The controller.prove_theorem() API is working correctly!")
    else:
        print("❌ FAILURE: prove_theorem API test failed")
        print("🔧 Check the error messages above for details")
    
    print(f"\n🚀 Controller API Status: {'✅ WORKING' if success else '❌ NEEDS FIXING'}")
