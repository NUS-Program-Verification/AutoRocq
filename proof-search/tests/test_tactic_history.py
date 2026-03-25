import os
import sys
import json
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.coq_interface import CoqInterface
from agent.history_recorder import TacticHistoryManager, TacticHistoryEntry
from utils.config import ProofAgentConfig

# --- CONFIGURATION ---
coq_file = PROJECT_ROOT / "examples" / "main_loop_invariant_2_established_Coq.v"
config_file = PROJECT_ROOT / "configs" / "default_config.json"
history_file = PROJECT_ROOT / "data" / "tactic_history.json"

def clean_ansi_codes(text):
    """Remove ANSI escape codes from text."""
    import re
    if not text:
        return ""
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    return ansi_escape.sub('', text)

def debug_coq_setup():
    """Debug the CoqInterface setup process step by step"""
    print("\n🔍 DEBUGGING COQ SETUP PROCESS")
    print("=" * 50)
    
    try:
        # Remove existing history file for clean test
        if history_file.exists():
            history_file.unlink()
            print(f"🗑️ Removed existing history file: {history_file}")
        
        # Check if files exist
        print(f"📁 Checking file existence:")
        print(f"   - Coq file: {coq_file.exists()} ({coq_file})")
        print(f"   - Config file: {config_file.exists()} ({config_file})")
        
        if not coq_file.exists():
            print(f"❌ Coq file does not exist!")
            return False
            
        if not config_file.exists():
            print(f"❌ Config file does not exist!")
            return False
        
        # Clean proof file first
        print(f"🧹 Cleaning proof file...")
        try:
            with open(coq_file, 'r', encoding='utf-8') as f:
                content = f.read()
            
            proof_pos = content.find("Proof.")
            if proof_pos != -1:
                clean_content = content[:proof_pos + len("Proof.")] + "\n"
                with open(coq_file, 'w', encoding='utf-8') as f:
                    f.write(clean_content)
                print("✅ Proof file cleaned")
            else:
                print("⚠️ No 'Proof.' found in file")
        except Exception as e:
            print(f"❌ Failed to clean proof file: {e}")
            return False
        
        # Load configuration
        print(f"📖 Loading configuration...")
        try:
            config = ProofAgentConfig.from_file(str(config_file))
            print(f"✅ Configuration loaded successfully")
            print(f"   - Workspace: {getattr(config.coq, 'workspace', 'None')}")
            print(f"   - Library paths: {getattr(config.coq, 'library_paths', 'None')}")
            print(f"   - Timeout: {getattr(config.coq, 'timeout', 'None')}")
        except Exception as e:
            print(f"❌ Failed to load configuration: {e}")
            import traceback
            traceback.print_exc()
            return False
        
        # Create history manager FIRST
        print(f"📝 Creating TacticHistoryManager...")
        try:
            shared_history_manager = TacticHistoryManager(str(history_file))
            print(f"✅ Created TacticHistoryManager: {history_file}")
            print(f"📊 Initial entries: {len(shared_history_manager.entries)}")
        except Exception as e:
            print(f"❌ Failed to create TacticHistoryManager: {e}")
            import traceback
            traceback.print_exc()
            return False
        
        # Create CoqInterface
        print(f"🔧 Creating CoqInterface...")
        try:
            coq_interface = CoqInterface(
                file_path=str(coq_file),
                workspace=config.coq.workspace or str(coq_file.parent),
                library_paths=config.coq.library_paths,
                auto_setup_coqproject=config.coq.auto_setup_coqproject,
                timeout=config.coq.timeout
            )
            print(f"✅ CoqInterface created successfully")
        except Exception as e:
            print(f"❌ Failed to create CoqInterface: {e}")
            import traceback
            traceback.print_exc()
            return False
        
        # Try to load the file
        print(f"📂 Loading Coq file...")
        try:
            load_result = coq_interface.load()
            if load_result:
                print(f"✅ CoqInterface loaded successfully")
            else:
                error_msg = coq_interface.get_last_error()
                print(f"❌ Failed to load file: {error_msg}")
                return False
        except Exception as e:
            print(f"❌ Exception during file load: {e}")
            import traceback
            traceback.print_exc()
            return False
        
        # Test applying a simple tactic
        print(f"🧪 Testing simple tactic application...")
        try:
            # Get initial state
            initial_goals = clean_ansi_codes(coq_interface.get_goal_str())
            initial_hypotheses = clean_ansi_codes(coq_interface.get_hypothesis())
            
            print(f"📊 Initial state:")
            print(f"   - Goals: {initial_goals[:100]}...")
            print(f"   - Hypotheses: {initial_hypotheses[:50]}...")
            
            # Apply simple tactic
            test_tactic = "intros i_1 i Hle Hlow Hup Hup_i Hsint."
            print(f"🎯 Applying tactic: {test_tactic}")
            
            success = coq_interface.apply_tactic(test_tactic)
            
            if success:
                print(f"✅ Tactic applied successfully")
                
                # Get new state
                new_goals = clean_ansi_codes(coq_interface.get_goal_str())
                new_hypotheses = clean_ansi_codes(coq_interface.get_hypothesis())
                
                print(f"📊 New state:")
                print(f"   - Goals: {new_goals[:100]}...")
                print(f"   - Hypotheses: {new_hypotheses[:50]}...")
                
                # Add to history
                print(f"💾 Adding to history...")
                initial_count = len(shared_history_manager.entries)
                
                shared_history_manager.add_successful_tactic(
                    tactic=test_tactic,
                    goals_before=initial_goals,
                    goals_after=new_goals,
                    theorem_name="debug_test",
                    hypotheses_before=initial_hypotheses,
                    hypotheses_after=new_hypotheses,
                    step_number=1
                )
                
                final_count = len(shared_history_manager.entries)
                print(f"📊 Entries: {initial_count} -> {final_count}")
                
                # Save to file
                print(f"💾 Saving to file...")
                shared_history_manager.save_history()
                
                # Verify file
                if history_file.exists():
                    file_size = history_file.stat().st_size
                    print(f"✅ File saved: {file_size} bytes")
                    
                    # Read and verify
                    with open(history_file, 'r', encoding='utf-8') as f:
                        content = f.read()
                        print(f"📄 File content preview:\n{content[:300]}...")
                        
                        try:
                            data = json.loads(content)
                            entries_count = len(data.get('entries', []))
                            print(f"📊 Entries in file: {entries_count}")
                            
                            if entries_count > 0:
                                print(f"🎉 SUCCESS: History saved successfully!")
                                return True
                            else:
                                print(f"❌ File has no entries")
                                return False
                        except json.JSONDecodeError as e:
                            print(f"❌ JSON parsing failed: {e}")
                            return False
                else:
                    print(f"❌ File not created")
                    return False
            else:
                error_msg = coq_interface.get_last_error()
                print(f"❌ Tactic failed: {error_msg}")
                return False
                
        except Exception as e:
            print(f"❌ Exception during tactic test: {e}")
            import traceback
            traceback.print_exc()
            return False
        
        finally:
            try:
                coq_interface.close()
                print(f"🔒 CoqInterface closed")
            except:
                pass
                
    except Exception as e:
        print(f"❌ Debug setup failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def check_file_after_test():
    """Check what's in the file after all tests complete"""
    print(f"\n🔍 CHECKING FILE AFTER ALL TESTS")
    print("=" * 40)
    
    if history_file.exists():
        file_size = history_file.stat().st_size
        print(f"📄 File exists: {file_size} bytes")
        
        if file_size > 0:
            with open(history_file, 'r', encoding='utf-8') as f:
                content = f.read()
                print(f"📄 Content:\n{content}")
                
                try:
                    data = json.loads(content)
                    entries = data.get('entries', [])
                    print(f"📊 Parsed {len(entries)} entries")
                    return len(entries)
                except json.JSONDecodeError as e:
                    print(f"❌ JSON error: {e}")
                    return 0
        else:
            print(f"📄 File is empty")
            return 0
    else:
        print(f"📄 File does not exist")
        return 0

def simple_working_test():
    """Use the pattern that worked in isolated test"""
    print(f"\n✅ SIMPLE WORKING TEST")
    print("=" * 30)
    
    try:
        # Remove file first
        if history_file.exists():
            history_file.unlink()
            print(f"🗑️ Removed existing file")
        
        # Create manager and add entry (this worked before)
        manager = TacticHistoryManager(str(history_file))
        print(f"✅ Created manager")
        
        manager.add_successful_tactic(
            tactic="intros x y z.",
            goals_before="forall x y z : nat, x + y = z",
            goals_after="x, y, z : nat |- x + y = z",
            theorem_name="simple_test",
            step_number=1
        )
        print(f"✅ Added entry")
        
        manager.save_history()
        print(f"✅ Saved history")
        
        # Check result
        return check_file_after_test()
        
    except Exception as e:
        print(f"❌ Simple test failed: {e}")
        return 0

if __name__ == "__main__":
    print("=" * 70)
    print("🔍 TACTIC HISTORY DEBUG TEST SUITE")
    print("=" * 70)
    
    # First, try the simple test that we know works
    print(f"\n{'='*70}")
    print("TEST 1: Simple Working Test")
    print(f"{'='*70}")
    simple_result = simple_working_test()
    
    # Then, debug the full Coq setup
    print(f"\n{'='*70}")
    print("TEST 2: Debug Coq Setup")
    print(f"{'='*70}")
    debug_result = debug_coq_setup()
    
    # Final check
    print(f"\n{'='*70}")
    print("🏁 FINAL RESULTS")
    print(f"{'='*70}")
    
    print(f"Simple test entries: {simple_result}")
    print(f"Debug test result: {'✅ SUCCESS' if debug_result else '❌ FAILED'}")
    
    # Final file status
    final_entries = check_file_after_test()
    print(f"Final entries in file: {final_entries}")
    
    if final_entries > 0:
        print(f"🎉 SUCCESS: File contains {final_entries} entries!")
    else:
        print(f"❌ FAILURE: File is empty or missing")
        
        # If file is empty, check if it exists but empty
        if history_file.exists():
            print(f"🔍 File exists but is empty - possible overwrite issue")
        else:
            print(f"🔍 File doesn't exist - creation issue")
