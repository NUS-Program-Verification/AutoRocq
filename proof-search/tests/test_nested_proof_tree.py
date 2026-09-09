from agent.proof_controller import ProofController
from agent.proof_tree import ProofTree


def test_nested_branching_does_not_duplicate_background_goals():
    controller = ProofController.__new__(ProofController)
    controller.logger = ProofTree().logger
    controller.proof_tree = ProofTree()
    controller.global_step_id = 0
    controller.proof_tree.add_node(
        tactic="Proof.",
        goals_before="A /\\ B /\\ C",
        goals_after="A /\\ B /\\ C",
        hypotheses_before="",
        hypotheses_after="",
        step_number=0,
        subgoals_after=["A /\\ B /\\ C"],
    )

    def update(before, after, tactic):
        controller.global_step_id += 1
        controller._update_proof_tree(
            before,
            after,
            tactic,
            before[0],
            after[0] if after else "",
            "",
            "",
        )

    update(["A /\\ B /\\ C"], ["A", "B /\\ C"], "split.")
    update(["A", "B /\\ C"], ["A1", "A2", "B /\\ C"], "split.")

    assert len(controller.proof_tree.open_subgoals) == 3

    update(["A1", "A2", "B /\\ C"], ["A2", "B /\\ C"], "exact proof_A1.")
    update(["A2", "B /\\ C"], ["B /\\ C"], "exact proof_A2.")
    update(["B /\\ C"], [], "exact proof_BC.")

    assert controller.proof_tree.to_dict()["metadata"]["open_subgoals_count"] == 0
