"""Parsed Rocq dependencies determine the proof context shown to the LLM."""

import sys
from unittest.mock import Mock

import pytest
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tests.test_utils import (
    configure_test_library, create_coq_interface, create_proof_file, temp_example_copy,
)
from utils.coq_utils import extract_essential_proof_content
from utils.config import ProofAgentConfig
from agent.context_manager import ContextManager
from utils.logger import setup_logger

logger = setup_logger("test_extract_proof_content")

GOAL_FILE = PROJECT_ROOT / "examples" / "main_loop_invariant_2_established_Coq.v"


def extract(content, tmp_path):
    path = tmp_path / "context.v"
    path.write_text(content, encoding="utf-8")
    return extract_with_coqpyt(path)


@pytest.fixture(scope="module")
def extracted_goal(coq_factory):
    config = configure_test_library(
        ProofAgentConfig.from_file(str(PROJECT_ROOT / "configs" / "default_config.json"))
    )
    interface = coq_factory(temp_example_copy(GOAL_FILE.name), config=config)
    manager = ContextManager.__new__(ContextManager)
    manager.coq, manager.logger = interface, logger
    return manager.extract_essential_proof_content(interface.get_proof_file_content())


def extract_with_coqpyt(path):
    with create_proof_file(str(path), use_disk_cache=True) as proof_file:
        proof = proof_file.unproven_proofs[0]
        return extract_essential_proof_content(
            logger,
            path.read_text(encoding="utf-8"),
            proof=proof,
            file_context=proof_file.context,
            file_path=proof_file.path,
        )


def test_initial_prompt_resolves_parsed_dependencies_without_an_llm(tmp_path):
    # Program declarations require parsed context; the binder shadows a global.
    source = "\n".join(
        [
            "From Stdlib Require Import Program.",
            "Program Definition hidden_value : nat := 7.",
            "Definition used_value : nat := hidden_value.",
            "Definition unused_value : nat := 42.",
            "Theorem wp_goal : forall unused_value : nat, used_value = used_value.",
            "Proof.",
            "Admitted.",
        ]
    )
    path = tmp_path / "prompt_context.v"
    path.write_text(source, encoding="utf-8")
    interface = create_coq_interface(str(path), timeout=60)
    try:

        # Prompt construction needs the loaded proof, not a chat session.
        manager = ContextManager.__new__(ContextManager)
        manager.coq = interface
        manager.logger = logger
        manager.proof_plan = None
        prompt = manager.build_initial_prompt("")

        assert "Program Definition hidden_value : nat := 7." in prompt
        assert "Definition used_value : nat := hidden_value." in prompt
        assert "Definition unused_value" not in prompt
        assert prompt.count("Theorem wp_goal") == 1
        assert prompt.index("Program Definition hidden_value") < prompt.index(
            "Definition used_value"
        )
    finally:
        interface.close()


def test_a_why3_goal_file_keeps_its_imports_theorem_and_used_definitions(extracted_goal):
    """The three things the prompt cannot do without, on the real fixture."""
    extracted = extracted_goal

    assert "Require Import BuiltIn." in extracted
    assert "From Stdlib Require Import ZArith Lia." in extracted
    assert "Open Scope Z_scope." in extracted

    assert "Theorem wp_goal :" in extracted
    assert "is_sint32 i ->" in extracted
    assert "Proof." in extracted

    assert "Definition is_sint32" in extracted


def test_definitions_the_theorem_never_mentions_are_dropped(extracted_goal):
    """Keep the prompt substantially smaller than the source file."""
    content = GOAL_FILE.read_text(encoding="utf-8")
    extracted = extracted_goal

    for unused in [
        "Definition is_uint8",
        "Definition is_sint8",
        "Definition is_sint64",
        "Definition real_of_int",
        "Parameter zlt:",
        "Parameter to_sint64:",
        "Axiom cmod_remainder",
    ]:
        assert unused not in extracted, f"{unused!r} survived but is unused"

    assert len(extracted) < len(content) / 4, (
        f"barely trimmed anything: {len(content)} -> {len(extracted)}"
    )


def test_why3_comments_are_stripped(extracted_goal):
    extracted = extracted_goal

    assert "(* Why3 goal *)" not in extracted
    assert "(* Why3 assumption *)" not in extracted
    assert "Beware! Only edit allowed sections" not in extracted


def test_transitive_dependencies_are_followed(tmp_path):
    """A definition the theorem reaches only through another must be kept."""
    source = "\n".join(
        [
            "From Stdlib Require Import ZArith.",
            "Open Scope Z_scope.",
            "",
            "Definition is_small (x:Z) : Prop := (0 <= x)%Z.",
            "",
            "Definition is_tiny (x:Z) : Prop := is_small x /\\ (x < 8)%Z.",
            "",
            "Definition is_unrelated (x:Z) : Prop := (x < 0)%Z.",
            "",
            "Theorem t : forall (x:Z), is_tiny x -> (0 <= x)%Z.",
            "Proof.",
            "Admitted.",
        ]
    )

    extracted = extract(source, tmp_path)

    assert "Definition is_tiny" in extracted, "the direct dependency is missing"
    assert "Definition is_small" in extracted, "the transitive dependency is missing"
    assert "Definition is_unrelated" not in extracted
    assert "Theorem t :" in extracted
    assert "From Stdlib Require Import ZArith." in extracted


def test_inductive_dependencies_are_kept(tmp_path):
    source = "\n".join(
        [
            "Inductive addr :=",
            "  | addr'mk : nat -> addr.",
            "Definition address_value (a : addr) : nat :=",
            "  match a with addr'mk n => n end.",
            "Theorem wp_goal : forall a : addr, address_value a = address_value a.",
            "Proof.",
            "Admitted.",
        ]
    )

    extracted = extract(source, tmp_path)

    assert "Inductive addr" in extracted
    assert "addr'mk : nat -> addr" in extracted
    assert "Definition address_value" in extracted


def test_coqpyt_context_handles_declaration_forms_and_transitive_dependencies(
    tmp_path, caplog
):
    source = "\n".join(
        [
            "From Stdlib Require Import Arith.",
            "Inductive addr :=",
            "  | addr'mk : nat -> addr.",
            "Record box := { unbox : addr }.",
            "Fixpoint countdown (n : nat) : nat :=",
            "  match n with O => O | S n' => countdown n' end.",
            "Definition address_value (a : addr) : nat :=",
            "  match a with addr'mk n => countdown n end.",
            "Definition boxed_value (b : box) : nat := address_value (unbox b).",
            "Definition unused_value : nat := 42.",
            "Theorem earlier : True. Proof. exact I. Qed.",
            "Theorem wp_goal : forall (b : box), boxed_value b = boxed_value b.",
            "Proof.",
            "Admitted.",
        ]
    )
    path = tmp_path / "declarations.v"
    path.write_text(source, encoding="utf-8")

    extracted = extract_with_coqpyt(path)

    expected = [
        "Inductive addr",
        "Record box",
        "Fixpoint countdown",
        "Definition address_value",
        "Definition boxed_value",
        "Theorem wp_goal",
    ]
    positions = [extracted.index(fragment) for fragment in expected]
    assert positions == sorted(positions)
    assert "addr'mk : nat -> addr" in extracted
    assert "Definition unused_value" not in extracted
    assert "Theorem earlier" not in extracted
    assert "Missing definitions for theorem" not in caplog.text


def test_coqpyt_context_deduplicates_an_inductive_and_its_constructor(tmp_path):
    source = "\n".join(
        [
            "Inductive addr :=",
            "  | addr'mk : nat -> addr.",
            "Theorem wp_goal : forall n, addr'mk n = addr'mk n.",
            "Proof.",
            "Admitted.",
        ]
    )
    path = tmp_path / "constructor.v"
    path.write_text(source, encoding="utf-8")

    extracted = extract_with_coqpyt(path)

    assert extracted.count("Inductive addr") == 1
    assert extracted.count("addr'mk : nat -> addr") == 1


@pytest.mark.parametrize("missing", ["proof", "file_context", "file_path"])
def test_missing_parsed_context_is_an_error(missing):
    inputs = dict(proof=object(), file_context=object(), file_path="/proof.v")
    inputs[missing] = None
    log = Mock()
    with pytest.raises(ValueError, match=f"{missing} missing"):
        extract_essential_proof_content(log, "Theorem t : True.", **inputs)
    log.error.assert_called_once()


def test_coqpyt_extraction_failure_is_not_hidden(monkeypatch):
    def fail(*args):
        raise LookupError("unresolved declaration")

    monkeypatch.setattr("utils.coq_utils._structured_dependencies", fail)
    with pytest.raises(RuntimeError, match="unresolved declaration") as error:
        extract_essential_proof_content(
            Mock(), "Theorem t : True.", proof=object(),
            file_context=object(), file_path="/proof.v",
        )
    assert isinstance(error.value.__cause__, LookupError)


def test_initial_prompt_requires_loaded_coqpyt_context():
    manager = ContextManager.__new__(ContextManager)
    manager.coq = Mock(proof=None, proof_file=None, file_path="/proof.v")
    manager.coq.get_proof_file_content.return_value = "Theorem t : True."
    manager.logger = Mock()
    with pytest.raises(ValueError, match="proof, file_context missing"):
        manager.build_initial_prompt("")


def test_the_goal_is_not_emitted_as_its_own_dependency(tmp_path):
    source = "\n".join(
        [
            "From Stdlib Require Import ZArith.",
            "Definition is_small (x:Z) : Prop := (0 <= x)%Z.",
            "Theorem wp_goal : forall (x:Z), is_small x -> (0 <= x)%Z.",
            "Proof.",
            "Admitted.",
        ]
    )

    extracted = extract(source, tmp_path)

    assert extracted.count("Theorem wp_goal") == 1
    assert "Definition is_small" in extracted
