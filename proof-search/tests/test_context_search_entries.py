"""
Test script for Context Search on match_string_assert.v
Tests specific search commands with ranking and summarization
"""

import sys
import os
import json
from pathlib import Path
from datetime import datetime

# Add the parent directory to the path so we can import from agent
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    from backend.coq_interface import CoqInterface
    from agent.context_search import CoqCommandSearch
    print("✅ CoqInterface and CoqCommandSearch available")
except ImportError as e:
    print(f"❌ Import failed: {e}")
    sys.exit(1)


def test_search_commands():
    """Test specific search commands with ranking and summarization"""
    print("\n" + "=" * 70)
    print("Testing Search Commands with Ranking and Summarization")
    print("=" * 70)
    
    proof_file_path = PROJECT_ROOT / "examples" / "match_string_assert.v"
    
    if not proof_file_path.exists():
        print(f"❌ Proof file not found: {proof_file_path}")
        return False
    
    print(f"📄 Proof file: {proof_file_path}")
    
    try:
        # Initialize CoqInterface and CoqCommandSearch
        coq = CoqInterface(str(proof_file_path))
        coq.load()
        print("✅ CoqInterface loaded successfully")
        
        # Initialize CoqCommandSearch with ranking capabilities
        coq_search = CoqCommandSearch(coq)
        print("✅ CoqCommandSearch initialized\n")
        
        # Test commands with goal context for better ranking
        test_cases = [
            {
                "command": "About Q_real_len_not_nulls.",
                "goal_context": "Q_real_len not nulls list"
            },
            {
                "command": "Search L_real_len.",
                "goal_context": "L_real_len length list real"
            }
        ]
        
        for i, test_case in enumerate(test_cases, 1):
            cmd = test_case["command"]
            goal_context = test_case.get("goal_context", "")
            
            print(f"{'=' * 70}")
            print(f"Command {i}: {cmd}")
            if goal_context:
                print(f"Goal Context: {goal_context}")
            print(f"{'=' * 70}")
            
            try:
                # Use auto_search which applies ranking and reduction
                search_result = coq_search.auto_search(cmd, goal_context)
                
                print(f"\n📊 Result Metadata:")
                print(f"  - Original Size: {search_result.original_size} characters")
                print(f"  - Final Size: {search_result.result_size} characters")
                print(f"  - Reduction Applied: {search_result.reduction_applied}")
                print(f"  - Relevance Score: {search_result.relevance_score}")
                if search_result.metadata.get('size_saved', 0) > 0:
                    print(f"  - Size Saved: {search_result.metadata['size_saved']} characters")
                
                print(f"\n📄 Search Results:")
                print("-" * 70)
                print(search_result.content)
                print("-" * 70)
                print()
                
            except Exception as e:
                print(f"❌ Query failed: {e}")
                import traceback
                traceback.print_exc()
                print()
        
        # Clean up
        coq.close()
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = test_search_commands()
    sys.exit(0 if success else 1)
