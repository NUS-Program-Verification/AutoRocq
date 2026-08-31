import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--runllm",
        action="store_true",
        default=False,
        help="run tests that call the LLM API (needs a valid api_key and costs money)",
    )


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "llm: mark test as requiring a live LLM API key"
    )


def pytest_collection_modifyitems(config, items):
    if config.getoption("--runllm"):
        return
    skip_llm = pytest.mark.skip(reason="need --runllm option to run")
    for item in items:
        if "llm" in item.keywords:
            item.add_marker(skip_llm)
