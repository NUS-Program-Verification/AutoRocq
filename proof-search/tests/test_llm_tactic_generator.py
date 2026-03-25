import os
import sys
from pathlib import Path

# Add the parent directory to Python path so we can import backend modules
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.coq_interface import CoqInterface
from agent.context_manager import ContextManager
from utils.config import ProofAgentConfig
from utils.coq_utils import find_transitive_dependencies

# --- CONFIGURATION ---
coq_file = PROJECT_ROOT / "examples" / "example.v"
config_file = PROJECT_ROOT / "configs" / "default_config.json"

def test_context_manager_initialization(config):
    """Simple test of the ContextManager initialization."""
    print("🧪 Testing ContextManager initialization...")
    
    if not coq_file.exists():
        print(f"Error: Example file not found at {coq_file}")
        return False
    
    # Create a CoqInterface instance first
    coq = CoqInterface(str(coq_file))
    coq.load()
    
    try:
        # Instantiate ContextManager with the required coq_interface argument
        cm = ContextManager(coq, api_key=config.llm.api_key)

        # Check that the ContextManager has the expected attributes
        checks = {
            "Has chat_session": hasattr(cm, 'chat_session') and cm.chat_session is not None,
            "Has tactic_history": hasattr(cm, 'tactic_history') and cm.tactic_history is not None,
            "Has model": hasattr(cm, 'model') and cm.model is not None,
            "Has coq interface": hasattr(cm, 'coq') and cm.coq is not None,
        }
        
        all_passed = True
        for check_name, result in checks.items():
            status = "✅" if result else "❌"
            print(f"   {status} {check_name}")
            if not result:
                all_passed = False
        
        if all_passed:
            print(f"✅ ContextManager initialized successfully with model: {cm.model}")
            return True
        else:
            print("❌ ContextManager initialization failed some checks")
            return False
        
    except Exception as e:
        print(f"❌ Error in ContextManager test: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        # Clean up
        coq.close()

def test_context_manager_with_proof(config):
    """Test that ContextManager can work with a proof file."""
    print("\n🧪 Testing ContextManager with proof file...")
    
    if not coq_file.exists():
        print(f"Error: Example file not found at {coq_file}")
        return False
    
    coq = CoqInterface(str(coq_file))
    coq.load()
    
    try:
        cm = ContextManager(coq, api_key=config.llm.api_key)

        print("== Initial proof state ==")
        goals = coq.get_goal_str()
        hypotheses = coq.get_hypothesis()
        
        print(f"Goals: {goals[:200] if goals else 'None'}...")
        print(f"Hypotheses: {hypotheses[:100] if hypotheses else 'None'}...")
        
        # Test building initial prompt
        print("\n🔧 Testing build_initial_prompt...")
        try:
            from agent.proof_tree import ProofTree
            proof_tree = ProofTree()
            # Add a dummy root node
            proof_tree.add_node(
                tactic="Proof.",
                goals_before=goals or "",
                goals_after=goals or "",
                hypotheses_before=hypotheses or "",
                hypotheses_after=hypotheses or "",
                step_number=1,
                subgoals_after=[]
            )
            proof_tree_str = proof_tree.get_proof_tree_string()
            prompt = cm.build_initial_prompt(proof_tree_str)
            
            if prompt and len(prompt) > 0:
                print(f"✅ Initial prompt built successfully ({len(prompt)} chars)")
                print(f"   Preview: {prompt[:200]}...")
                return True
            else:
                print("❌ Initial prompt is empty")
                return False
        except Exception as e:
            print(f"❌ Error building initial prompt: {e}")
            import traceback
            traceback.print_exc()
            return False
            
    except Exception as e:
        print(f"❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        coq.close()

def test_extract_essential_content(config):
    """Test that ContextManager can extract essential proof content."""
    print("\n🧪 Testing extract_essential_proof_content...")
    
    if not coq_file.exists():
        print(f"Error: Example file not found at {coq_file}")
        return False
    
    coq = CoqInterface(str(coq_file))
    coq.load()
    
    try:
        cm = ContextManager(coq, api_key=config.llm.api_key)
        
        # Read the file content
        with open(coq_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        print(f"   Original content: {len(content)} chars")
        
        # Extract essential content
        extracted = cm.extract_essential_proof_content(content)
        
        print(f"   Extracted content: {len(extracted)} chars")
        print(f"   Compression ratio: {len(extracted)/len(content):.1%}" if len(content) > 0 else "   N/A")
        
        if extracted and len(extracted) > 0:
            print(f"✅ Content extraction successful")
            return True
        else:
            print("❌ Content extraction returned empty result")
            return False
            
    except Exception as e:
        print(f"❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        coq.close()

if __name__ == "__main__":
    print("=" * 60)
    print("Testing ContextManager")
    print("=" * 60)
    
    config = ProofAgentConfig.from_file(str(config_file))
    
    # Run initialization test
    print("\n--- ContextManager Initialization Test ---")
    init_test_passed = test_context_manager_initialization(config)
    
    # Run proof file test
    print("\n--- ContextManager Proof File Test ---")
    proof_test_passed = test_context_manager_with_proof(config)
    
    # Run content extraction test
    print("\n--- Content Extraction Test ---")
    extraction_test_passed = test_extract_essential_content(config)
    
    # Summary
    print("\n" + "=" * 60)
    all_passed = init_test_passed and proof_test_passed and extraction_test_passed
    
    if all_passed:
        print("✅ All ContextManager tests PASSED!")
        print("The ContextManager is working correctly.")
        sys.exit(0)
    else:
        print("❌ Some ContextManager tests FAILED!")
        print(f"   - Initialization: {'✅' if init_test_passed else '❌'}")
        print(f"   - Proof file: {'✅' if proof_test_passed else '❌'}")
        print(f"   - Content extraction: {'✅' if extraction_test_passed else '❌'}")
        sys.exit(1)
