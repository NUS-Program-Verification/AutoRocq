from unittest.mock import Mock

import pytest

from prover_backends.interface import ProverInterface
from prover_backends.rocq.backend import RocqBackend
from prover_backends.types import Goal, GoalState


@pytest.mark.parametrize("after,accepted", [
    (GoalState([], [], []), True),
    (GoalState([], [], [Goal(2, "new child")]), False),
    (GoalState([], [Goal(1, "original")], []), False),
    (GoalState([Goal(1, "original")], [Goal(2, "witness")], []), True),
])
def test_backend_policy_uses_only_the_interface_contract(after, accepted):
    interface = Mock(spec_set=ProverInterface)
    interface.get_goal_state.side_effect = [GoalState([Goal(1, "original")], [], []), after]
    interface.execute.return_value = True
    backend = RocqBackend(interface)

    assert backend.apply_tactic("idtac.") is accepted
    interface.execute.assert_called_once_with("idtac.")
    if accepted:
        interface.restore.assert_not_called()
    else:
        interface.restore.assert_called_once_with(interface.checkpoint.return_value)

    interface.is_loaded.return_value = True
    interface.execute_query.return_value = "nat : Set"
    result = backend.search_by_type("check", "nat")
    assert result.content == "nat : Set"
    interface.execute_query.assert_called_once_with("Check nat.")
