#!/usr/bin/env python3
import os
import sys
from pathlib import Path
import time
from typing import List, Dict, Any

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.coq_interface import CoqInterface
from agent.context_manager import ContextManager
from agent.proof_controller import ProofController
from utils.config import ProofAgentConfig

# --- CONFIGURATION ---
# Folder containing .v files to prove
benchmark_folder = PROJECT_ROOT.parent / "AutoRocq-bench" / "benchmarks" / "svcomp"
lemmas_txt = PROJECT_ROOT.parent / "AutoRocq-bench" / "benchmarks" / "svcomp-ablation.txt"

# Accept config file as a command-line argument
if len(sys.argv) > 1:
    print(f"Using config file from command line: {sys.argv[1]}")
    config_file = Path(sys.argv[1])
else:
    print("Using default config file")
    config_file = PROJECT_ROOT / "configs" / "default_config.json"

def clean_proof_file(file_path):
    """Clean the proof file by removing everything after 'Proof.' and adding fresh 'Proof.'"""
    try:
        # Read the original file
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Find the position of "Proof."
        proof_pos = content.find("Proof.")
        if proof_pos == -1:
            return False
        
        # Get content up to and including "Proof."
        clean_content = content[:proof_pos + len("Proof.")] + "\n"
        
        # Write the cleaned content back
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(clean_content)
        
        return True
        
    except Exception as e:
        return False

def read_v_files_from_lemmas(lemmas_path: str, benchmark_folder: str) -> List[str]:
    """Read .v file paths from lemmas.txt and return full paths."""
    v_files = []
    with open(lemmas_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or not line.endswith(".v"):
                continue
            full_path = os.path.join(benchmark_folder, line)
            if os.path.isfile(full_path):
                v_files.append(full_path)
            else:
                print(f"❌ File not found: {full_path}")
    return v_files

def prove_single_file(coq_file: Path, config: ProofAgentConfig) -> bool:
    """Prove a single file with crash recovery."""
    max_crash_retries = 3
    crash_count = 0
    
    while crash_count < max_crash_retries:
        try:
            # Clean the proof file first
            if not clean_proof_file(coq_file):
                return False
            
            # Initialize CoqInterface
            coq_interface = CoqInterface(
                file_path=str(coq_file),
                workspace=config.coq.workspace or str(Path(coq_file).parent),
                library_paths=config.coq.library_paths,
                auto_setup_coqproject=config.coq.auto_setup_coqproject,
                coqproject_extra_options=config.coq.coqproject_extra_options,
                timeout=config.coq.timeout
            )
            
            try:
                # Load the cleaned file
                if not coq_interface.load():
                    return False
                
                # Initialize ContextManager
                context_manager = ContextManager(
                    coq_interface,
                    api_key=config.llm.api_key,
                    enable_history_context=getattr(config, "enable_history_context", True)
                )
                
                # Initialize ProofController with updated parameters
                controller = ProofController(
                    coq_interface=coq_interface,
                    context_manager=context_manager,
                    max_steps=100,  # Reasonable limit for testing
                    enable_context_search=getattr(config, "enable_context_search", True),
                    enable_error_feedback=getattr(config, "enable_error_feedback", True),
                    max_context_search=getattr(config, "max_context_search", 3),
                )
                
                # Check proof status
                status = coq_interface.get_proof_status()
                if not status.get("has_proof", False):
                    return False
                
                # Extract theorem name (simple extraction from filename)
                theorem_name = Path(coq_file).stem
                
                # Use ProofController to prove the theorem (returns bool now)
                success = controller.prove_theorem(theorem_name)
                return success
            
            finally:
                coq_interface.close()
        
        except Exception as e:
            error_msg = str(e)
            if any(keyword in error_msg.lower() for keyword in ['out of memory', 'server quit', 'broken pipe']):
                crash_count += 1
                print(f"🚨 Coq server crashed (attempt {crash_count}/{max_crash_retries}): {error_msg}")
                
                if crash_count < max_crash_retries:
                    print("🔄 Restarting and retrying...")
                    time.sleep(2)  # Brief pause before retry
                    continue
                else:
                    print("❌ Max crash retries exceeded")
                    return False
            else:
                # Re-raise non-crash errors
                raise e
    
    return False

def test_folder_batch():
    """Test all .v files listed in lemmas.txt with simple progress output."""
    print("🚀 Batch Proof Testing")
    print("="*60)
    
    try:
        # Load configuration
        if not config_file.exists():
            print(f"❌ Config file not found: {config_file}")
            return False
        
        config = ProofAgentConfig.from_file(str(config_file))
        
        # Read .v files from lemmas.txt
        v_files = read_v_files_from_lemmas(str(lemmas_txt), str(benchmark_folder))
      
        if not v_files:
            print(f"❌ No .v files found in: {lemmas_txt}")
            return False
        
        total_files = len(v_files)
        proved_count = 0
        failed_count = 0
        
        print(f"📁 Found {total_files} .v files listed in {lemmas_txt}")
        print(f"🚀 Starting batch proof testing...")
        print()
        
        # Process each file
        for i, coq_file in enumerate(v_files, 1):
            rel_path = os.path.relpath(coq_file, str(benchmark_folder))
            # --- Add this line to clearly show which file is being proved ---
            print(f"\n=== Proving file [{i}/{total_files}]: {rel_path} | Proved: {proved_count} | Failed: {failed_count} | Remaining: {total_files - i} ===")
            start_time = time.time()
            success = prove_single_file(coq_file, config)
            elapsed = time.time() - start_time

            # Update counters
            if success:
                proved_count += 1
                result_text = "Yes"
            else:
                failed_count += 1
                result_text = "No"
            
            remaining = total_files - i
            success_rate = proved_count / i * 100
            
            #exit(1)
            # Print simple progress line
            #print(f"{rel_path:<50} {result_text:<3} Proved - [{proved_count}] Failed - [{failed_count}] Remaining [{remaining}] Progress [{i}/{total_files}] Success rate [{success_rate:.2f}%]")
            
        # Final summary
        print()
        print("="*60)
        print("🏁 BATCH TESTING COMPLETE")
        print("="*60)
        print(f"📊 Total files: {total_files}")
        print(f"✅ Proved: {proved_count}")
        print(f"❌ Failed: {failed_count}")
        print(f"📈 Success rate: {proved_count/total_files*100:.2f}%")
        
        return proved_count > 0
        
    except Exception as e:
        print(f"❌ Batch test failed: {e}")
        return False

if __name__ == "__main__":
    print("=" * 70)
    print("🚀 Folder Batch Proof Testing")
    print("=" * 70)

    # Check if config file exists
    if not config_file.exists():
        print(f"❌ Config file not found: {config_file}")
        print("💡 Please create the config file with library_paths configuration")
        sys.exit(1)
    
    # Check if folder exists
    if not benchmark_folder.exists():
        print(f"❌ Benchmark folder not found: {benchmark_folder}")
        print("💡 Please ensure the benchmark folder exists")
        sys.exit(1)
    
    # Check if lemmas file exists
    if not lemmas_txt.exists():
        print(f"❌ Lemmas file not found: {lemmas_txt}")
        sys.exit(1)
    
    # Test all files in folder
    success = test_folder_batch()
    
    if success:
        print("\n🎉 Batch testing completed with some successes!")
        sys.exit(0)
    else:
        print("\n❌ Batch testing failed or no successes")
        sys.exit(1)
