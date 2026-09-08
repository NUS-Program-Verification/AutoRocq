import signal
from pathlib import Path

import pytest

import main as main_module
from backend.coq_interface import CoqInterface
from utils.logger import setup_logger
from utils.scratch import ScratchProof


def test_save_uses_flat_numeric_suffixes(tmp_path):
    source = tmp_path / "a.v"
    source.write_text("Theorem a : True. Proof. exact I. Qed.")
    results = tmp_path / "results"

    scratch = ScratchProof(source)
    scratch.open()
    try:
        saved = [scratch.save(results) for _ in range(3)]
    finally:
        scratch.close()

    assert [path.name for path in saved] == ["a.v", "a.1.v", "a.2.v"]


def test_close_preserves_source_and_removes_scratch_artifacts(tmp_path):
    source = tmp_path / "proof.v"
    original = b"Theorem proof : True. Proof. exact I. Qed.\n"
    source.write_bytes(original)

    coq = CoqInterface(str(source))
    scratch = Path(coq.file_path)
    scratch.write_text("changed")

    artifacts = [
        scratch.with_suffix(".vo"),
        scratch.with_suffix(".vok"),
        scratch.with_suffix(".vos"),
        scratch.with_suffix(".glob"),
        scratch.with_name(f".{scratch.stem}.aux"),
    ]
    for artifact in artifacts:
        artifact.touch()

    coq.close()

    assert source.read_bytes() == original
    assert not scratch.exists()
    assert not any(path.exists() for path in artifacts)


def test_source_path_and_scratch_use_the_resolved_source(tmp_path):
    source_dir = tmp_path / "source"
    link_dir = tmp_path / "links"
    source_dir.mkdir()
    link_dir.mkdir()
    source = source_dir / "proof.v"
    source.write_text("Theorem proof : True. Proof. exact I. Qed.")
    link = link_dir / "alias.v"
    link.symlink_to(source)

    coq = CoqInterface(str(link))
    try:
        assert Path(coq.source_path) == source.resolve()
        assert Path(coq.file_path).parent == source.parent.resolve()
    finally:
        coq.close()


def test_clean_proof_file_does_not_create_a_backup(tmp_path):
    source = tmp_path / "proof.v"
    source.write_text("Theorem proof : True. Proof. exact I. Qed.\n")

    assert main_module.clean_proof_file(str(source), setup_logger("test_scratch"))
    assert source.read_text().endswith("Proof.\nAdmitted.")
    assert not Path(f"{source}.backup").exists()


def test_interface_cleaning_does_not_create_a_backup(tmp_path):
    source = tmp_path / "proof.v"
    source.write_text("Theorem proof : True. Proof. exact I. Qed.\n")

    coq = CoqInterface(str(source))
    scratch = Path(coq.file_path)
    try:
        assert coq.clear_all_proof_scripts()
        assert not scratch.with_suffix(".v.backup").exists()
    finally:
        coq.close()


def test_signal_before_output_directory_setup_exits_cleanly(monkeypatch):
    handlers = {}
    monkeypatch.setattr(
        main_module.signal,
        "signal",
        lambda signum, handler: handlers.__setitem__(signum, handler),
    )

    def interrupt_during_argument_parsing():
        handlers[signal.SIGINT](signal.SIGINT, None)

    monkeypatch.setattr(main_module, "parse_arguments", interrupt_during_argument_parsing)

    with pytest.raises(SystemExit) as stopped:
        main_module.main()

    assert stopped.value.code == 128 + signal.SIGINT
