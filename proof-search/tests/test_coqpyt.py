import sys
import os
from pathlib import Path

from coqpyt.coq.proof_file import ProofFile
from coqpyt.coq.exceptions import InvalidChangeException


def clean_proof_file(file_path):
    """Clean the proof file by removing everything after 'Proof.'"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        proof_pos = content.find("Proof.")
        if proof_pos == -1:
            print("❌ 'Proof.' not found in file")
            return False
        
        clean_content = content[:proof_pos + len("Proof.")] + "\n"
        
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(clean_content)
        
        print("✅ Proof file cleaned successfully")
        return True
        
    except Exception as e:
        print(f"❌ Error cleaning file: {e}")
        return False

file_path = os.path.join(os.getcwd(), "examples/example.v")
# Clean the proof file first
clean_proof_file(file_path)

with ProofFile(os.path.join(os.getcwd(), "examples/example.v")) as proof_file:
    proof_file.run()
    # Get the first admitted proof
    unproven = proof_file.unproven_proofs[0]
    # Steps for an incorrect proof
    incorrect = [" reflexivity.", "\nQed."]
    # Steps for a correct proof
    correct = [" rewrite app_assoc."] + incorrect

    # Important: always start with the ""
    correct = [
        "  intros b.",
        "  destruct b.",
        "  simpl.",
        "  reflexivity.",
        "  simpl.",
        "  reflexivity.",
        "  Qed.",
    ]

    # Loop through both attempts
    for attempt in [correct, correct]:
        # Remove the "\nAdmitted." step
        #proof_file.pop_step(unproven)
        try:
            # Append all steps in the attempt
            for i, s in enumerate(attempt):
                proof_file.append_step(unproven, s)
            print("Proof succeeded!")
            break
        except InvalidChangeException:
            # Some step was invalid, so we rollback the previous changes
            [proof_file.pop_step(unproven) for _ in range(i)]
            proof_file.append_step(unproven, "\nAdmitted.")
            print("Proof attempt not valid.")
        break