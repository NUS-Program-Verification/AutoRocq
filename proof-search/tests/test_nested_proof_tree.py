from tests.test_utils import create_coq_interface
from agent.proof_controller import ProofController
from agent.proof_tree import ProofTree
from agent.context_manager import ContextManager
from backend.coq_interface import CoqInterface
from coqpyt.lsp.structs import Goal, Hyp
import pytest


def make_controller(initial_goal):
    controller = ProofController.__new__(ProofController)
    controller.logger = ProofTree().logger
    controller.proof_tree = ProofTree()
    controller.global_step_id = 0
    controller.successful_tactics = []
    controller.enable_recording = False
    controller.recorder = None
    controller.proof_tree.add_node(
        tactic="Proof.",
        goals_before=initial_goal,
        goals_after=initial_goal,
        hypotheses_before="",
        hypotheses_after="",
        step_number=0,
        subgoals_after=[Goal([], initial_goal, 0)],
    )
    return controller


def update(controller, before, after, tactic):
    def goal_text(goal):
        return str(goal.ty) if hasattr(goal, "ty") else str(goal)

    controller.global_step_id += 1
    ids = [node.goal_id for node in controller.proof_tree.open_subgoals]
    replacement_count = len(after) - len(before) + 1
    after_ids = [controller.global_step_id * 100 + i for i in range(replacement_count)] + ids[1:]
    def identified(goal, goal_id):
        if isinstance(goal, str):
            return Goal([], goal, goal_id)
        goal.goal_id = goal_id
        return goal
    before = [identified(goal, goal_id) for goal, goal_id in zip(before, ids)]
    after = [identified(goal, goal_id) for goal, goal_id in zip(after, after_ids)]
    controller._update_proof_tree(
        before,
        after,
        tactic,
        goal_text(before[0]),
        goal_text(after[0]) if after else "",
        "",
        "",
    )


def open_goals(controller):
    return [controller.proof_tree.current_goal(node)[0] for node in controller.proof_tree.open_subgoals]


def hypothesis_text(goal):
    return CoqInterface.format_hypotheses(goal)


def assert_frontier_matches_coqpyt(controller, interface):
    expected = [
        (str(goal.ty).strip(), hypothesis_text(goal))
        for goal in interface.get_subgoals()
    ]
    actual = [
        controller.proof_tree.current_goal(node)
        for node in controller.proof_tree.open_subgoals
    ]
    assert actual == expected
    assert [node.goal_id for node in controller.proof_tree.open_subgoals] == [
        goal.goal_id for goal in interface.get_subgoals()
    ]


def make_live_controller(interface):
    controller = ProofController.__new__(ProofController)
    controller.logger = ProofTree().logger
    controller.coq = interface
    controller.global_step_id = 0
    controller.successful_tactics = []
    controller.failed_tactics = []
    controller.query_commands = []
    controller.enable_recording = False
    controller.recorder = None
    controller._init_proof_tree()
    return controller


def apply_live(controller, tactic):
    interface = controller.coq
    before = interface.get_subgoals()
    goals_before = interface.get_goal_str()
    hypotheses_before = interface.get_hypothesis()
    assert controller._apply_tactic(tactic), interface.get_last_error()
    after = interface.get_subgoals()
    controller.global_step_id += 1
    state = controller._handle_successful_tactic(
        tactic,
        before,
        after,
        goals_before,
        interface.get_goal_str(),
        hypotheses_before,
        interface.get_hypothesis(),
    )
    assert state is not False
    assert_frontier_matches_coqpyt(controller, interface)
    return state


def load_live_proof(tmp_path, name, statement):
    source = tmp_path / f"{name}.v"
    source.write_text(
        f"Theorem {name} {statement}.\nProof.\nAdmitted.\n",
        encoding="utf-8",
    )
    interface = create_coq_interface(str(source))
    controller = make_live_controller(interface)
    assert_frontier_matches_coqpyt(controller, interface)
    return interface, controller


def find_tactic(node, tactic):
    if node.tactic == tactic:
        return node
    for child in node.children:
        found = find_tactic(child, tactic)
        if found is not None:
            return found
    return None


def is_ancestor(ancestor, node):
    while node is not None:
        if node is ancestor:
            return True
        node = node.parent
    return False


def test_initial_context_includes_the_current_proof_tree_without_an_llm():
    class ProofFileContext:
        @staticmethod
        def get_proof_file_content():
            return "Theorem paper_contract : True."

    manager = ContextManager.__new__(ContextManager)
    manager.coq = ProofFileContext()
    manager.proof_plan = None
    manager.extract_essential_proof_content = lambda content: content
    proof_tree = "0. Proof.\n   Goal: True\n   Status: Open"

    prompt = manager.build_initial_prompt(proof_tree)

    assert "## CURRENT PROOF TREE:\n" + proof_tree in prompt


def completed_nested_tree():
    controller = make_controller("(A /\\ B) /\\ C")
    update(controller, ["(A /\\ B) /\\ C"], ["A /\\ B", "C"], "split.")
    update(controller, ["A /\\ B", "C"], ["A", "B", "C"], "split.")
    update(controller, ["A", "B", "C"], ["B", "C"], "exact HA.")
    update(controller, ["B", "C"], ["C"], "exact HB.")
    update(controller, ["C"], [], "exact HC.")
    return controller


def test_linear_tactic_replaces_only_the_focused_frontier_node():
    controller = make_controller("A /\\ C")
    update(controller, ["A /\\ C"], ["A", "C"], "split.")
    background_node = controller.proof_tree.open_subgoals[1]

    update(controller, ["A", "C"], ["A'", "C"], "change A with A'.")

    assert open_goals(controller) == ["A'", "C"]
    assert controller.proof_tree.open_subgoals[1] is background_node


def test_branch_nodes_preserve_the_complete_goal_expression():
    controller = make_controller("compound goal")
    implication = Goal([], "A -> B")
    let_expression = Goal([], "let x := 1 in x = x")

    update(
        controller,
        ["compound goal"],
        [implication, let_expression],
        "make_two_obligations.",
    )

    assert open_goals(controller) == ["A -> B", "let x := 1 in x = x"]


def test_branch_nodes_preserve_let_bound_hypothesis_values():
    controller = make_controller("P /\\ True")
    let_goal = Goal([Hyp(["y"], "bool", "true")], "y = true")

    update(controller, ["P /\\ True"], [let_goal, Goal([], "True")], "split.")

    assert controller.proof_tree.open_subgoals[0].hypotheses_after == (
        "y := true : bool"
    )


def test_nested_branching_preserves_count_order_and_tactic_attachments():
    controller = completed_nested_tree()

    assert not controller.proof_tree.open_subgoals

    outer_split = controller.proof_tree.root.children[0]
    ab_branch, c_branch = outer_split.children
    inner_split = ab_branch.children[0]
    a_branch, b_branch = inner_split.children

    assert a_branch.children[0].tactic == "exact HA."
    assert b_branch.children[0].tactic == "exact HB."
    assert c_branch.children[0].tactic == "exact HC."
    assert controller.proof_tree.to_dict()["metadata"]["open_subgoals_count"] == 0


def test_solving_a_goal_does_not_copy_the_next_goal_into_its_branch():
    controller = make_controller("A /\\ B")
    update(controller, ["A /\\ B"], ["A", "B"], "split.")

    update(controller, ["A", "B"], ["B"], "exact HA.")

    solved = find_tactic(controller.proof_tree.root, "exact HA.")
    assert solved.status == "Proved"
    assert solved.goals_after == ""
    assert open_goals(controller) == ["B"]


def test_rollback_frontier_excludes_goals_solved_at_the_kept_step():
    controller = completed_nested_tree()

    result = controller.proof_tree.delete_subtree_by_step_number(3)

    assert result["open_subgoals_updated"]
    assert open_goals(controller) == ["B", "C"]
    assert find_tactic(controller.proof_tree.root, "exact HA.").status == "Proved"
    assert find_tactic(controller.proof_tree.root, "exact HB.") is None


def test_rollback_to_a_branching_step_reopens_its_children_in_order():
    controller = completed_nested_tree()

    controller.proof_tree.delete_subtree_by_step_number(2)

    assert open_goals(controller) == ["A", "B", "C"]


def test_rollback_to_the_root_restores_the_initial_goal_only():
    controller = completed_nested_tree()

    controller.proof_tree.delete_subtree_by_step_number(0)

    assert controller.proof_tree.open_subgoals == [controller.proof_tree.root]
    assert open_goals(controller) == ["(A /\\ B) /\\ C"]


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
    interface, controller = load_live_proof(
        tmp_path,
        "nested_split",
        "(A B C : Prop) : A -> B -> C -> (A /\\ B) /\\ C",
    )

    try:
        def apply(tactic):
            before = interface.get_subgoals()
            apply_live(controller, tactic)
            after = interface.get_subgoals()
            return before, after

        apply("intros HA HB HC.")
        apply("split.")
        outer_split = find_tactic(controller.proof_tree.root, "split.")
        _, c_branch = outer_split.children
        apply("{")
        before, after = apply("split.")

        assert [str(goal.ty) for goal in before] == ["A /\\ B", "C"]
        assert [str(goal.ty) for goal in after] == ["A", "B", "C"]
        assert open_goals(controller) == ["A", "B", "C"]

        apply("exact HA.")
        apply("exact HB.")
        assert controller.proof_tree.open_subgoals == [c_branch]
        apply("}")
        apply("exact HC.")

        expected_parents = {
            "exact HA.": "A",
            "exact HB.": "B",
        }
        for tactic, expected_goal in expected_parents.items():
            tactic_node = find_tactic(controller.proof_tree.root, tactic)
            assert tactic_node is not None
            assert tactic_node.parent.goals_after == expected_goal
        assert is_ancestor(
            c_branch,
            find_tactic(controller.proof_tree.root, "exact HC."),
        )
        assert not controller.proof_tree.open_subgoals
    finally:
        interface.close()


def test_live_controller_rollback_restores_coqpyt_and_tree_together(tmp_path):
    interface, controller = load_live_proof(
        tmp_path,
        "rollback_nested",
        "(A B C : Prop) : A -> B -> C -> (A /\\ B) /\\ C",
    )
    try:
        states = [
            apply_live(controller, tactic)
            for tactic in [
                "intros HA HB HC.",
                "split.",
                "{",
                "split.",
                "exact HA.",
            ]
        ]

        result = controller._execute_rollback(states, "test", "", 1)
        assert result["success"], result
        assert [str(goal.ty) for goal in interface.get_subgoals()] == ["A", "B", "C"]
        assert_frontier_matches_coqpyt(controller, interface)

        kept_states = states[:-1]
        result = controller._execute_rollback(
            kept_states,
            "test",
            "",
            len(kept_states),
        )
        assert result["success"], result
        assert len(interface.get_subgoals()) == 1
        assert "(A /\\ B) /\\ C" in str(interface.get_subgoals()[0].ty)
        assert_frontier_matches_coqpyt(controller, interface)
    finally:
        interface.close()


def test_explicit_goal_selector_updates_the_selected_branch(tmp_path):
    interface, controller = load_live_proof(
        tmp_path,
        "selected_branch",
        "(A B : Prop) : A -> B -> A /\\ B",
    )
    try:
        apply_live(controller, "intros HA HB.")
        apply_live(controller, "split.")
        _, b_branch = controller.proof_tree.open_subgoals

        apply_live(controller, "2: exact HB.")

        selected = find_tactic(controller.proof_tree.root, "2: exact HB.")
        assert selected.status == "Proved"
        assert selected.parent is b_branch
        assert open_goals(controller) == ["A"]
    finally:
        interface.close()


def test_explicit_selector_can_branch_a_background_goal(tmp_path):
    interface, controller = load_live_proof(
        tmp_path,
        "selected_split",
        "(A B C : Prop) : A -> B -> C -> A /\\ (B /\\ C)",
    )
    try:
        apply_live(controller, "intros HA HB HC.")
        apply_live(controller, "split.")
        a_branch, bc_branch = controller.proof_tree.open_subgoals

        apply_live(controller, "2: split.")

        assert controller.proof_tree.open_subgoals[0] is a_branch
        assert open_goals(controller) == ["A", "B", "C"]
        selected_split = find_tactic(controller.proof_tree.root, "2: split.")
        assert selected_split.parent is bc_branch
    finally:
        interface.close()


def test_selector_distinguishes_identical_live_goals_by_position(tmp_path):
    interface, controller = load_live_proof(
        tmp_path,
        "selected_duplicate",
        "(P : Prop) : P -> P /\\ P",
    )
    try:
        apply_live(controller, "intro HP.")
        apply_live(controller, "split.")
        first, second = controller.proof_tree.open_subgoals

        apply_live(controller, "2: exact HP.")

        assert controller.proof_tree.open_subgoals == [first]
        selected = find_tactic(controller.proof_tree.root, "2: exact HP.")
        assert selected.parent is second
    finally:
        interface.close()


def test_all_selector_can_close_every_open_branch(tmp_path):
    interface, controller = load_live_proof(
        tmp_path,
        "all_branches",
        "(P : Prop) : P -> P /\\ P",
    )
    try:
        apply_live(controller, "intro HP.")
        apply_live(controller, "split.")
        apply_live(controller, "all: exact HP.")

        assert not controller.proof_tree.open_subgoals
        assert not interface.get_subgoals()
    finally:
        interface.close()


def test_all_selector_accepts_any_tactic_that_closes_every_branch(tmp_path):
    interface, controller = load_live_proof(
        tmp_path,
        "all_assumption",
        "(P Q : Prop) : P -> Q -> P /\\ Q",
    )
    try:
        apply_live(controller, "intros HP HQ.")
        apply_live(controller, "split.")
        apply_live(controller, "all: assumption.")

        assert not controller.proof_tree.open_subgoals
        assert not interface.get_subgoals()
    finally:
        interface.close()


def test_nonclosing_all_selector_is_reverted_without_desynchronizing(tmp_path):
    interface, controller = load_live_proof(
        tmp_path,
        "unsafe_all",
        "(P : Prop) : P -> P /\\ P",
    )
    try:
        apply_live(controller, "intro HP.")
        apply_live(controller, "split.")
        tree_before = controller.proof_tree.to_dict()
        goals_before = [str(goal.ty) for goal in interface.get_subgoals()]

        assert not controller._apply_tactic("all: idtac.")
        assert controller.proof_tree.to_dict() == tree_before
        assert [str(goal.ty) for goal in interface.get_subgoals()] == goals_before
    finally:
        interface.close()


def test_focus_reorders_existing_nodes_then_restores_their_order(tmp_path):
    interface, controller = load_live_proof(
        tmp_path,
        "rotated_goals",
        "(A B C : Prop) : A -> B -> C -> A /\\ B /\\ C",
    )
    try:
        apply_live(controller, "intros HA HB HC.")
        apply_live(controller, "repeat split.")
        original_nodes = list(controller.proof_tree.open_subgoals)

        apply_live(controller, "Focus 2.")

        assert set(controller.proof_tree.open_subgoals) == set(original_nodes)
        assert controller.proof_tree.open_subgoals != original_nodes

        apply_live(controller, "Unfocus.")
        assert controller.proof_tree.open_subgoals == original_nodes
    finally:
        interface.close()


def test_selector_scoped_braces_reorder_then_restore_existing_nodes(tmp_path):
    interface, controller = load_live_proof(
        tmp_path,
        "selector_focus",
        "(A B C : Prop) : A -> B -> C -> A /\\ B /\\ C",
    )
    try:
        apply_live(controller, "intros HA HB HC.")
        apply_live(controller, "repeat split.")
        original_nodes = list(controller.proof_tree.open_subgoals)

        apply_live(controller, "2: {")

        assert controller.proof_tree.open_subgoals == [
            original_nodes[1],
            original_nodes[0],
            original_nodes[2],
        ]

        apply_live(controller, "exact HB.")
        apply_live(controller, "}")

        assert controller.proof_tree.open_subgoals == [
            original_nodes[0],
            original_nodes[2],
        ]
        selected = find_tactic(controller.proof_tree.root, "exact HB.")
        assert selected.parent is original_nodes[1]
    finally:
        interface.close()


def test_rollback_to_active_focus_restores_the_focused_frontier_order(tmp_path):
    interface, controller = load_live_proof(
        tmp_path,
        "rollback_active_focus",
        "(A B C : Prop) : A -> B -> C -> A /\\ B /\\ C",
    )
    try:
        states = [
            apply_live(controller, tactic)
            for tactic in [
                "intros HA HB HC.",
                "repeat split.",
                "Focus 2.",
                "idtac.",
            ]
        ]
        focused_nodes = list(controller.proof_tree.open_subgoals)

        result = controller._execute_rollback(states, "test", "", 1)

        assert result["success"], result
        assert controller.proof_tree.open_subgoals == [
            focused_nodes[0].parent,
            focused_nodes[1],
            focused_nodes[2],
        ]
        assert_frontier_matches_coqpyt(controller, interface)
    finally:
        interface.close()


def test_bullets_preserve_branch_lineage_and_frontier_order(tmp_path):
    interface, controller = load_live_proof(
        tmp_path,
        "bullet_branches",
        "(A B : Prop) : A -> B -> A /\\ B",
    )
    try:
        apply_live(controller, "intros HA HB.")
        apply_live(controller, "split.")
        a_branch, b_branch = controller.proof_tree.open_subgoals
        apply_live(controller, "-")
        apply_live(controller, "exact HA.")
        apply_live(controller, "-")
        apply_live(controller, "exact HB.")

        assert is_ancestor(a_branch, find_tactic(controller.proof_tree.root, "exact HA."))
        assert is_ancestor(b_branch, find_tactic(controller.proof_tree.root, "exact HB."))
        assert not controller.proof_tree.open_subgoals
    finally:
        interface.close()


def test_rollback_after_focus_restoration_keeps_the_background_goal(tmp_path):
    interface, controller = load_live_proof(
        tmp_path,
        "rollback_focus",
        "(A B C : Prop) : A -> B -> C -> (A /\\ B) /\\ C",
    )
    try:
        states = [
            apply_live(controller, tactic)
            for tactic in [
                "intros HA HB HC.",
                "split.",
                "{",
                "split.",
                "exact HA.",
                "exact HB.",
                "}",
            ]
        ]
        c_node = controller.proof_tree.open_subgoals[0]

        result = controller._execute_rollback(states, "test", "", 1)

        assert result["success"], result
        assert [str(goal.ty) for goal in interface.get_subgoals()] == ["C"]
        assert controller.proof_tree.open_subgoals == [c_node]
        assert_frontier_matches_coqpyt(controller, interface)
    finally:
        interface.close()


def test_failed_tactic_query_and_idtac_do_not_corrupt_the_frontier(tmp_path):
    interface, controller = load_live_proof(
        tmp_path,
        "transparent_steps",
        "(P : Prop) : P -> P",
    )
    try:
        apply_live(controller, "intro HP.")
        tree_before = controller.proof_tree.to_dict()
        frontier_before = list(controller.proof_tree.open_subgoals)
        goals_before = [str(goal.ty) for goal in interface.get_subgoals()]

        assert not controller._apply_tactic("exact I.")
        assert controller.proof_tree.to_dict() == tree_before
        assert controller.proof_tree.open_subgoals == frontier_before
        assert [str(goal.ty) for goal in interface.get_subgoals()] == goals_before

        assert interface.execute_query("Check nat.")
        assert controller.proof_tree.to_dict() == tree_before
        assert controller.proof_tree.open_subgoals == frontier_before
        assert [str(goal.ty) for goal in interface.get_subgoals()] == goals_before

        class QueryContext:
            @staticmethod
            def handle_query_call(query, tool_call_id):
                return f"{tool_call_id}: {query}", True

        controller.context_manager = QueryContext()
        assert controller._run_query("Check nat.", "query-1") == "query-1: Check nat."
        assert controller.proof_tree.to_dict() == tree_before
        assert controller.proof_tree.open_subgoals == frontier_before

        apply_live(controller, "idtac.")
        assert open_goals(controller) == ["P"]
    finally:
        interface.close()


def test_abort_is_rejected_without_destroying_the_proof_state(tmp_path):
    interface, controller = load_live_proof(
        tmp_path,
        "no_abort",
        "(P : Prop) : P -> P",
    )
    try:
        apply_live(controller, "intro HP.")
        tree_before = controller.proof_tree.to_dict()
        goals_before = [str(goal.ty) for goal in interface.get_subgoals()]

        assert not controller._apply_tactic("Abort.")
        assert controller.proof_tree.to_dict() == tree_before
        assert [str(goal.ty) for goal in interface.get_subgoals()] == goals_before
    finally:
        interface.close()


def test_inconsistent_frontier_ids_are_not_silently_accepted():
    controller = make_controller("A")
    controller.proof_tree.open_subgoals.append(
        controller.proof_tree.add_node(
            tactic="background",
            goals_before="B",
            goals_after="B",
            hypotheses_before="",
            hypotheses_after="",
            step_number=0,
            parent=controller.proof_tree.root,
        )
    )
    controller.proof_tree.open_subgoals[1].goal_id = 1

    result = controller._handle_successful_tactic(
        "2: exact HB.",
        [Goal([], "A", 0), Goal([], "B", 99)],
        [Goal([], "A", 0)],
        "A",
        "X",
        "",
        "",
    )

    assert result is False
    assert open_goals(controller) == ["A", "B"]


def test_live_reconciliation_failure_restores_rocq(tmp_path, monkeypatch):
    interface, controller = load_live_proof(
        tmp_path,
        "reconcile_rollback",
        "(P : Prop) : P -> P",
    )
    try:
        apply_live(controller, "intro HP.")
        tree_before = controller.proof_tree.to_dict()
        goals_before = interface.get_goal_str()
        hypotheses_before = interface.get_hypothesis()
        subgoals_before = interface.get_subgoals()
        steps_before = len(interface.proof.steps)

        assert controller._apply_tactic("idtac.")
        subgoals_after = interface.get_subgoals()
        def reject_update(*_args):
            controller.proof_tree.root.children.clear()
            raise ValueError("bad frontier")

        monkeypatch.setattr(controller, "_update_proof_tree", reject_update)

        result = controller._handle_successful_tactic(
            "idtac.",
            subgoals_before,
            subgoals_after,
            goals_before,
            interface.get_goal_str(),
            hypotheses_before,
            interface.get_hypothesis(),
        )

        assert result is False
        assert len(interface.proof.steps) == steps_before
        assert interface.get_goal_str() == goals_before
        assert controller.proof_tree.to_dict() == tree_before
        assert "reverted" in interface.get_last_error()
    finally:
        interface.close()


def test_shelving_is_rejected_until_the_tree_can_represent_shelves(tmp_path):
    interface, controller = load_live_proof(
        tmp_path,
        "no_hidden_shelves",
        "(P : Prop) : P -> P",
    )
    try:
        apply_live(controller, "intro HP.")
        tree_before = controller.proof_tree.to_dict()
        goals_before = [str(goal.ty) for goal in interface.get_subgoals()]

        assert not controller._apply_tactic("shelve.")
        assert controller.proof_tree.to_dict() == tree_before
        assert [str(goal.ty) for goal in interface.get_subgoals()] == goals_before
    finally:
        interface.close()


@pytest.mark.parametrize("nested, focused", [(False, False), (True, False), (True, True)])
def test_shared_witness_refreshes_all_branches_and_survives_rollback(tmp_path, nested, focused):
    statement = (
        ": exists n : nat, (n = 2 /\\ n = 2 + 0) /\\ n + 0 = 2"
        if nested else ": exists n : nat, n = 2 /\\ n + 0 = 2"
    )
    interface, controller = load_live_proof(tmp_path, "shared_witness", statement)
    try:
        tactics = ["eexists.", "split."]
        if focused:
            tactics.append("{")
        if nested:
            tactics.append("split.")
        states = [apply_live(controller, tactic) for tactic in tactics]
        nodes_before = list(controller.proof_tree.open_subgoals)
        snapshots = [(node.goals_after, node.hypotheses_after) for node in nodes_before]
        ids_before = [node.goal_id for node in nodes_before]

        states.append(apply_live(controller, "reflexivity."))
        assert [node.goal_id for node in controller.proof_tree.open_subgoals] == ids_before[1:]
        assert controller.proof_tree.open_subgoals == nodes_before[1:]
        assert open_goals(controller) == (["2 = 2 + 0", "2 + 0 = 2"] if nested else ["2 + 0 = 2"])
        assert [(node.goals_after, node.hypotheses_after) for node in nodes_before] == snapshots
        assert "?n" not in controller.proof_tree.get_proof_tree_string()

        result = controller._execute_rollback(states, "", "", 1)
        assert result["success"], result
        assert_frontier_matches_coqpyt(controller, interface)
        assert all("?n" in goal for goal in open_goals(controller))
        apply_live(controller, "reflexivity.")
        if nested:
            apply_live(controller, "reflexivity.")
        if focused:
            apply_live(controller, "}")
        apply_live(controller, "reflexivity.")
        assert not controller.proof_tree.open_subgoals
    finally:
        interface.close()


def test_shared_witness_refreshes_hypothesis_types_and_definition_bodies(tmp_path):
    interface, controller = load_live_proof(
        tmp_path, "shared_context", ": exists n : nat, n = 2 /\\ n + 0 = 2",
    )
    try:
        apply_live(controller, "eexists.")
        apply_live(controller, "match goal with |- ?w = _ /\\ _ => pose (saved := w); pose proof (eq_refl w) as H; pose (packed := eq_refl w) end.")
        apply_live(controller, "split.")
        sibling = controller.proof_tree.open_subgoals[1]
        context_snapshot = sibling.hypotheses_after
        assert "?n" in context_snapshot
        apply_live(controller, "reflexivity.")
        assert controller.proof_tree.open_subgoals == [sibling]
        context = controller.proof_tree.current_goal(sibling)[1]
        assert "?n" not in context
        assert "saved := 2 : nat" in context
        assert "H : 2 = 2" in context
        assert "packed :=" in context and ": 2 = 2" in context
        assert sibling.hypotheses_after == context_snapshot
        assert context in controller.proof_tree.get_proof_tree_string()
        apply_live(controller, "reflexivity.")
    finally:
        interface.close()


def test_identical_goal_text_is_reordered_by_id(tmp_path):
    interface, controller = load_live_proof(tmp_path, "identical_goals", ": True /\\ True")
    try:
        apply_live(controller, "split.")
        first, second = controller.proof_tree.open_subgoals
        assert first.goal_id != second.goal_id
        assert first.goals_after == second.goals_after == "True"
        apply_live(controller, "Focus 2.")
        assert controller.proof_tree.open_subgoals == [second, first]
        apply_live(controller, "exact I.")
        assert controller.proof_tree.open_subgoals == [first]
    finally:
        interface.close()


def test_goal_parser_preserves_server_identity_and_requires_it_for_tracking():
    goal = Goal.parse({"info": {"evar": ["Ser_Evar", 14]}, "hyps": [], "ty": "True"})
    assert goal.goal_id == ("Ser_Evar", 14)
    assert ProofTree.goal_ids([goal]) == [("Ser_Evar", 14)]
    with pytest.raises(ValueError, match="required"):
        ProofTree.goal_ids([Goal.parse({"hyps": [], "ty": "True"})])
    with pytest.raises(ValueError, match="Duplicate"):
        ProofTree.goal_ids([goal, goal])


def test_indirectly_solved_goal_keeps_history_and_reopens_on_rollback():
    controller = make_controller("A /\\ B")
    update(controller, ["A /\\ B"], ["A", "B"], "split.")
    first, second = controller.proof_tree.open_subgoals
    controller.global_step_id += 1
    controller._update_proof_tree(
        [Goal([], "A", first.goal_id), Goal([], "B", second.goal_id)],
        [], "solve_shared_evar.", "A", "", "", "",
    )
    assert not controller.proof_tree.open_subgoals
    assert first.children[0].status == second.children[0].status == "Proved"
    assert first.goals_after == "A" and second.goals_after == "B"
    controller.proof_tree.delete_subtree_by_step_number(1)
    assert controller.proof_tree.open_subgoals == [first, second]


def test_goal_hidden_by_a_tactical_is_not_mistaken_for_a_solved_goal(tmp_path):
    interface, controller = load_live_proof(tmp_path, "hidden_tactical", ": True")
    try:
        before = controller.proof_tree.to_dict()
        steps = len(interface.proof.steps)
        assert not controller._apply_tactic("try shelve.")
        assert "shelved" in interface.get_last_error()
        assert len(interface.proof.steps) == steps
        assert controller.proof_tree.to_dict() == before
        assert_frontier_matches_coqpyt(controller, interface)
    finally:
        interface.close()
