#!/usr/bin/env python3
import os
import sys
from pathlib import Path
from datetime import datetime
import time
from typing import List, Dict, Any

import pytest

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
if len(sys.argv) > 1 and sys.argv[1].endswith(".json"):
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

def prove_single_file(
    coq_file: Path,
    config: ProofAgentConfig,
    results_dir: Path = None,
    result_name: str = None,
) -> bool:
    """Prove a single file with crash recovery.

    The benchmark files are tracked sources: cleaning strips their proofs and
    coqpyt writes each accepted tactic back to disk, so a run would rewrite the
    whole of AutoRocq-bench. Every attempt therefore happens on a scratch copy,
    and the result is saved into results_dir where it can be re-checked later.
    """
    max_crash_retries = 3
    crash_count = 0
    
    while crash_count < max_crash_retries:
        coq_interface = None
        try:
            # CoqInterface proves on a copy, so the benchmark file is never touched.
            coq_interface = CoqInterface(
                file_path=str(coq_file),
                workspace=config.coq.workspace or str(Path(coq_file).parent),
                library_paths=config.coq.library_paths,
                auto_setup_coqproject=config.coq.auto_setup_coqproject,
                coqproject_extra_options=config.coq.coqproject_extra_options,
                timeout=config.coq.timeout
            )
            
            try:
                if not clean_proof_file(coq_interface.file_path):
                    return False

                # Load the cleaned file
                if not coq_interface.load():
                    return False
                
                # Initialize ContextManager
                context_manager = ContextManager(
                    coq_interface,
                    api_key=config.llm.api_key,
                    enable_history_context=getattr(config, "enable_history_context", True),
                    enable_context_search=getattr(config, "enable_context_search", True),
                )
                
                # Initialize ProofController with updated parameters
                controller = ProofController(
                    coq_interface=coq_interface,
                    context_manager=context_manager,
                    max_steps=100,  # Reasonable limit for testing
                    enable_error_feedback=getattr(config, "enable_error_feedback", True),
                    max_context_search=getattr(config, "max_context_search", 3),
                    output_dir=str(results_dir) if results_dir else None,
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
        
        finally:
            if coq_interface is not None and results_dir is not None:
                coq_interface.save_result(results_dir, result_name)
    
    return False

@pytest.mark.llm
def test_folder_batch(tmp_path):
    """Prove every .v file listed in the ablation list and check the tally.

    This is the ablation experiment, not a unit test: it runs the whole agent
    over ~70 benchmark goals and costs real API time. It stays behind the `llm`
    marker for that reason.

    The old version counted proved/failed, printed a success rate, and returned
    `proved_count > 0` -- which pytest ignores. A run in which every single goal
    failed, or in which the lemma list resolved to nothing, passed exactly like
    a clean sweep. It also wrote its results under the repo's results/ rather
    than into a temp directory.
    """
    assert config_file.exists(), f"config not found: {config_file}"
    config = ProofAgentConfig.from_file(str(config_file))

    if not lemmas_txt.exists():
        pytest.skip(f"benchmark list not checked out: {lemmas_txt}")

    v_files = read_v_files_from_lemmas(str(lemmas_txt), str(benchmark_folder))
    assert v_files, f"no .v files resolved from {lemmas_txt}"

    # Each attempt is saved so it can be re-verified independently later,
    # instead of being overwritten by the next run.
    results_dir = tmp_path / f"batch-{datetime.now():%Y%m%d-%H%M%S}"
    results_dir.mkdir(parents=True)

    outcomes = {}
    for i, coq_file in enumerate(v_files, 1):
        rel_path = os.path.relpath(coq_file, str(benchmark_folder))
        print(f"\n=== [{i}/{len(v_files)}] {rel_path} ===")
        start = time.time()
        success = prove_single_file(
            coq_file, config, results_dir, rel_path.replace(os.sep, "__")
        )
        assert isinstance(success, bool), f"{rel_path}: got {success!r}"
        outcomes[rel_path] = success
        print(f"    {'proved' if success else 'failed'} in {time.time() - start:.1f}s")

    proved = [name for name, ok in outcomes.items() if ok]
    print(f"\n{len(proved)}/{len(v_files)} proved")

    # Every listed file was attempted and got a verdict.
    assert len(outcomes) == len(v_files)

    # Every attempt left a saved artefact, whether or not it was proved.
    saved = list(results_dir.iterdir())
    assert saved, "no results were written"

    # The benchmark sources are never edited: each attempt runs on a copy.
    for coq_file in v_files:
        assert "Admitted." in Path(coq_file).read_text(encoding="utf-8"), (
            f"{coq_file} was modified in place"
        )

    # A run that proves nothing at all means the agent is broken, not that the
    # benchmark got harder.
    assert proved, f"not one of {len(v_files)} goals was proved"
