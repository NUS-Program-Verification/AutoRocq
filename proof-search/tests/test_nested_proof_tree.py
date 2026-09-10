from agent.proof_controller import ProofController
from agent.proof_tree import ProofTree
from backend.coq_interface import CoqInterface


def make_controller(initial_goal):
    controller = ProofController.__new__(ProofController)
    controller.logger = ProofTree().logger
    controller.proof_tree = ProofTree()
    controller.global_step_id = 0
    controller.proof_tree.add_node(
        tactic="Proof.",
        goals_before=initial_goal,
        goals_after=initial_goal,
        hypotheses_before="",
        hypotheses_after="",
        step_number=0,
        subgoals_after=[initial_goal],
    )
    return controller


def update(controller, before, after, tactic):
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


def open_goals(controller):
    return [node.goals_after for node in controller.proof_tree.open_subgoals]


def find_tactic(node, tactic):
    if node.tactic == tactic:
        return node
    for child in node.children:
        found = find_tactic(child, tactic)
        if found is not None:
            return found
    return None


def test_nested_branching_preserves_count_order_and_tactic_attachments():
    controller = make_controller("(A /\\ B) /\\ C")

    update(controller, ["(A /\\ B) /\\ C"], ["A /\\ B", "C"], "split.")
    update(controller, ["A /\\ B", "C"], ["A", "B", "C"], "split.")

    assert open_goals(controller) == ["A", "B", "C"]

    update(controller, ["A", "B", "C"], ["B", "C"], "exact HA.")
    update(controller, ["B", "C"], ["C"], "exact HB.")
    update(controller, ["C"], [], "exact HC.")

    outer_split = controller.proof_tree.root.children[0]
    ab_branch, c_branch = outer_split.children
    inner_split = ab_branch.children[0]
    a_branch, b_branch = inner_split.children

    assert a_branch.children[0].tactic == "exact HA."
    assert b_branch.children[0].tactic == "exact HB."
    assert c_branch.children[0].tactic == "exact HC."
    assert controller.proof_tree.to_dict()["metadata"]["open_subgoals_count"] == 0


def test_nested_branching_handles_three_children_and_two_background_goals():
    controller = make_controller("F /\\ D /\\ E")

    update(controller, ["F /\\ D /\\ E"], ["F", "D", "E"], "outer_split.")
    background_nodes = controller.proof_tree.open_subgoals[1:]
    update(controller, ["F", "D", "E"], ["A", "B", "C", "D", "E"], "three_way_split.")

    assert open_goals(controller) == ["A", "B", "C", "D", "E"]
    assert controller.proof_tree.open_subgoals[-2:] == background_nodes


def test_identical_new_and_background_goals_keep_distinct_nodes():
    controller = make_controller("P /\\ P")

    update(controller, ["P /\\ P"], ["P", "P"], "split.")
    background_node = controller.proof_tree.open_subgoals[1]
    update(controller, ["P", "P"], ["P", "P", "P"], "split_focused_P.")

    assert open_goals(controller) == ["P", "P", "P"]
    assert controller.proof_tree.open_subgoals[-1] is background_node
    assert all(
        node is not background_node
        for node in controller.proof_tree.open_subgoals[:2]
    )


def test_live_nested_split_matches_coqpyt_order_and_tree_attachments(tmp_path):
    source = tmp_path / "nested_split.v"
    source.write_text(
        """Theorem nested_split (A B C : Prop) :
  A -> B -> C -> (A /\\ B) /\\ C.
Proof.
Admitted.
""",
        encoding="utf-8",
    )
    interface = CoqInterface(str(source))
    assert interface.load(), interface.get_last_error()

    try:
        initial_goals = interface.get_subgoals()
        controller = make_controller(str(initial_goals[0].ty))

        def apply(tactic):
            before = interface.get_subgoals()
            goals_before = interface.get_goal_str()
            hypotheses_before = interface.get_hypothesis()
            assert interface.apply_tactic(tactic), interface.get_last_error()
            after = interface.get_subgoals()
            controller.global_step_id += 1
            controller._update_proof_tree(
                before,
                after,
                tactic,
                goals_before,
                interface.get_goal_str(),
                hypotheses_before,
                interface.get_hypothesis(),
            )
            return before, after

        apply("intros HA HB HC.")
        apply("split.")
        before, after = apply("split.")

        assert [str(goal.ty) for goal in before] == ["A /\\ B", "C"]
        assert [str(goal.ty) for goal in after] == ["A", "B", "C"]
        assert open_goals(controller) == ["A", "B", "C"]

        apply("exact HA.")
        apply("exact HB.")
        apply("exact HC.")

        expected_parents = {
            "exact HA.": "A",
            "exact HB.": "B",
            "exact HC.": "C",
        }
        for tactic, expected_goal in expected_parents.items():
            tactic_node = find_tactic(controller.proof_tree.root, tactic)
            assert tactic_node is not None
            assert tactic_node.parent.goals_after == expected_goal
        assert not controller.proof_tree.open_subgoals
    finally:
        interface.close()
