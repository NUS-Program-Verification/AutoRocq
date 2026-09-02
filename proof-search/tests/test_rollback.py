"""
reset_by_step(): popping the proof back to an earlier step and replaying
forward. This is what the controller runs when the LLM walks into a dead end,
so "the state after rollback is the state we recorded" is the whole contract.

The old version printed that contract instead of asserting it -- "⚠️ Step count
mismatch: expected 4, got 6", "⚠️ State mismatch (may be normal due to
formatting)" -- and returned True at the end whatever it had printed. It also
`continue`d past any rollback target it decided was invalid, so a reset_by_step
that refused every call still finished with "🎉 All rollback tests completed
successfully!".
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

# Step 1 is "Proof.", so these land on steps 2 through 6.
TACTICS = [
    "\n intros i_1 i Hle Hlow Hup Hup_i Hsint.",
    "\n assert (Hrange: -9 <= i <= 9) by lia.",
    "\n destruct Hrange as [Hi_low Hi_up].",
    "\n Search Z.abs.",
    "\n assert (Hi_abs_le : Z.abs i <= 9) by now apply Z.abs_le.",
]
FIRST_TACTIC_STEP = 2


@pytest.fixture(scope="module")
def replayed():
    """One session with all five tactics applied, plus the state after each.

    Module-scoped because loading this goal file dominates the runtime. The
    tests below run in order against it: they roll the same session back and
    forward, which is exactly the behaviour under test.

    The file is left as the tracked copy -- load() pops the trailing
    "Admitted." itself, and rewriting it first would only cost a cold
    re-elaboration by changing what coqpyt's disk cache is keyed on.
    """
    config = ProofAgentConfig.from_file(str(config_file))
    skip_if_libraries_missing(config)

    coq_file = temp_example_copy("main_loop_invariant_2_established_Coq.v")
    coq = CoqInterface(
        file_path=str(coq_file),
        workspace=config.coq.workspace or str(coq_file.parent),
        library_paths=config.coq.library_paths,
        auto_setup_coqproject=config.coq.auto_setup_coqproject,
        coqproject_extra_options=config.coq.coqproject_extra_options,
        timeout=config.coq.timeout,
    )
    assert coq.load(), f"load() failed: {coq.get_last_error()}"

    try:
        # step number -> the goal string that step leaves behind
        states = {1: coq.get_goal_str()}

        for offset, tactic in enumerate(TACTICS):
            step_number = FIRST_TACTIC_STEP + offset
            assert coq.apply_tactic(tactic), (
                f"step {step_number}, {tactic.strip()[:50]!r} failed: "
                f"{coq.get_last_error()}"
            )
            assert coq.get_current_step_number() == step_number
            states[step_number] = coq.get_goal_str()

        yield coq, states
    finally:
        coq.close()


def test_every_step_left_a_distinct_state(replayed):
    """Rollback is only meaningful if the steps actually differ."""
    coq, states = replayed

    assert coq.get_current_step_number() == FIRST_TACTIC_STEP + len(TACTICS) - 1
    assert len(states) == len(TACTICS) + 1

    # `Search Z.abs.` is a query: it is a real step but changes no goal, so the
    # states either side of it are equal. Every other step moves the proof.
    changing = [s for s in sorted(states) if s != 5]
    assert len(set(states[s] for s in changing)) == len(changing), (
        "two tactics left identical goals"
    )
    assert states[5] == states[4], "a Search command changed the goal"


@pytest.mark.parametrize("target", [4, 2, 1])
def test_reset_by_step_restores_the_recorded_state(replayed, target):
    """Popping back to a step has to reproduce that step's goal exactly."""
    coq, states = replayed

    assert coq.get_current_step_number() > target, "nothing to roll back"
    assert coq.reset_by_step(target), coq.get_last_error()

    assert coq.get_current_step_number() == target, (
        f"asked for step {target}, landed on {coq.get_current_step_number()}"
    )
    assert coq.get_goal_str() == states[target], (
        f"step {target}: goal after rollback differs from the recorded state"
    )

    steps = [s.text.strip() for s in coq.proof.steps]
    assert len(steps) == target
    assert steps[0] == "Proof."


def test_replaying_forward_lands_back_on_the_same_state(replayed):
    """After the rollbacks above the session is at step 1; walk it forward."""
    coq, states = replayed

    assert coq.get_current_step_number() == 1, "the rollback tests left step 1"

    for offset, tactic in enumerate(TACTICS):
        step_number = FIRST_TACTIC_STEP + offset
        assert coq.apply_tactic(tactic), (
            f"replaying step {step_number} failed: {coq.get_last_error()}"
        )
        assert coq.get_current_step_number() == step_number
        assert coq.get_goal_str() == states[step_number], (
            f"replayed step {step_number} produced a different goal"
        )


def test_reset_by_step_refuses_targets_it_cannot_reach(replayed):
    """The guards, and the promise that a refusal changes nothing."""
    coq, _ = replayed

    current = coq.get_current_step_number()
    goal_before = coq.get_goal_str()

    # Step 1 is "Proof."; anything below it would pop the proof open.
    assert not coq.reset_by_step(0)
    assert "must be >=" in coq.get_last_error(), coq.get_last_error()

    assert not coq.reset_by_step(current + 5)
    assert "current proof has" in coq.get_last_error(), coq.get_last_error()

    assert coq.get_current_step_number() == current, "a refused reset moved the proof"
    assert coq.get_goal_str() == goal_before

    # Asking for where you already are is a no-op success.
    assert coq.reset_by_step(current), coq.get_last_error()
    assert coq.get_current_step_number() == current
