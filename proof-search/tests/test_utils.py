import shutil
from pathlib import Path
from typing import Optional

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

