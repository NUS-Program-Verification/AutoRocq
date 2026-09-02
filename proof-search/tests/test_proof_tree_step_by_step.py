"""
The proof tree ProofController maintains as tactics land: one node per linear
tactic, and a branch with an open-subgoal placeholder per goal when a tactic
splits the proof.

The old version applied the same seven tactics, printed the tree after each one
and saved a PNG, then returned True -- which pytest ignores. Its only real
check was `raise Exception(...)` on a rejected tactic, and that was caught two
lines later by the blanket `except Exception` that returned False. So a run in
which every tactic was refused passed exactly like one where all seven landed.
"""

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from agent.context_manager import ContextManager
from agent.proof_controller import ProofController
from agent.proof_tree import ProofTree
from backend.coq_interface import CoqInterface
from tests.test_utils import skip_if_libraries_missing, temp_example_copy
from utils.config import ProofAgentConfig

config_file = PROJECT_ROOT / "configs" / "default_config.json"

# Steps 1-2 and 4-7 are linear; step 3 is the assert that splits the proof into
# the asserted lemma and the continuation.
TACTICS = [
    "intros t t1 t2 a i i1 i2 a1 a2.",
    "intros.",
    "assert (lor_disjoint_sum: forall x y:int, 0 <= x <= 15 -> (exists k:int, y = 16 * k) -> x + y = lor x y)",
    "{",
    "intros x0 y [Hx0_low Hx0_up] [k Hy_eq].",
    "subst y.",
    "rewrite Z.mul_comm.",
]
BRANCHING_STEP = 3


def count_nodes(node):
    return 0 if node is None else 1 + sum(count_nodes(c) for c in node.children)


@pytest.fixture(scope="module")
def walked(tmp_path_factory):
    """Replay the seven tactics once, recording the tree after each.

    Module-scoped: loading hex2bin_assert_3.v dominates the runtime, and every
    test below reads the same recording.
    """
    config = ProofAgentConfig.from_file(str(config_file))
    skip_if_libraries_missing(config)

    coq_file = temp_example_copy("hex2bin_assert_3.v")
    output_dir = tmp_path_factory.mktemp("proof_tree")

    coq = CoqInterface(
        file_path=str(coq_file),
        workspace=config.coq.workspace or str(coq_file.parent),
        library_paths=config.coq.library_paths,
        auto_setup_coqproject=config.coq.auto_setup_coqproject,
        timeout=config.coq.timeout,
    )
    assert coq.load(), f"load() failed: {coq.get_last_error()}"

    try:
        controller = ProofController(
            coq_interface=coq,
            context_manager=ContextManager(
                coq_interface=coq, api_key=config.llm.api_key
            ),
            max_steps=100,
            enable_recording=False,
            output_dir=str(output_dir),
        )
        controller.current_theorem_name = "hex2bin_assert_3"
        controller.step_count = 0
        controller.successful_tactics = []
        controller.proof_tree = ProofTree()

        goals = coq.get_goal_str()
        hypotheses = coq.get_hypothesis()
        controller.proof_tree.add_node(
            tactic="Proof.",
            goals_before=goals.strip(),
            goals_after=goals.strip(),
            hypotheses_before=hypotheses.strip(),
            hypotheses_after=hypotheses.strip(),
            step_number=0,
            subgoals_after=coq.get_subgoals(),
        )

        # step number -> (nodes, open subgoals, subgoals before, subgoals after)
        shape = {0: (count_nodes(controller.proof_tree.root), 1, None, None)}

        for step, tactic in enumerate(TACTICS, start=1):
            subgoals_before = coq.get_subgoals()
            goals_before = coq.get_goal_str()
            hypotheses_before = coq.get_hypothesis()

            assert controller._apply_tactic(tactic), (
                f"step {step}, {tactic[:50]!r} failed: {coq.get_last_error()}"
            )

            subgoals_after = coq.get_subgoals()
            controller.global_step_id = step
            controller._handle_successful_tactic(
                tactic,
                subgoals_before,
                subgoals_after,
                goals_before,
                coq.get_goal_str(),
                hypotheses_before,
                coq.get_hypothesis(),
            )
            shape[step] = (
                count_nodes(controller.proof_tree.root),
                len(controller.proof_tree.open_subgoals),
                len(subgoals_before),
                len(subgoals_after),
            )

        yield controller, shape, output_dir
    finally:
        coq.close()


def test_the_root_is_the_proof_step(walked):
    controller, shape, _ = walked

    assert controller.proof_tree.root is not None
    assert controller.proof_tree.root.tactic == "Proof."
    assert controller.proof_tree.root.step_number == 0
    assert shape[0][0] == 1, "the tree started with more than a root"


def test_every_tactic_was_recorded_in_order(walked):
    controller, _, _ = walked

    assert controller.successful_tactics == TACTICS
    assert controller.failed_tactics == []


def test_a_linear_tactic_adds_exactly_one_node(walked):
    _, shape, _ = walked

    for step in range(1, len(TACTICS) + 1):
        if step == BRANCHING_STEP:
            continue
        nodes_before = shape[step - 1][0]
        nodes_after = shape[step][0]
        assert nodes_after == nodes_before + 1, (
            f"step {step} ({TACTICS[step - 1][:40]!r}) added "
            f"{nodes_after - nodes_before} nodes"
        )


def test_the_branching_tactic_opens_a_placeholder_per_subgoal(walked):
    """`assert` splits the goal, and the tree has to show both branches."""
    _, shape, _ = walked

    nodes_before, open_before, _, _ = shape[BRANCHING_STEP - 1]
    nodes_after, open_after, subgoals_before, subgoals_after = shape[BRANCHING_STEP]

    assert (subgoals_before, subgoals_after) == (1, 2), (
        "the assert did not actually split the goal"
    )
    assert open_before == 1 and open_after == 2, (
        f"open subgoals went {open_before} -> {open_after}"
    )
    # The tactic node itself plus one placeholder for each of the two subgoals.
    assert nodes_after == nodes_before + 3, (
        f"branching added {nodes_after - nodes_before} nodes, expected 3"
    )


def test_the_rendered_tree_shows_the_script_and_the_open_branch(walked):
    controller, _, _ = walked
    rendered = controller.proof_tree.get_proof_tree_string()

    for tactic in TACTICS:
        assert tactic[:40] in rendered, f"{tactic[:40]!r} missing from the tree"

    assert "[Subgoal 1/2]" in rendered, rendered[:400]
    assert "[OPEN]" in rendered
    assert rendered.count("[APPLIED]") == len(TACTICS) + 1


def test_to_dict_reports_the_open_subgoals(walked):
    controller, _, _ = walked
    tree = controller.proof_tree.to_dict()

    assert tree["root"]["tactic"] == "Proof."
    assert tree["metadata"]["open_subgoals_count"] == 2
    assert tree["metadata"]["active_subgoal"] == TACTICS[-1]

    # The dict has to mirror the tree, not a summary of it.
    def count_dict(node):
        return 1 + sum(count_dict(c) for c in node["children"])

    assert count_dict(tree["root"]) == count_nodes(controller.proof_tree.root)


def test_the_tree_can_be_written_out_as_a_png(walked):
    controller, _, output_dir = walked

    controller.proof_tree.save_to_png(str(output_dir / "proof_tree_final"), prefix="run_")

    png = output_dir / "run_proof_tree_final.png"
    assert png.exists(), sorted(p.name for p in output_dir.iterdir())
    assert png.stat().st_size > 0
