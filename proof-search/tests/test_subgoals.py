"""
get_subgoals(): the structured view of the proof state that ProofController
diffs to decide how the proof tree branches.
"""

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tests.test_utils import configure_test_library, temp_example_copy
from utils.config import ProofAgentConfig

config_file = PROJECT_ROOT / "configs" / "default_config.json"


@pytest.fixture(scope="module")
def _shared_coq(coq_factory):
    config = configure_test_library(ProofAgentConfig.from_file(str(config_file)))

    coq_file = temp_example_copy("main_loop_invariant_2_established_Coq.v")
    return coq_factory(coq_file, config=config)


@pytest.fixture
def coq(_shared_coq):
    yield _shared_coq
    assert _shared_coq.reset_by_step(1), _shared_coq.get_last_error()


@pytest.fixture
def introduced_coq(coq):
    assert coq.apply_tactic("intros."), coq.get_last_error()
    return coq


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

    ty_after = str(subgoals_after[0].ty)
    assert "forall" not in ty_after, ty_after
    assert "i1 * i1 <= 99" in ty_after, ty_after
    assert ty_after != str(subgoals_before[0].ty)


def test_get_hypothesis_renders_the_focused_context(introduced_coq):
    """The context comes off the goals; the proof's steps never carried it.

    Hypotheses live on `goals.goals[i].hyps`, which is what get_subgoals()
    reads. A ProofStep has no `hypotheses`, and its `context` is a List[Term]
    -- the definitions a step referenced, not the proof's hypotheses.
    """
    coq = introduced_coq
    focused = coq.get_subgoals()[0]
    assert focused.hyps, "the context is gone; this test is moot"

    hypotheses = coq.get_hypothesis()
    assert hypotheses, "get_hypothesis() is still empty"
    assert hypotheses == coq.get_raw_hypothesis(), "nothing here needs ANSI cleaning"

    lines = hypotheses.splitlines()
    assert len(lines) == len(focused.hyps), (
        f"{len(lines)} lines rendered for {len(focused.hyps)} hypotheses"
    )

    for hyp, line in zip(focused.hyps, lines):
        for name in hyp.names:
            assert name in line, f"{name!r} missing from {line!r}"
        assert str(hyp.ty) in line, f"{hyp.ty!r} missing from {line!r}"

    names = [name for hyp in focused.hyps for name in hyp.names]
    assert len(names) == 8, names
    for name in names:
        assert name in hypotheses, f"{name!r} never reached the rendered context"


def test_the_context_is_not_the_goal(introduced_coq):
    """The two halves of the state the agent prompts with must stay distinct."""
    coq = introduced_coq
    hypotheses = coq.get_hypothesis()
    conclusion = str(coq.get_subgoals()[0].ty)

    assert conclusion not in hypotheses, "the conclusion leaked into the context"
    assert "i1 * i1 <= 99" in conclusion, conclusion
    assert "i1 * i1 <= 99" not in hypotheses, hypotheses
