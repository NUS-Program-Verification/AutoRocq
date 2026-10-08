from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from tests.test_utils import create_coq_interface, create_proof_file


@pytest.fixture
def session(monkeypatch):
    session = Mock()
    session.load.return_value = True
    session.get_last_error.return_value = "load failed"
    for target in ("backend.coq_interface.CoqInterface", "coqpyt.coq.proof_file.ProofFile"):
        monkeypatch.setattr(target, Mock(return_value=session))
    return session


def test_interface_preserves_configuration_and_loads_once(session):
    from backend.coq_interface import CoqInterface

    options = dict(workspace="/stable/workspace", library_paths=[{"path": "/lib", "name": "lib"}],
                   auto_setup_coqproject=False, coqproject_extra_options=["-w", "-all"], timeout=60)
    config = SimpleNamespace(coq=SimpleNamespace(**options))
    assert create_coq_interface("/proof.v", config=config, timeout=90) is session
    CoqInterface.assert_called_once_with("/proof.v", **(options | {"timeout": 90}))
    session.load.assert_called_once_with()
    assert vars(config.coq) == options


def test_interface_can_defer_loading(session):
    create_coq_interface("/proof.v", load=False)
    session.load.assert_not_called()


def test_raw_session_uses_disk_cache(session):
    from coqpyt.coq.proof_file import ProofFile

    create_proof_file("/proof.v", timeout=60)
    ProofFile.assert_called_once_with("/proof.v", timeout=60, use_disk_cache=True)
    session.run.assert_called_once_with()


@pytest.mark.parametrize("factory,error", [(create_coq_interface, AssertionError),
                                          (create_proof_file, RuntimeError)])
def test_failed_initialization_closes_session(session, factory, error):
    session.load.return_value = False
    session.run.side_effect = RuntimeError("load failed")
    with pytest.raises(error, match="load failed"):
        factory("/proof.v")
    session.close.assert_called_once_with()
