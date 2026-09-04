from types import SimpleNamespace
from unittest.mock import Mock

from agent.interactive_session import InteractiveSessionManager
from utils.logger import setup_logger


def make_session(controller=None):
    session = object.__new__(InteractiveSessionManager)
    session.controller = controller or SimpleNamespace(is_successful=False)
    session._gen = None
    session._done = False
    session.logger = setup_logger("test_interactive_session")
    session._readline_available = False
    session._history_file = None
    return session


def test_advance_one_marks_completion_and_handles_exhaustion():
    session = make_session()
    session._gen = iter([{"type": "tactic", "proof_complete": True}])

    result = session._advance_one()
    assert result["proof_complete"]
    assert session._done

    session._done = False
    session._gen = iter([])
    assert session._advance_one() == {"type": "done", "success": False}
    assert session._done


def test_run_stops_when_the_goal_changes(monkeypatch):
    coq = SimpleNamespace(get_goal_str=Mock(side_effect=["goal 1", "goal 2"]))
    session = make_session(SimpleNamespace(coq=coq))
    session._gen = iter([{"type": "tactic", "success": True, "proof_complete": False}])
    report = Mock()
    display = Mock()
    monkeypatch.setattr(session, "_report", report)
    monkeypatch.setattr(session, "_display_state", display)

    session._do_run()

    report.assert_called_once()
    display.assert_called_once()


def test_hint_is_queued_for_the_next_agent_step(capsys):
    controller = SimpleNamespace(_pending_hints=[])
    session = make_session(controller)

    session._do_hint("consider induction")

    assert controller._pending_hints == ["consider induction"]
    assert "queued" in capsys.readouterr().out.lower()


def test_search_passes_the_current_goal_to_context_search(capsys):
    search = Mock(return_value=SimpleNamespace(content="found lemma"))
    controller = SimpleNamespace(
        coq=SimpleNamespace(get_goal_str=Mock(return_value="current goal")),
        context_manager=SimpleNamespace(context_search=SimpleNamespace(search=search)),
    )
    session = make_session(controller)

    session._do_search("Search foo.")

    search.assert_called_once_with("Search foo.", goal_context="current goal")
    assert capsys.readouterr().out.strip() == "found lemma"


def test_successful_user_tactic_is_recorded_and_closed(monkeypatch):
    statuses = [
        {"is_complete": True, "ready_for_qed": True, "qed_already_applied": False},
        {"is_complete": True, "ready_for_qed": True, "qed_already_applied": True},
    ]
    coq = SimpleNamespace(
        get_subgoals=Mock(side_effect=[["before"], []]),
        get_goal_str=Mock(side_effect=["goal", "No more goals."]),
        get_hypothesis=Mock(side_effect=["H : P", ""]),
        apply_tactic=Mock(return_value=True),
        apply_qed=Mock(return_value=True),
        get_proof_completion_status=Mock(side_effect=statuses),
    )
    controller = SimpleNamespace(
        coq=coq,
        global_step_id=0,
        _tactics_with_states=[],
        _handle_successful_tactic=Mock(return_value={"step_number": 1}),
        is_successful=False,
    )
    session = make_session(controller)
    monkeypatch.setattr(session, "_display_state", Mock())

    session._do_user_tactic("exact I", silent=True)

    coq.apply_tactic.assert_called_once_with("exact I.")
    coq.apply_qed.assert_called_once()
    assert controller._tactics_with_states[0]["source"] == "user"
    assert controller.is_successful
    assert session._done


def test_failed_user_tactic_does_not_change_history(capsys):
    coq = SimpleNamespace(
        get_subgoals=Mock(return_value=["before"]),
        get_goal_str=Mock(return_value="goal"),
        get_hypothesis=Mock(return_value="H : P"),
        apply_tactic=Mock(return_value=False),
        get_last_error=Mock(return_value="unknown tactic"),
    )
    controller = SimpleNamespace(coq=coq, global_step_id=0, _tactics_with_states=[])
    session = make_session(controller)

    session._do_user_tactic("bad")

    assert controller._tactics_with_states == []
    assert controller.global_step_id == 0
    assert "unknown tactic" in capsys.readouterr().out


def test_rollback_removes_history_proof_steps_and_tree(monkeypatch):
    proof = object()
    proof_file = SimpleNamespace(pop_step=Mock())
    coq = SimpleNamespace(
        get_unproven_proof=Mock(return_value=proof),
        proof_file=proof_file,
        proof=proof,
    )
    tree = SimpleNamespace(delete_subtree_by_step_number=Mock())
    history = [
        {"step_number": 1, "source": "agent"},
        {"step_number": 2, "source": "user"},
        {"step_number": 3, "source": "agent"},
    ]
    controller = SimpleNamespace(coq=coq, proof_tree=tree, _tactics_with_states=history)
    session = make_session(controller)
    monkeypatch.setattr(session, "_display_state", Mock())

    session._do_rollback(2)

    assert proof_file.pop_step.call_count == 2
    tree.delete_subtree_by_step_number.assert_called_once_with(1)
    assert controller._tactics_with_states == [{"step_number": 1, "source": "agent"}]
