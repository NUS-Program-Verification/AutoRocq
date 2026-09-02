"""
get_subgoals(): the structured view of the proof state that ProofController
diffs to decide how the proof tree branches.

The old version printed a before/after dump and a running commentary --
"❌ RESULT: Goals strings are IDENTICAL", "✅ RESULT: Added 6 new hypotheses" --
and returned True at the end regardless of which of those it had printed. Every
one of those comparisons is an assertion here instead.
"""

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.coq_interface import CoqInterface
from tests.test_utils import skip_if_libraries_missing, temp_example_copy
from utils.config import ProofAgentConfig

config_file = PROJECT_ROOT / "configs" / "default_config.json"


@pytest.fixture(scope="module")
def coq():
    """One session for this module.

    Loading this goal file is the expensive part, and the file is left exactly
    as the tracked copy -- load() pops the trailing "Admitted." itself, so
    there is nothing to reset first. Rewriting it beforehand only changes the
    content coqpyt's disk cache is keyed on and forces a cold re-elaboration.

    The workspace and library_paths are not optional: without the libframac
    mapping the statement does not typecheck and load() dies in coqpyt.
    """
    config = ProofAgentConfig.from_file(str(config_file))
    skip_if_libraries_missing(config)

    coq_file = temp_example_copy("main_loop_invariant_2_established_Coq.v")
    interface = CoqInterface(
        file_path=str(coq_file),
        workspace=config.coq.workspace or str(coq_file.parent),
        library_paths=config.coq.library_paths,
        auto_setup_coqproject=config.coq.auto_setup_coqproject,
        coqproject_extra_options=config.coq.coqproject_extra_options,
        timeout=config.coq.timeout,
    )
    assert interface.load(), f"load() failed: {interface.get_last_error()}"
    try:
        yield interface
    finally:
        interface.close()


# These two run in order against the one session: the first only reads, the
# second applies the tactic.


def test_the_opening_state_is_one_goal_with_no_hypotheses(coq):
    status = coq.get_proof_status()
    assert status["has_proof"], status
    assert status["proof_steps"] == 1, "load() left more than 'Proof.'"

    subgoals = coq.get_subgoals()
    assert len(subgoals) == 1, f"expected a single goal, got {len(subgoals)}"
    assert subgoals[0].hyps == [], "nothing has been introduced yet"

    ty = str(subgoals[0].ty)
    assert "forall i i1 : int" in ty, ty
    assert "is_sint32 i" in ty, ty
    assert "i1 * i1 <= 99" in ty, ty

    # Nothing has been introduced, so there is no context to render either.
    assert coq.get_hypothesis() == ""


def test_intros_moves_every_binder_into_the_hypotheses(coq):
    goals_before = coq.get_goal_str()
    subgoals_before = coq.get_subgoals()

    assert coq.apply_tactic("intros."), coq.get_last_error()

    subgoals_after = coq.get_subgoals()
    goals_after = coq.get_goal_str()

    assert goals_after != goals_before, "intros left the goal string unchanged"
    assert len(subgoals_after) == 1, "intros must not branch the proof"

    # wp_goal binds i and i1 and then takes six hypotheses.
    names = [name for hyp in subgoals_after[0].hyps for name in hyp.names]
    assert len(names) == 8, names
    assert len(subgoals_after[0].hyps) > len(subgoals_before[0].hyps)

    # What is left to prove is the conclusion alone.
    ty_after = str(subgoals_after[0].ty)
    assert "forall" not in ty_after, ty_after
    assert "i1 * i1 <= 99" in ty_after, ty_after
    assert ty_after != str(subgoals_before[0].ty)


def test_get_hypothesis_renders_the_focused_context(coq):
    """The context comes off the goals; the proof's steps never carried it.

    get_raw_hypothesis() used to read `hypotheses` or `context` off the proof's
    last step. A ProofStep has no `hypotheses`, and its `context` is a
    List[Term] -- the definitions and notations that step referenced, never the
    proof's hypotheses. So the second branch was taken and returned either ""
    (empty list, which is what this goal file gives, and what put
    "Hypotheses: None" in every prompt) or a rendering of whatever terms the
    step happened to touch, labelled as the context. Hypotheses have only ever
    been on the goals: goals.goals[i].hyps, which is what get_subgoals() reads.
    """
    focused = coq.get_subgoals()[0]
    assert focused.hyps, "the context is gone; this test is moot"

    hypotheses = coq.get_hypothesis()
    assert hypotheses, "get_hypothesis() is still empty"
    assert hypotheses == coq.get_raw_hypothesis(), "nothing here needs ANSI cleaning"

    lines = hypotheses.splitlines()
    assert len(lines) == len(focused.hyps), (
        f"{len(lines)} lines rendered for {len(focused.hyps)} hypotheses"
    )

    # Every name and every type the goal carries has to be in there, in order.
    for hyp, line in zip(focused.hyps, lines):
        for name in hyp.names:
            assert name in line, f"{name!r} missing from {line!r}"
        assert str(hyp.ty) in line, f"{hyp.ty!r} missing from {line!r}"

    names = [name for hyp in focused.hyps for name in hyp.names]
    assert len(names) == 8, names
    for name in names:
        assert name in hypotheses, f"{name!r} never reached the rendered context"


def test_the_context_is_not_the_goal(coq):
    """The two halves of the state the agent prompts with must stay distinct."""
    hypotheses = coq.get_hypothesis()
    conclusion = str(coq.get_subgoals()[0].ty)

    assert conclusion not in hypotheses, "the conclusion leaked into the context"
    assert "i1 * i1 <= 99" in conclusion, conclusion
    assert "i1 * i1 <= 99" not in hypotheses, hypotheses
