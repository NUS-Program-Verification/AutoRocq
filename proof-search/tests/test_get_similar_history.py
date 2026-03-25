import os
import sys
import json
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from agent.history_recorder import TacticHistoryManager

def test_with_real_history():
    """Test get_similar_history with existing real history data"""
    print(f"\n🔍 TESTING WITH REAL HISTORY DATA")
    print("=" * 50)
    
    try:
        # Use the actual history file
        real_history_file = PROJECT_ROOT / "data" / "tactic_history.json"
        
        if not real_history_file.exists():
            print(f"⚠️ Real history file not found: {real_history_file}")
            print(f"💡 Run some proof tests first to generate history data")
            return True
        
        # Load real history
        real_history_manager = TacticHistoryManager(str(real_history_file))
        
        if not real_history_manager.entries:
            print(f"⚠️ No entries in real history file")
            return True
        
        print(f"✅ Loaded {len(real_history_manager.entries)} real history entries")
        
        # Test with a typical proof state
        test_query = "forall i i1 : int, i <= i1 -> i <= 9 -> i1 <= 9 -> is_sint32 i -> i1 * i1 <= 99"
        
        print(f"\n🔍 Query: {test_query}")
        similar_real = real_history_manager.get_similar_history(test_query, n=5)
        
        print(f"✅ Found {len(similar_real)} similar tactics from real history:")
        
        for i, tactic_info in enumerate(similar_real, 1):
            tactic = tactic_info['tactic'].strip()
            print(f"\n  {i}. {tactic}")
            print(f"     Goals before: {tactic_info['goals_before']}...")
            print(f"     Goals after: {tactic_info['goals_after']}...")
            
        return len(similar_real) > 0
        
    except Exception as e:
        print(f"❌ Real history test failed: {e}")
        return False

if __name__ == "__main__":
    print("=" * 70)
    print("🧪 GET_SIMILAR_HISTORY FUNCTION TEST")
    print("=" * 70)


    print(f"\nTEST : Real History Data Test") 
    print("="*70)
    success_2 = test_with_real_history()
    
    # Final results
    print(f"\n{'='*70}")
    print("🏁 FINAL TEST RESULTS")
    print(f"{'='*70}")
    
    print(f"Real history test: {'✅ PASSED' if success_2 else '❌ FAILED'}")
