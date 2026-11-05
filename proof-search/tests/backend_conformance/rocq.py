import subprocess

from prover_backends.rocq.backend import RocqBackend
from prover_backends.rocq.session import RocqSession, RocqSessionDesync
from tests.backend_conformance import BackendCase, SharedWitnessCase


def create_case(directory, scenario):
    statements = {
        "branch": "forall P : Prop, P -> P /\\ P",
        "shared_witness": "exists n : nat, n = 2 /\\ n + 0 = 2",
    }
    source = directory / "contract.v"
    source.write_text(f"Theorem contract : {statements[scenario]}.\nProof.\nAdmitted.\n")
    backend = RocqBackend(RocqSession(str(source)))

    def verify_export(content):
        # A compiler accepts Admitted, so also check the theorem's assumptions.
        exported = directory / "exported.v"
        exported.write_text(content + "\nPrint Assumptions contract.\n")
        result = subprocess.run(["coqc", str(exported)], capture_output=True,
                                text=True, timeout=30, cwd=directory)
        assert result.returncode == 0, result.stdout + result.stderr
        assert "Closed under the global context" in result.stdout, result.stdout

    if scenario == "shared_witness":
        return SharedWitnessCase(backend, source, "eexists.", "split.",
                                 "reflexivity.", verify_export)

    return BackendCase(
        backend=backend, source=source,
        introduce="intros P hp.", branch="split.",
        change_hypotheses="pose proof hp as extra.", focus_second="Focus 2.",
        solve_one="assumption.", solve_second="2: assumption.",
        solve_all="all: assumption.",
        rejected={
            "unknown": "exact missing_contract_term.",
            "partial_failure": "pose proof hp as extra; fail 1.",
            "admission": "admit.",
            "nested_admission": "split; admit.",
            "abort": "Abort.",
            "hidden_goal": "shelve.",
        },
        query="Check and.", query_identifier="and",
        missing_identifier="missing_contract_term",
        empty_search='Search "no_contract_lemma_has_this_name_781".',
        empty_result="No results found.",
        checkpoint_error=RocqSessionDesync,
        verify_export=verify_export,
    )
