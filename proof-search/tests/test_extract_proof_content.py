"""
extract_essential_proof_content: the context trimmer that decides what the LLM
gets to see of a Why3-generated goal file.

The fallback is pure text processing, while the runtime path uses CoqPyt's
parsed context to distinguish global references from binders and declaration
names. The old tests stood up a whole ContextManager and collected checks into
a returned boolean that pytest ignored, so every check could fail while the
test still passed.
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from utils.coq_utils import (
    extract_essential_proof_content,
    find_transitive_dependencies,
)
from coqpyt.coq.proof_file import ProofFile
from utils.logger import setup_logger

logger = setup_logger("test_extract_proof_content")

GOAL_FILE = PROJECT_ROOT / "examples" / "main_loop_invariant_2_established_Coq.v"


def extract(content):
    return extract_essential_proof_content(logger, content)


def extract_with_coqpyt(path):
    with ProofFile(str(path), workspace=str(path.parent)) as proof_file:
        proof_file.run()
        proof = proof_file.unproven_proofs[0]
        return extract_essential_proof_content(
            logger,
            path.read_text(encoding="utf-8"),
            proof=proof,
            file_context=proof_file.context,
            file_path=proof_file.path,
        )


def test_a_why3_goal_file_keeps_its_imports_theorem_and_used_definitions():
    """The three things the prompt cannot do without, on the real fixture."""
    content = GOAL_FILE.read_text(encoding="utf-8")
    extracted = extract(content)

    # Imports: plain Require, From ... Require, and Open Scope all count.
    assert "Require Import BuiltIn." in extracted
    assert "From Stdlib Require Import ZArith Lia." in extracted
    assert "Open Scope Z_scope." in extracted

    # The theorem itself, with its statement and the Proof. that follows.
    assert "Theorem wp_goal :" in extracted
    assert "is_sint32 i ->" in extracted
    assert "Proof." in extracted

    # wp_goal mentions is_sint32, so its definition has to come along.
    assert "Definition is_sint32" in extracted


def test_definitions_the_theorem_never_mentions_are_dropped():
    """The whole point is the size cut, so check what got left behind."""
    content = GOAL_FILE.read_text(encoding="utf-8")
    extracted = extract(content)

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


def test_why3_comments_are_stripped():
    content = GOAL_FILE.read_text(encoding="utf-8")
    extracted = extract(content)

    assert "(* Why3 goal *)" not in extracted
    assert "(* Why3 assumption *)" not in extracted
    assert "Beware! Only edit allowed sections" not in extracted


def test_transitive_dependencies_are_followed():
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

    extracted = extract(source)

    assert "Definition is_tiny" in extracted, "the direct dependency is missing"
    assert "Definition is_small" in extracted, "the transitive dependency is missing"
    assert "Definition is_unrelated" not in extracted
    assert "Theorem t :" in extracted
    assert "From Stdlib Require Import ZArith." in extracted


def test_a_file_with_no_theorem_says_so():
    extracted = extract("Require Import ZArith.\nDefinition d (x:Z) := x.\n")

    assert "current theorem not found" in extracted


def test_find_transitive_dependencies_closes_over_the_graph():
    definitions = {
        "a": {"lines": ["Definition a := b."], "dependencies": {"b"}},
        "b": {"lines": ["Definition b := c."], "dependencies": {"c"}},
        "c": {"lines": ["Definition c := 0."], "dependencies": set()},
        "unused": {"lines": ["Definition unused := 0."], "dependencies": set()},
    }

    assert find_transitive_dependencies({"a"}, definitions) == {"a", "b", "c"}
    assert find_transitive_dependencies({"c"}, definitions) == {"c"}
    assert find_transitive_dependencies(set(), definitions) == set()

    # A name with no definition is simply not resolvable, and must not raise.
    assert find_transitive_dependencies({"missing"}, definitions) == set()


def test_a_cycle_in_the_dependency_graph_terminates():
    definitions = {
        "a": {"lines": ["Definition a := b."], "dependencies": {"b"}},
        "b": {"lines": ["Definition b := a."], "dependencies": {"a"}},
    }

    assert find_transitive_dependencies({"a"}, definitions) == {"a", "b"}


def test_text_fallback_keeps_an_inductive_dependency():
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

    extracted = extract(source)

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
