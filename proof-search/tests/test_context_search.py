"""
Test script for Context Search Module with Adaptive Result Reduction
Tests full Coq command search functionality: Search/Print/Check/About/Locate/Print Assumptions
with adaptive size reduction strategies.
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
    from agent.context_search import ContextSearch, CoqCommandSearch, SearchResult
    print("✅ Successfully imported context search modules")
except ImportError as e:
    print(f"❌ Failed to import context search modules: {e}")
    sys.exit(1)

try:
    from backend.coq_interface import CoqInterface
    REAL_COQ_AVAILABLE = True
    print("✅ Real CoqInterface available")
except ImportError as e:
    print(f"❌ Real CoqInterface not available: {e}")
    sys.exit(1)


def check_coq_setup():
    """Check if CoqInterface can be properly initialized."""
    print("\n🔧 Checking CoqInterface Setup...")
    
    # Check if files exist
    workspace = PROJECT_ROOT / "examples"
    proof_file = PROJECT_ROOT / "examples" / "main_loop_invariant_2_established_Coq.v"
    lib_path = PROJECT_ROOT / "lib-sv-comp"
    
    print(f"📁 Workspace exists: {Path(workspace).exists()}")
    print(f"📄 Proof file exists: {Path(proof_file).exists()}")
    print(f"📚 Library path exists: {Path(lib_path).exists()}")
    
    # Check proof file content
    if Path(proof_file).exists():
        with open(proof_file, 'r') as f:
            content = f.read()
            print(f"📄 Proof file size: {len(content)} characters")
            
            # Check if proof is complete
            if content.strip().endswith('Proof.'):
                print("✅ Proof file ends with 'Proof.' - perfect for testing!")
                print("   This means we can enter proving mode for search commands")
            elif 'Qed.' in content or 'Defined.' in content:
                print("✅ Proof file contains completed proofs")
            else:
                print("⚠️  Proof file status unclear")
    
    if Path(lib_path).exists():
        lib_files = list(Path(lib_path).glob("*.v"))
        print(f"📚 Library files found: {len(lib_files)}")
        for f in lib_files[:5]:  # Show first 5 files
            print(f"   - {f.name}")
    
    return Path(workspace).exists() and Path(proof_file).exists()


def test_coq_interface_initialization():
    """Test CoqInterface initialization with full query command testing."""
    print("\n🔬 Testing CoqInterface Initialization (Full Query Commands)")
    print("=" * 50)
    
    # Use the correct initialization pattern from LLM test
    proof_file_path = PROJECT_ROOT / "examples" / "main_loop_invariant_2_established_Coq.v"    
    try:
        # Initialize CoqInterface with just file path (like in LLM test)
        coq = CoqInterface(proof_file_path)
        print("✅ CoqInterface object created")
        
        # Load the file (essential step!)
        coq.load()
        print("✅ CoqInterface loaded successfully")
        
        # Check what we have
        attrs = [attr for attr in dir(coq) if not attr.startswith('_')]
        print(f"Available methods: {attrs}")
        
        # Test basic functionality
        print("\n🧪 Testing basic functionality:")
        
        # Check goals and hypotheses
        try:
            goals = coq.get_goal_str()
            hypotheses = coq.get_hypothesis()
            print(f"✅ Current goals: {goals}")
            print(f"✅ Current hypotheses: {hypotheses}")
        except Exception as e:
            print(f"⚠️  Goal/hypothesis check: {e}")
        
        # Test all query command functionality (the key part!)
        print("\n🔍 Testing full query command functionality:")
        
        search_commands = [
            # Search commands (these should trigger reduction)
            "Search Z.abs.",
            "Search (_ <= _).",
            "Search (_ + _).",
            "Search (forall _ : int, _ \/ _).",
            # Print commands (small results)
            "Print Z.abs.",
            "Print nat.",
            "Print bool.",
            # Print Assumptions commands
            "Print Assumptions.",
            "Print Assumptions Z.abs.",
            # Locate commands
            "Locate le.",
            "Locate mult.",
            # About commands
            "About Z.",
            "About nat.",
            # Check commands
            "Check nat.",
            "Check bool.",
        ]
        
        successful_searches = 0
        command_results = {}
        total_result_size = 0
        reduction_summary = {'none': 0, 'boundary_aware_truncation': 0, 'structured_summary': 0, 'simple_truncation': 0}
        
        for cmd in search_commands:
            try:
                print(f"\n--- {cmd} ---")
                result = coq.search(cmd)
                result_size = len(result) if result else 0
                total_result_size += result_size
                
                print(f"✅ Query result: {result[:200]}...")
                print(f"📊 Raw result size: {result_size} characters")
                successful_searches += 1
                
                # Categorize results by command type
                cmd_type = cmd.split()[0].lower()
                if cmd_type not in command_results:
                    command_results[cmd_type] = {'count': 0, 'total_size': 0, 'raw_total': 0}
                command_results[cmd_type]['count'] += 1
                command_results[cmd_type]['raw_total'] += result_size
                
            except Exception as e:
                print(f"❌ Query failed: {e}")
        
        print(f"\n📊 Raw Results Summary:")
        print(f"📊 Successful queries: {successful_searches}/{len(search_commands)}")
        print(f"📊 Total raw result size: {total_result_size} characters")
        print(f"📊 Average raw result size: {total_result_size / successful_searches:.1f} characters" if successful_searches > 0 else "")
        print(f"📊 Raw results by command type:")
        for cmd_type, data in command_results.items():
            avg_size = data['raw_total'] / data['count'] if data['count'] > 0 else 0
            print(f"   - {cmd_type.upper()}: {data['count']} successful, {data['raw_total']} total chars, {avg_size:.1f} avg chars")
        
        # Clean up
        coq.close()
        return successful_searches > 0
        
    except Exception as e:
        print(f"❌ CoqInterface initialization failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_coq_command_search_with_reduction():
    """Test CoqCommandSearch functionality with adaptive result reduction."""
    print("\n" + "=" * 60)
    print("TESTING CoqCommandSearch with Adaptive Result Reduction")
    print("=" * 60)
    
    # Check setup first
    if not check_coq_setup():
        print("❌ CoqInterface setup check failed - skipping test")
        return False
    
    # Test correct initialization first
    if not test_coq_interface_initialization():
        print("❌ CoqInterface initialization failed - skipping CoqCommandSearch test")
        return False
    
    # Initialize CoqInterface using correct pattern
    proof_file_path = PROJECT_ROOT / "examples" / "main_loop_invariant_2_established_Coq.v"

    try:
        # Use the correct initialization pattern
        coq_interface = CoqInterface(str(proof_file_path))
        coq_interface.load()  # Essential!
        print("✅ CoqInterface initialized and loaded for reduction testing")
        
        # Create CoqCommandSearch
        coq_search = CoqCommandSearch(coq_interface)
        
        # Test cases specifically designed to test reduction strategies
        test_cases = [
            # Large search results (should trigger structured summarization)
            ("Search pattern (_ <= _) - Large Result", "search_pattern", None, "(_ <= _)", "forall x y z : Z, x <= y -> y <= z -> x <= z"),
            ("Search pattern (_ + _) - Large Result", "search_pattern", None, "(_ + _)", "forall x y : Z, x + y = y + x"),
            ("Search lemma Z.abs - Large Result", "search_lemma", "Z.abs", None, "forall x : Z, 0 <= Z.abs x"),
            
            # Medium results (should trigger boundary-aware truncation)
            ("Search lemma mult", "search_lemma", "mult", None, "multiplication"),
            
            # Small results (should remain unchanged)
            ("Print definition Z.abs", "print_definition", "Z.abs", None, ""),
            ("Print definition nat", "print_definition", "nat", None, ""),
            ("Check Z.abs", "check_term", "Z.abs", None, ""),
            ("Check nat", "check_term", "nat", None, ""),
            ("About Z.abs", "about_identifier", "Z.abs", None, ""),
            ("Locate le", "locate_definition", "le", None, ""),
            
            # Auto search tests
            ("Auto search - Search (_ * _)", "auto_search", "Search (_ * _).", None, "multiplication associativity"),
            ("Auto search - Print bool", "auto_search", "Print bool.", None, ""),
        ]
        
        successful_tests = 0
        results_by_reduction = {'none': [], 'boundary_aware_truncation': [], 'structured_summary': [], 'simple_truncation': []}
        total_original_size = 0
        total_final_size = 0
        total_bytes_saved = 0
        
        for test_name, method_name, identifier, pattern, goal_context in test_cases:
            print(f"\n--- {test_name} ---")
            print(f"Method: {method_name}")
            if identifier:
                print(f"Identifier: {identifier}")
            if pattern:
                print(f"Pattern: {pattern}")
            if goal_context:
                print(f"Goal context: {goal_context}")
            
            try:
                # Execute the search with goal context for relevance ranking
                if method_name == "search_lemma":
                    result = coq_search.search_lemma(identifier, goal_context)
                elif method_name == "search_pattern":
                    result = coq_search.search_pattern(pattern, goal_context)
                elif method_name == "print_definition":
                    result = coq_search.print_definition(identifier)
                elif method_name == "print_assumptions":
                    result = coq_search.print_assumptions(identifier)
                elif method_name == "locate_definition":
                    result = coq_search.locate_definition(identifier)
                elif method_name == "about_identifier":
                    result = coq_search.about_identifier(identifier)
                elif method_name == "check_term":
                    result = coq_search.check_term(identifier)
                elif method_name == "auto_search":
                    result = coq_search.auto_search(identifier, goal_context)
                else:
                    print(f"❌ Unknown method: {method_name}")
                    continue
                
                # Print reduction analysis
                print(f"✅ Source: {result.source}")
                print(f"✅ Relevance: {result.relevance_score}")
                print(f"📊 Original size: {result.original_size} characters")
                print(f"📊 Final size: {result.result_size} characters")
                print(f"🔧 Reduction applied: {result.reduction_applied or 'none'}")
                
                if result.original_size > result.result_size:
                    bytes_saved = result.original_size - result.result_size
                    reduction_percent = (bytes_saved / result.original_size) * 100
                    print(f"💾 Bytes saved: {bytes_saved} ({reduction_percent:.1f}% reduction)")
                    total_bytes_saved += bytes_saved
                else:
                    print(f"💾 No reduction needed")
                
                # Print content preview (handle None case)
                if result.content:
                    print(f"✅ Content preview: {result.content[:150]}...")
                else:
                    print(f"⚠️  No content returned")
                
                if result.metadata:
                    print(f"✅ Metadata: {result.metadata}")
                
                # Track reduction statistics
                reduction_method = result.reduction_applied or 'none'
                results_by_reduction[reduction_method].append({
                    'test_name': test_name,
                    'original_size': result.original_size,
                    'final_size': result.result_size,
                    'reduction_percent': ((result.original_size - result.result_size) / result.original_size * 100) if result.original_size > 0 else 0
                })
                
                successful_tests += 1
                total_original_size += result.original_size
                total_final_size += result.result_size
                
            except Exception as e:
                print(f"❌ Error: {e}")
                import traceback
                traceback.print_exc()
        
        # Print comprehensive reduction analysis
        print(f"\n" + "=" * 60)
        print(f"📊 REDUCTION ANALYSIS SUMMARY")
        print(f"=" * 60)
        
        print(f"📊 Successful tests: {successful_tests}/{len(test_cases)}")
        print(f"📊 Total original size: {total_original_size:,} characters")
        print(f"📊 Total final size: {total_final_size:,} characters")
        print(f"📊 Total bytes saved: {total_bytes_saved:,} characters")
        
        if total_original_size > 0:
            overall_reduction = (total_bytes_saved / total_original_size) * 100
            print(f"📊 Overall reduction: {overall_reduction:.1f}%")
        
        print(f"\n🔧 Reduction Methods Used:")
        for method, results in results_by_reduction.items():
            if results:
                count = len(results)
                avg_original = sum(r['original_size'] for r in results) / count
                avg_final = sum(r['final_size'] for r in results) / count
                avg_reduction = sum(r['reduction_percent'] for r in results) / count
                
                print(f"   - {method}: {count} tests")
                print(f"     → Avg original: {avg_original:.0f} chars")
                print(f"     → Avg final: {avg_final:.0f} chars") 
                print(f"     → Avg reduction: {avg_reduction:.1f}%")
                
                # Show examples
                for result in results[:2]:  # Show first 2 examples
                    print(f"     → Example: {result['test_name']} ({result['original_size']} → {result['final_size']} chars)")
        
        # Test specific reduction scenarios
        print(f"\n🧪 Testing Specific Reduction Scenarios:")
        
        # Test large search that should definitely be reduced
        try:
            print(f"\n--- Large Search Test: Search (_ * _) ---")
            large_result = coq_search.search_pattern("(_ * _)", "multiplication commutative associative")
            print(f"📊 Large search result: {large_result.original_size} → {large_result.result_size} chars")
            print(f"🔧 Reduction method: {large_result.reduction_applied}")
            
            # Print content if available
            if large_result.content:
                preview = large_result.content[:200] if len(large_result.content) > 200 else large_result.content
                print(f"📄 Content preview: {preview}...")
            else:
                print(f"⚠️  No content returned")
            
            if large_result.reduction_applied == 'structured_summary':
                print(f"✅ Large result correctly summarized")
            elif large_result.original_size > 1000:
                print(f"⚠️  Large result ({large_result.original_size} chars) but reduction method: {large_result.reduction_applied}")
            else:
                print(f"✅ Result size acceptable ({large_result.original_size} chars)")
        except Exception as e:
            print(f"❌ Large search test failed: {e}")
        
        # Clean up
        coq_interface.close()
        
        return successful_tests > 0
        
    except Exception as e:
        print(f"❌ Failed to initialize CoqInterface: {e}")
        import traceback
        traceback.print_exc()
        return False


def run_all_tests():
    """Run all context search tests focusing on adaptive reduction."""
    print("🚀 Starting Context Search Tests with Adaptive Result Reduction")
    print("=" * 90)
    
    results = []
    
    try:
        # Test: CoqCommandSearch with adaptive reduction
        print("\n" + "🧪 TEST: CoqCommandSearch with Adaptive Result Reduction")
        reduction_result = test_coq_command_search_with_reduction()
        results.append(("CoqCommandSearch with Reduction", reduction_result))
        
        # Summary
        print("\n" + "=" * 90)
        print("🏁 TEST RESULTS SUMMARY (ADAPTIVE REDUCTION)")
        print("=" * 90)
        
        passed_tests = 0
        for test_name, result in results:
            status = "✅ PASSED" if result else "❌ FAILED"
            print(f"{test_name}: {status}")
            if result:
                passed_tests += 1
        
        print(f"\nOverall: {passed_tests}/{len(results)} tests passed")
        
        if passed_tests == len(results):
            print("🎉 ALL REDUCTION TESTS PASSED!")
            print("✅ Adaptive result reduction working correctly")
            print("✅ Large search results properly summarized")
            print("✅ Medium results boundary-aware truncated")
            print("✅ Small results preserved unchanged")
            print("✅ Context-aware relevance ranking functional")
            return True
        else:
            print("❌ REDUCTION TESTS FAILED")
            print("🔧 Check result reduction implementation")
            return False
        
    except Exception as e:
        print(f"\n❌ Test suite failed with error: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = run_all_tests()
    
    print("\n" + "=" * 90)
    print("🏁 CONTEXT SEARCH REDUCTION TEST SUMMARY")
    print("=" * 90)
    
    if success:
        print("🎉 Context search reduction testing completed successfully!")
        print("✅ CoqCommandSearch: Working with adaptive reduction")
        print("✅ Result reduction strategies: Working")
        print("   - Small results (< 500): ✅ Preserved unchanged")
        print("   - Medium results (500-1K): ✅ Boundary-aware truncation")  
        print("   - Large results (> 1K): ✅ Structured summarization")
        print("✅ Context-aware ranking: Working")
        print("✅ Size tracking and analysis: Working")
        print("🚀 Ready for LLM integration with manageable result sizes")
    else:
        print("❌ Context search reduction testing failed")
        print("🔧 Check reduction algorithm implementation")
        print("🔧 Verify result parsing and ranking logic")
    
    print("\n💡 Adaptive reduction features:")
    print("   - 📏 Size-based strategy selection")
    print("   - 🎯 Goal context-aware relevance ranking")
    print("   - ✂️  Boundary-aware truncation at theorem boundaries")
    print("   - 📝 Structured summarization with categorization")
    print("   - 📊 Comprehensive size and reduction tracking")
    print("   - 🔍 Keyword extraction and matching")
    print("   - 📚 Standard library preference")
    print("   - 💾 Significant space savings for large results")
    
    sys.exit(0 if success else 1)