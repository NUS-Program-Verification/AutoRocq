import inspect
import os
import shutil
import tempfile
from pathlib import Path

import pytest


def skip_if_libraries_missing(config):
    for entry in config.coq.library_paths or []:
        path = entry["path"] if isinstance(entry, dict) else entry.path
        if not os.path.isdir(path):
            pytest.skip(
                f"Coq library '{entry.get('name', '?') if isinstance(entry, dict) else '?'}' "
                f"not available at {path}; configure coq.library_paths (README step 3)"
            )

# Project root for tests
PROJECT_ROOT = Path(__file__).parent.parent


def reset_coq_file_to_admitted(file_path: Path, backup: bool = True) -> bool:
    """
    Reset a Coq file so its first proof ends with Admitted. instead of Qed.
    This makes it an "unproven" proof that coqpyt and CoqInterface can work with.
    
    Args:
        file_path: Path to the .v file
        backup: If True, create a .backup file before modifying
        
    Returns:
        True if successful, False otherwise.
    """
    file_path = Path(file_path)
    
    if not file_path.exists():
        return False
    
    # Create backup if requested
    if backup:
        backup_path = file_path.with_suffix('.v.backup')
        shutil.copy2(file_path, backup_path)
    
    with open(file_path, 'r') as f:
        content = f.read()
    
    # Find the first proof block and reset it to just Proof. Admitted.
    lines = content.split('\n')
    clean_lines = []
    in_proof = False
    proof_found = False
    
    for line in lines:
        stripped = line.strip()
        
        # Start of proof
        if stripped.startswith('Proof.') and not proof_found:
            clean_lines.append(line)
            clean_lines.append('Admitted.')  # Add Admitted. right after Proof.
            in_proof = True
            proof_found = True
            continue
        
        # End of proof - skip everything until we see Qed. or Admitted.
        if in_proof:
            if stripped in ('Qed.', 'Admitted.', 'Defined.'):
                in_proof = False
            # Skip all lines inside the proof
            continue
        
        clean_lines.append(line)
    
    if not proof_found:
        return False
    
    # Write clean content back
    clean_content = '\n'.join(clean_lines)
    with open(file_path, 'w') as f:
        f.write(clean_content)
    
    return True


def restore_coq_file_from_backup(file_path: Path) -> bool:
    """
    Restore a Coq file from its .backup file.
    
    Args:
        file_path: Path to the .v file
        
    Returns:
        True if restored, False if no backup exists.
    """
    file_path = Path(file_path)
    backup_path = file_path.with_suffix('.v.backup')
    
    if backup_path.exists():
        shutil.copy2(backup_path, file_path)
        backup_path.unlink()
        return True
    return False


def get_example_file() -> Path:
    """Get path to the standard example.v test file."""
    return PROJECT_ROOT / "examples" / "example.v"


TEMP_EXAMPLE_ROOT = Path(tempfile.gettempdir()) / "autorocq-test-examples"


def temp_example_copy(name: str) -> Path:
    """
    Copy an example .v file to a stable temp path and return the copy.

    Tests must never run against the tracked files in examples/.

    The copy lives under a *fixed* directory for better coqpyt caching.

    examples/_CoqProject is copied alongside it. The examples need it to
    resolve their libframac imports, and a test driving coqpyt's ProofFile
    directly has nothing that would regenerate it -- test_coqpyt_svcomp is the
    one that would otherwise fail to load with "pop from empty list". A
    CoqInterface with auto_setup_coqproject rewrites it with the same content.

    Args:
        name: File name under examples/, e.g. "example.v".

    Returns:
        Path to the writable copy.
    """
    src = PROJECT_ROOT / "examples" / name

    caller = inspect.currentframe().f_back
    owner = Path(caller.f_globals.get("__file__", "shared")).stem

    tmp_dir = TEMP_EXAMPLE_ROOT / owner
    tmp_dir.mkdir(parents=True, exist_ok=True)

    dst = tmp_dir / src.name
    shutil.copyfile(src, dst)

    coqproject = PROJECT_ROOT / "examples" / "_CoqProject"
    if coqproject.exists():
        shutil.copyfile(coqproject, tmp_dir / "_CoqProject")

    return dst
