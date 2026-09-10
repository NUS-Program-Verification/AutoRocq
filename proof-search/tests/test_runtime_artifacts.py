from pathlib import Path

from main import setup_output_directory
from utils.scratch import ScratchProof


def test_scratch_restores_coqproject_in_explicit_workspace(tmp_path):
    source_dir = tmp_path / "source"
    workspace = tmp_path / "workspace"
    source_dir.mkdir()
    workspace.mkdir()
    source = source_dir / "proof.v"
    source.write_text("Lemma x : True. Proof. exact I. Qed.\n")
    coqproject = workspace / "_CoqProject"
    coqproject.write_text("original\n")

    scratch = ScratchProof(source, workspace=workspace)
    scratch.open()
    coqproject.write_text("generated\n")
    scratch.close()

    assert source.read_text() == "Lemma x : True. Proof. exact I. Qed.\n"
    assert coqproject.read_text() == "original\n"
    assert not scratch.path.exists()


def test_scratch_removes_generated_workspace_coqproject(tmp_path):
    source_dir = tmp_path / "source"
    workspace = tmp_path / "workspace"
    source_dir.mkdir()
    workspace.mkdir()
    source = source_dir / "proof.v"
    source.write_text("Lemma x : True. Proof. exact I. Qed.\n")

    scratch = ScratchProof(source, workspace=workspace)
    scratch.open()
    (workspace / "_CoqProject").write_text("generated\n")
    scratch.close()

    assert not (workspace / "_CoqProject").exists()


def test_default_output_directory_uses_parsed_proof_path(tmp_path):
    proof = tmp_path / "nested" / "proof.v"
    proof.parent.mkdir()

    output = setup_output_directory(None, str(proof))

    assert output.parent == proof.parent
    assert output.name.startswith("autorocq-")
    assert output.is_dir()
