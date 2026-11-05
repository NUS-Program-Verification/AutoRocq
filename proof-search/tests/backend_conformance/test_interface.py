from pathlib import Path

import pytest

from prover_backends.types import CompletionStatus, Goal, GoalState


def observe(interface):
    return (interface.get_goal_state(), interface.completion_status(),
            interface.get_step_count(), interface.get_proof_file_content())


def execute(interface, command):
    count = interface.get_step_count()
    assert interface.execute(command), interface.get_last_error()
    assert interface.get_step_count() == count + 1


@pytest.mark.parametrize("command", ["unknown", "partial_failure"])
def test_execution_failure_is_atomic_without_backend_policy(case, command):
    interface = case.interface
    execute(interface, case.introduce)
    checkpoint, before = interface.checkpoint(), observe(interface)
    assert not interface.execute(case.rejected[command])
    assert interface.get_last_error()
    assert interface.matches_checkpoint(checkpoint)
    assert observe(interface) == before
    execute(interface, case.branch)
    execute(interface, case.solve_all)
    assert interface.finalize()
    case.verify_export(interface.get_proof_file_content())


def test_queries_preserve_state_without_backend_policy(case):
    interface = case.interface
    execute(interface, case.introduce)
    execute(interface, case.branch)
    checkpoint, before = interface.checkpoint(), observe(interface)
    assert interface.execute_query(case.invalid_query) is None
    assert interface.get_last_error()
    assert interface.execute_query(case.query)
    assert interface.execute_query(case.empty_search) == case.empty_result
    assert interface.matches_checkpoint(checkpoint)
    assert observe(interface) == before


def test_restore_recovers_goal_order_hypotheses_and_cached_state(case, case_factory):
    interface = case.interface
    execute(interface, case.introduce)
    execute(interface, case.branch)
    checkpoint, before = interface.checkpoint(), observe(interface)
    state = before[0]
    assert isinstance(state, GoalState)
    assert len(state.goals) == 2
    assert all(isinstance(goal, Goal) and goal.hypotheses for goal in state.goals)
    assert state.goals[0].goal_id != state.goals[1].goal_id
    assert not state.shelved and not state.given_up
    execute(interface, case.change_hypotheses)
    abandoned = interface.checkpoint()
    assert interface.get_goal_state().goals[0].hypotheses != state.goals[0].hypotheses
    execute(interface, case.focus_second)
    execute(interface, case.solve_one)
    interface.restore(checkpoint)
    assert observe(interface) == before
    interface.restore(checkpoint)
    execute(interface, case.solve_one)
    assert interface.get_goal_state().goals == state.goals[1:]
    current, current_state = interface.checkpoint(), observe(interface)
    for invalid in (abandoned, case_factory().interface.checkpoint(), object()):
        with pytest.raises(case.checkpoint_error):
            interface.restore(invalid)
        assert interface.matches_checkpoint(current)
        assert observe(interface) == current_state


def test_finalization_checks_obligations_without_backend_policy(case):
    interface = case.interface
    checkpoint, before = interface.checkpoint(), observe(interface)
    assert not interface.finalize()
    assert interface.matches_checkpoint(checkpoint)
    assert observe(interface) == before
    execute(interface, case.introduce)
    execute(interface, case.branch)
    execute(interface, case.solve_all)
    assert interface.completion_status() == CompletionStatus(True, False)
    assert interface.finalize()
    assert interface.completion_status().finalized
    assert interface.get_goal_state() == GoalState([], [], [])
    case.verify_export(interface.get_proof_file_content())


@pytest.mark.parametrize("obligation", ["hidden_goal", "nested_admission"])
def test_unresolved_obligations_remain_visible_and_prevent_finalization(case, obligation):
    interface = case.interface
    execute(interface, case.introduce)
    execute(interface, case.rejected[obligation])
    state = interface.get_goal_state()
    assert state.shelved or state.given_up
    assert all(isinstance(goal, Goal) for goal in state.shelved + state.given_up)
    checkpoint, before = interface.checkpoint(), observe(interface)
    assert not interface.finalize()
    assert not interface.completion_status().finalized
    assert interface.matches_checkpoint(checkpoint)
    assert observe(interface) == before


def test_shared_witness_state_survives_restore(case_factory):
    case = case_factory("shared_witness")
    interface = case.interface
    execute(interface, case.create_witness)
    execute(interface, case.branch)
    checkpoint, before = interface.checkpoint(), observe(interface)
    execute(interface, case.solve_one)
    remaining = interface.get_goal_state().goals
    assert len(remaining) == 1
    assert remaining[0].goal_id == before[0].goals[1].goal_id
    assert remaining[0].conclusion != before[0].goals[1].conclusion
    interface.restore(checkpoint)
    assert observe(interface) == before
    execute(interface, case.solve_one)
    execute(interface, case.solve_one)
    assert interface.finalize()
    case.verify_export(interface.get_proof_file_content())


def test_restart_replay_and_close_preserve_source(case):
    interface = case.interface
    assert interface.is_loaded() and interface.has_active_proof()
    source = case.source.read_bytes()
    working = Path(interface.file_path)
    assert Path(interface.source_path).resolve() == case.source.resolve()
    assert working.resolve() != case.source.resolve()
    initial, before = interface.checkpoint(), observe(interface)
    for command in (case.introduce, case.branch, case.solve_one):
        execute(interface, command)
    checkpoint, progressed = interface.checkpoint(), observe(interface)
    assert interface.restart()
    assert interface.load()
    assert interface.is_loaded()
    assert interface.matches_checkpoint(checkpoint)
    assert observe(interface) == progressed
    commands = interface.extract_and_reset_tactics()
    assert interface.matches_checkpoint(initial)
    assert observe(interface) == before
    for command in commands:
        execute(interface, command)
    assert observe(interface) == progressed
    interface.close()
    assert not working.exists()
    assert case.source.read_bytes() == source
