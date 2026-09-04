from pathlib import Path

import pytest


COQPYT_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def run_from_coqpyt_root(monkeypatch):
    """Keep CoqPyt's relative test-resource paths valid from a parent suite."""
    monkeypatch.chdir(COQPYT_ROOT)


def pytest_addoption(parser):
    parser.addoption(
        "--runextra",
        action="store_true",
        default=False,
        help="run extra tests from external libraries",
    )


def pytest_configure(config):
    config.addinivalue_line("markers", "extra: mark test as from external library")


def pytest_collection_modifyitems(config, items):
    if config.getoption("--runextra"):
        return
    skip_extra = pytest.mark.skip(reason="need --runextra option to run")
    for item in items:
        if "extra" in item.keywords:
            item.add_marker(skip_extra)
