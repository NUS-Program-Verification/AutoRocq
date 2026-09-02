"""
extract_essential_proof_content: the context trimmer that decides what the LLM
gets to see of a Why3-generated goal file.

This is pure text processing -- ContextManager.extract_essential_proof_content
just forwards to utils.coq_utils with its logger -- so these tests call the
function directly. The old version stood up a whole coq-lsp session and a
ContextManager (and so needed the libraries and an API key) to reach it, then
collected its four checks into a dict, printed a tick or a cross for each and
returned the conjunction. pytest ignores that return, so every check could fail
and the test still passed.
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from utils.coq_utils import (
    extract_essential_proof_content,
    find_transitive_dependencies,
)
from utils.logger import setup_logger

logger = setup_logger("test_extract_proof_content")

GOAL_FILE = PROJECT_ROOT / "examples" / "main_loop_invariant_2_established_Coq.v"


def extract(content):
    return extract_essential_proof_content(logger, content)


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
