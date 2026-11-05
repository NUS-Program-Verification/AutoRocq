from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from agent.context_manager import ContextManager
from agent.interactive_session import InteractiveSessionManager
from agent.proof_controller import ProofController
from prover_backends.types import CompletionStatus, Goal, SearchResult, TacticEffect


def observe(backend):
    """Observe proof state without relying on checkpoints."""
    return (backend.get_goals(), backend.completion_status(),
            backend.get_proof_file_content())


def apply(backend, command):
    before_count = backend.get_step_count()
    normalized = backend.normalize_tactic(command)
    assert backend.normalize_tactic(normalized) == normalized
    assert backend.apply_tactic(normalized), backend.get_last_error()
    assert backend.get_step_count() == before_count + 1


def branch(case):
    apply(case.backend, case.introduce)
    apply(case.backend, case.branch)
    goals = case.backend.get_goals()
    assert len(goals) == 2
    assert all(isinstance(goal, Goal) for goal in goals)
    assert goals[0].conclusion == goals[1].conclusion
    assert goals[0].goal_id != goals[1].goal_id
    assert all(goal.hypotheses for goal in goals)
    return goals


def controller_for(case, tmp_path):
    history = str(tmp_path / "history.json")
    context = ContextManager(case.backend, history_file=history, enable_caching=False)
    controller = ProofController(case.backend, context, history_file=history,
                                 enable_recording=False, output_dir=str(tmp_path))
    assert controller._init_proof_session("contract")
    return controller


@pytest.mark.parametrize("enable_search", [True, False])
def test_model_receives_backend_tool_definitions(case, tmp_path, monkeypatch, enable_search):
    expected_tactic = deepcopy(case.backend.tactic_tool)
    expected_query = deepcopy(case.backend.query_tool)
    context = ContextManager(case.backend, history_file=str(tmp_path / "history.json"),
                             enable_caching=False, enable_context_search=enable_search)
    tool_call = SimpleNamespace(id="contract", function=SimpleNamespace(
        name="plan", arguments='{"strategy": "Use the hypothesis."}'))
    message = SimpleNamespace(content=None, tool_calls=[tool_call])
    completion = Mock(return_value=SimpleNamespace(
        choices=[SimpleNamespace(message=message)], usage=None))
    monkeypatch.setattr("agent.context_manager.litellm.completion", completion)
    monkeypatch.setattr("agent.context_manager.litellm.completion_cost", lambda **kwargs: 0)

    result = context.chat_session.send_message("Prove the current goal.")

    assert result["function_call"]["name"] == "plan"
    completion.assert_called_once()
    request = completion.call_args.kwargs
    tools = {tool["function"]["name"]: tool for tool in request["tools"]}
    assert tools["tactic"] == expected_tactic
    assert {"plan", "rollback"} <= tools.keys()
    if enable_search:
        assert tools["query"] == expected_query
    else:
        assert "query" not in tools
    system = request["messages"][0]["content"]
    assert case.backend.system_prompt in system
    assert case.backend.tactic_instruction.strip() in system
    assert case.backend.prompt_guidelines.strip() in system


def test_loading_and_observation_do_not_mutate_proof(case):
    backend = case.backend
    assert backend.has_active_proof()
    assert backend.get_step_count() == 0
    checkpoint, before = backend.checkpoint(), observe(backend)
    assert len(before[0]) == 1
    assert before[1] == CompletionStatus(False, False)
    assert backend.get_goal_str() and backend.display_state()
    assert isinstance(backend.get_hypothesis(), str)
    assert backend.extract_proof_context(before[2])
    assert observe(backend) == before
    assert backend.matches_checkpoint(checkpoint)


@pytest.mark.parametrize("command", ["unknown", "partial_failure", "admission",
                                     "nested_admission", "abort", "hidden_goal"])
def test_rejection_is_atomic_and_session_remains_usable(case, command):
    backend = case.backend
    apply(backend, case.introduce)
    checkpoint, before = backend.checkpoint(), observe(backend)
    assert not backend.apply_tactic(backend.normalize_tactic(case.rejected[command]))
    assert backend.get_last_error()
    assert backend.matches_checkpoint(checkpoint)
    assert observe(backend) == before
    apply(backend, case.branch)
    apply(backend, case.solve_all)
    assert backend.finalize()
    case.verify_export(backend.get_proof_file_content())


@pytest.mark.parametrize("query_type", [None, "search", "print", "print_assumptions",
                                       "locate", "about", "check"])
def test_queries_preserve_goals_order_hypotheses_and_script(case, query_type):
    backend = case.backend
    branch(case)
    checkpoint, before = backend.checkpoint(), observe(backend)
    result = (backend.search(case.query, backend.get_goal_str()) if query_type is None
              else backend.search_by_type(query_type, case.query_identifier,
                                          goal_context=backend.get_goal_str()))
    assert isinstance(result, SearchResult)
    assert result.content and not (result.metadata or {}).get("error")
    assert result.result_size == len(result.content)
    assert backend.matches_checkpoint(checkpoint)
    assert observe(backend) == before


def test_query_error_is_distinct_from_no_matches_and_does_not_poison_session(case):
    backend = case.backend
    checkpoint, before = backend.checkpoint(), observe(backend)
    failed = backend.search_by_type("check", case.missing_identifier)
    assert failed.metadata and failed.metadata.get("error")
    empty = backend.search(case.empty_search)
    assert not (empty.metadata or {}).get("error")
    assert empty.content == case.empty_result
    assert empty.result_size == len(empty.content)
    good = backend.search(case.query)
    assert good.content and not (good.metadata or {}).get("error")
    assert backend.matches_checkpoint(checkpoint)
    assert observe(backend) == before


def test_unsupported_query_operation_reports_error_without_mutating_proof(case):
    backend = case.backend
    checkpoint, before = backend.checkpoint(), observe(backend)
    result = backend.search_by_type("unsupported_contract_operation", case.query_identifier)
    assert result.metadata and result.metadata.get("error")
    assert backend.matches_checkpoint(checkpoint)
    assert observe(backend) == before


def test_rollback_restores_hypotheses_goals_order_and_script(case):
    backend = case.backend
    branch(case)
    checkpoint, before = backend.checkpoint(), observe(backend)
    apply(backend, case.change_hypotheses)
    assert backend.get_goals()[0].hypotheses != before[0][0].hypotheses
    apply(backend, case.focus_second)
    apply(backend, case.solve_one)
    assert not backend.matches_checkpoint(checkpoint)
    backend.restore(checkpoint)
    assert backend.get_step_count() == 2
    assert backend.matches_checkpoint(checkpoint)
    assert observe(backend) == before
    backend.restore(checkpoint)
    assert observe(backend) == before
    # Retrying must not reuse stale state from before rollback.
    apply(backend, case.solve_one)
    assert backend.get_goals() == before[0][1:]
    backend.restore(checkpoint)
    assert observe(backend) == before


def test_foreign_and_invalid_checkpoints_cannot_mutate_session(case, case_factory):
    backend = case.backend
    other = case_factory()
    checkpoint, before = backend.checkpoint(), observe(backend)
    for invalid in (other.backend.checkpoint(), object()):
        assert not backend.matches_checkpoint(invalid)
        with pytest.raises(case.checkpoint_error):
            backend.restore(invalid)
        assert backend.matches_checkpoint(checkpoint)
        assert observe(backend) == before


def test_abandoned_checkpoint_is_rejected_without_mutation(case):
    backend = case.backend
    apply(backend, case.introduce)
    initial = backend.checkpoint()
    apply(backend, case.change_hypotheses)
    abandoned = backend.checkpoint()
    backend.restore(initial)
    apply(backend, case.branch)
    current, before = backend.checkpoint(), observe(backend)
    with pytest.raises(case.checkpoint_error):
        backend.restore(abandoned)
    assert backend.matches_checkpoint(current)
    assert observe(backend) == before


def test_focus_and_selected_goal_effects_preserve_other_goal_identities(case):
    backend = case.backend
    goals = branch(case)
    checkpoint = backend.checkpoint()
    assert backend.tactic_effect(case.focus_second) == TacticEffect("focus")
    apply(backend, case.focus_second)
    assert backend.get_goals() == goals[::-1]
    apply(backend, case.solve_one)
    assert backend.get_goals() == goals[:1]
    backend.restore(checkpoint)
    assert backend.tactic_effect(case.solve_second) == TacticEffect("single", 1)
    apply(backend, case.solve_second)
    assert backend.get_goals() == goals[:1]
    assert backend.tactic_effect(case.solve_one) == TacticEffect("single", 0)
    apply(backend, case.solve_one)
    assert backend.get_goals() == []


def test_finalization_requires_closed_obligations_and_exports_a_checked_proof(case):
    backend = case.backend
    branch(case)
    checkpoint, before = backend.checkpoint(), observe(backend)
    assert not backend.finalize()
    assert backend.matches_checkpoint(checkpoint)
    assert observe(backend) == before
    assert backend.tactic_effect(case.solve_all) == TacticEffect("all")
    apply(backend, case.solve_all)
    assert backend.get_goals() == []
    assert backend.completion_status() == CompletionStatus(True, False)
    assert backend.finalize()
    assert backend.completion_status().finalized
    assert backend.get_goals() == []
    case.verify_export(backend.get_proof_file_content())


def test_native_verifier_rejects_the_unfinished_fixture(case):
    with pytest.raises(AssertionError):
        case.verify_export(case.source.read_text())


def test_extracted_tactics_reset_and_replay_the_same_proof(case):
    backend = case.backend
    initial, before = backend.checkpoint(), observe(backend)
    commands = [case.introduce, case.branch, case.solve_one]
    for command in commands:
        apply(backend, command)
    recorded = observe(backend)
    tactics = backend.extract_and_reset_tactics()
    assert [backend.normalize_tactic(t) for t in tactics] == commands
    assert backend.matches_checkpoint(initial)
    assert observe(backend) == before
    for tactic in tactics:
        apply(backend, tactic)
    assert observe(backend) == recorded


def test_shared_witness_updates_surviving_goal_and_rollback_undoes_instantiation(
        case_factory, tmp_path, monkeypatch):
    case = case_factory("shared_witness")
    controller = controller_for(case, tmp_path)
    monkeypatch.setattr(InteractiveSessionManager, "_setup_readline", lambda self: None)
    session = InteractiveSessionManager(controller)
    for command in (case.create_witness, case.branch):
        session._do_user_tactic(command, silent=True)
    before = observe(case.backend)
    assert len(before[0]) == 2
    session._do_user_tactic(case.solve_one, silent=True)
    remaining = case.backend.get_goals()
    assert len(remaining) == 1
    assert remaining[0].goal_id == before[0][1].goal_id
    assert remaining[0].conclusion != before[0][1].conclusion
    assert controller.proof_tree.current_goal(
        controller.proof_tree.open_subgoals[0])[0] == remaining[0].conclusion
    session._do_rollback(1)
    assert observe(case.backend) == before
    assert [node.goal_id for node in controller.proof_tree.open_subgoals] == [
        goal.goal_id for goal in before[0]]
    session._do_user_tactic(case.solve_one, silent=True)
    assert case.backend.get_goals() == remaining
    session._do_user_tactic(case.solve_one, silent=True)
    assert session._done and controller.is_successful
    case.verify_export(case.backend.get_proof_file_content())


def test_close_preserves_source_and_removes_working_copy(case):
    backend = case.backend
    source = case.source.read_bytes()
    working = Path(backend.file_path)
    assert Path(backend.source_path).resolve() == case.source.resolve()
    assert working.resolve() != case.source.resolve() and working.exists()
    apply(backend, case.introduce)
    backend.close()
    assert case.source.read_bytes() == source
    assert not working.exists()


def test_restart_and_reload_preserve_accepted_work(case):
    backend = case.backend
    branch(case)
    apply(backend, case.solve_one)
    checkpoint, before = backend.checkpoint(), observe(backend)
    assert backend.restart(), backend.get_last_error()
    assert backend.load(), backend.get_last_error()
    assert backend.matches_checkpoint(checkpoint)
    assert observe(backend) == before
    apply(backend, case.solve_one)
    assert backend.finalize()
    case.verify_export(backend.get_proof_file_content())


def test_controller_queries_branches_rolls_back_and_finishes(case, tmp_path):
    controller = controller_for(case, tmp_path)
    actions = iter([
        {"type": "tactic", "content": case.introduce},
        {"type": "tactic", "content": case.branch},
        {"type": "query", "content": case.query},
        {"type": "tactic", "content": case.solve_one},
        {"type": "rollback", "content": {"steps": 1, "reason": "retry"}},
        {"type": "tactic", "content": case.solve_all},
    ])
    controller.context_manager.get_action = lambda *a, **k: (next(actions), "contract")
    events = list(controller.step_generator())
    assert any(e["type"] == "rollback" and e["success"] for e in events)
    assert controller.is_successful and case.backend.completion_status().finalized
    assert not controller.proof_tree.open_subgoals
    case.verify_export(case.backend.get_proof_file_content())


def test_interactive_focus_failure_and_rollback_keep_tree_in_sync(case, tmp_path, monkeypatch):
    controller = controller_for(case, tmp_path)
    monkeypatch.setattr(InteractiveSessionManager, "_setup_readline", lambda self: None)
    session = InteractiveSessionManager(controller)
    for command in (case.introduce, case.branch):
        session._do_user_tactic(command, silent=True)
    before = observe(case.backend)
    history = list(controller._tactics_with_states)
    tree = controller.proof_tree.to_dict()
    session._do_user_tactic(case.rejected["partial_failure"], silent=True)
    assert observe(case.backend) == before
    assert controller._tactics_with_states == history
    assert controller.proof_tree.to_dict() == tree
    session._do_user_tactic(case.focus_second, silent=True)
    assert case.backend.get_goals() == before[0][::-1]
    session._do_user_tactic(case.solve_one, silent=True)
    session._do_rollback(2)
    assert observe(case.backend) == before
    assert controller._tactics_with_states == history
    session._do_user_tactic(case.solve_all, silent=True)
    assert session._done and controller.is_successful
    assert not controller.proof_tree.open_subgoals
    case.verify_export(case.backend.get_proof_file_content())
