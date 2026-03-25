import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.coq_interface import CoqInterface
from agent.proof_tree import ProofState

if __name__ == "__main__":
    file_path = str(PROJECT_ROOT / "examples" / "example.v")
    coq = CoqInterface(file_path)
    coq.load()

    print("== Initial proof steps ==")
    coq.print_steps()
    coq.print_goals()

    tactics = [
        "intros n m.",
        "rewrite -> (plus_O_n (S n * m)).",
        "reflexivity.",
        "Qed."
    ]
    applied_tactics = []
    states = []

    print("\n== Stepwise proof application with ProofState tracking ==")
    for i, tac in enumerate(tactics, 1):
        print(f"\nStep {i}: Applying tactic: {tac}")
        tac = "\n   " + tac
        ok = coq.apply_tactic(tac)
        applied_tactics.append(tac.strip())
        goal = coq.get_goal_str()      # You might need to adapt this
        hypo = coq.get_hypothesis()    # Or use a dummy, e.g., []
        state = ProofState(
            step_idx=i,
            current_goal=goal,
            hypothesis=hypo,
            applied_tactics=list(applied_tactics)
        )
        states.append(state)
        state.pretty_print()   # <-- Print all attributes here
        if not ok:
            print(f"Error: Tactic {tac!r} could not be applied.")
        coq.print_steps()
        coq.print_goals()

    if coq.is_proof_complete():
        print("\n✅ Proof completed with Qed.")
    else:
        print("\n❌ Proof not completed.")

    coq.close()
