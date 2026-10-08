from tests.test_utils import temp_example_copy, create_coq_interface


def test_focused_hypotheses_keep_names_types_and_values():
    interface = create_coq_interface(str(temp_example_copy("example.v")))
    try:
        assert interface.apply_tactic("intros b."), interface.get_last_error()
        assert interface.apply_tactic("set (y := true)."), interface.get_last_error()

        rendered = interface.get_hypothesis().splitlines()
        assert rendered == ["b : bool", "y := true : bool"]
    finally:
        interface.close()
