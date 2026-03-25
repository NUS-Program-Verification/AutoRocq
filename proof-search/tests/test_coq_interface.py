import os
import sys
from pathlib import Path

# Add the parent directory to Python path so we can import backend modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.coq_interface import CoqInterface


if __name__ == "__main__":
    # Use absolute path relative to the script location
    script_dir = Path(__file__).parent
    file_path = script_dir.parent / "examples" / "example.v"
    
    if not file_path.exists():
        print(f"Error: Example file not found at {file_path}")
        sys.exit(1)
    
    coq = CoqInterface(str(file_path))
    coq.load()
    #coq.clear_all_proof_scripts() # <--- This will clear all tactics, leaving just "Proof."
    #coq.proof_file.run()  # Re-parse the file

    print("== Initial proof steps ==")
    coq.print_steps()
    coq.print_goals()

    print("\n== Show all context terms ==")
    terms = coq.get_context_terms()
    #print([name for name in terms])

    print("\n== Show notation terms only ==")
    notations = coq.get_notations()
    #print([n.name for n in notations])

    tactics = [
        "intros.",
        "intros n m.",
        "rewrite -> (plus_O_n (S n * m)).",
        "reflexivity.",
        "Qed."
    ]

    print("\n== Stepwise proof application ==")
    for i, tac in enumerate(tactics, 1):
        print(f"\nStep {i}: Applying tactic: {tac}")
        tac = "\n  " + tac
        ok = coq.apply_tactic(tac)
        coq.print_steps()
        coq.print_goals()
        if not ok:
            print(f"Error: Tactic {tac!r} could not be applied.")

    # Final status
    if coq.is_proof_complete():
        print("\n✅ Proof completed with Qed.")
    else:
        print("\n❌ Proof not completed.")

    coq.close()
    print("Test completed successfully!")