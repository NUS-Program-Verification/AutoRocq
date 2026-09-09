from backend.coq_interface import CoqInterface
from tests.test_utils import temp_example_copy


def test_focused_hypotheses_keep_names_types_and_values():
    interface = CoqInterface(str(temp_example_copy("example.v")))
    assert interface.load(), interface.get_last_error()
    try:
        assert interface.apply_tactic("intros b."), interface.get_last_error()
        assert interface.apply_tactic("set (y := true)."), interface.get_last_error()

        rendered = interface.get_hypothesis().splitlines()
        assert rendered == ["b : bool", "y := true : bool"]
    finally:
        interface.close()
