import pytest


@pytest.fixture
def history_backend(tmp_path):
    """History analysis uses backend text methods without starting a prover."""
    from prover_backends.rocq.backend import RocqBackend
    from tests.test_utils import create_coq_interface

    source = tmp_path / "history.v"
    source.write_text("Theorem history : True.\nProof.\nAdmitted.\n")
    interface = create_coq_interface(source, load=False)
    try:
        yield RocqBackend(interface)
    finally:
        interface.close()


@pytest.fixture(scope="module")
def coq_factory(request):
    from tests.test_utils import create_coq_interface

    def create(*args, **kwargs):
        interface = create_coq_interface(*args, **kwargs)
        request.addfinalizer(interface.close)
        return interface

    return create


@pytest.fixture
def coq():
    from tests.test_utils import create_coq_interface, temp_example_copy

    interface = create_coq_interface(temp_example_copy("example.v"))
    yield interface
    interface.close()


def pytest_addoption(parser):
    parser.addoption(
        "--runllm",
        action="store_true",
        default=False,
        help="run tests that call the LLM API (needs a valid api_key and costs money)",
    )
    parser.addoption(
        "--runexperiment",
        action="store_true",
        default=False,
        help="run full experiments (slow and potentially expensive)",
    )


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "llm: mark test as requiring a live LLM API key"
    )
    config.addinivalue_line(
        "markers", "experiment: mark a full experiment excluded from regular test runs"
    )


def pytest_collection_modifyitems(config, items):
    skip_llm = pytest.mark.skip(reason="need --runllm option to run")
    skip_experiment = pytest.mark.skip(reason="need --runexperiment option to run")
    for item in items:
        if "llm" in item.keywords and not config.getoption("--runllm"):
            item.add_marker(skip_llm)
        if "experiment" in item.keywords and not config.getoption("--runexperiment"):
            item.add_marker(skip_experiment)
