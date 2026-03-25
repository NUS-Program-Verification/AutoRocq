"""
Diagnostic script to understand CoqInterface capabilities
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.coq_interface import CoqInterface

def test_coq_interface_initialization():
    """Test CoqInterface initialization with full query command testing."""
    print("\n🔬 Testing CoqInterface Initialization (Enhanced search() method)")
    print("=" * 50)
    
    proof_file_path = PROJECT_ROOT / "examples" / "main_loop_invariant_2_established_Coq.v"
    
    try:
        # Initialize CoqInterface
        coq = CoqInterface(str(proof_file_path))
        print("✅ CoqInterface object created")
        
        # CRUCIAL: Load the file first!
        coq.load()
        print("✅ CoqInterface loaded successfully")
        
        # Test all query command functionality
        print("\n🔍 Testing enhanced search() method with all query types:")
        
        search_commands = [
            # Search commands
            "Search Z.abs",
            "Search (_ <= _)",
            "Search Z.mul",
            "Search nat",
            "Search (_ + _)",
            # Print commands  
            "Print Z.abs",
            "Print nat",
            "Print bool",
            "Print option",
            # Print Assumptions commands
            "Print Assumptions",
            "Print Assumptions Z.abs",
            # Locate commands
            "Locate Z.abs", 
            "Locate le",
            "Locate mult",
            "Locate nat",
            # About commands
            "About Z.abs",
            "About Z",
            "About nat", 
            "About bool",
            # Check commands
            "Check Z.abs",
            "Check nat",
            "Check bool",
            "Check (fun x => x + 1)"
        ]
        
        successful_searches = 0
        command_results = {}
        
        for cmd in search_commands:
            try:
                print(f"\n--- {cmd} ---")
                result = coq.search(cmd)  # All commands now go through enhanced search()
                print(f"✅ Query result: {result[:200]}...")
                successful_searches += 1
                
                # Categorize results by command type
                cmd_type = cmd.split()[0].lower()
                if cmd_type not in command_results:
                    command_results[cmd_type] = 0
                command_results[cmd_type] += 1
                
            except Exception as e:
                print(f"❌ Query failed: {e}")
        
        print(f"\n📊 Successful queries: {successful_searches}/{len(search_commands)}")
        print(f"📊 Results by command type:")
        for cmd_type, count in command_results.items():
            print(f"   - {cmd_type.upper()}: {count} successful")
        
        # Clean up
        coq.close()
        return successful_searches > 0
        
    except Exception as e:
        print(f"❌ CoqInterface initialization failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    test_coq_interface_initialization()