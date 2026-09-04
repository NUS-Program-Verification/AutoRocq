from pathlib import Path
from types import SimpleNamespace

from backend.coq_interface import CoqInterface
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


def _interface_with_goal_config(monkeypatch, **goal_fields):
    interface = object.__new__(CoqInterface)
    config = SimpleNamespace(
        goals=goal_fields.get("goals", []),
        stack=goal_fields.get("stack", []),
        shelf=goal_fields.get("shelf", []),
        given_up=goal_fields.get("given_up", []),
    )
    answer = SimpleNamespace(goals=config)
    monkeypatch.setattr(interface, "_get_current_goals_cached", lambda: answer)
    return interface


def test_goal_count_ignores_empty_stack_frames(monkeypatch):
    interface = _interface_with_goal_config(monkeypatch, stack=[([], [])])
    assert not interface.has_open_goals()


def test_every_unresolved_goal_category_blocks_completion(monkeypatch):
    marker = object()
    cases = [
        {"goals": [marker]},
        {"stack": [([marker], [])]},
        {"stack": [([], [marker])]},
        {"shelf": [marker]},
        {"given_up": [marker]},
    ]

    for fields in cases:
        interface = _interface_with_goal_config(monkeypatch, **fields)
        assert interface.has_open_goals(), fields
