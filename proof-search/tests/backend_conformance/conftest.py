import pytest

from tests.backend_conformance.rocq import create_case


@pytest.fixture(params=[pytest.param(create_case, id="rocq")])
def case_factory(request, tmp_path):
    """Each registered backend runs the same contract tests."""
    count = 0

    def create(scenario="branch"):
        nonlocal count
        directory = tmp_path / str(count)
        count += 1
        directory.mkdir()
        case = request.param(directory, scenario)
        request.addfinalizer(case.backend.close)
        assert case.backend.load(), case.backend.get_last_error()
        return case

    return create


@pytest.fixture
def case(case_factory):
    return case_factory()
