import pytest

from prover_backends.rocq.session import RocqSessionDesync
from prover_backends.rocq.backend import RocqBackend
from tests.test_utils import create_coq_interface


@pytest.fixture
def backend(tmp_path):
    source = tmp_path / "adapter.v"
    source.write_text("Theorem t : True.\nProof.\nAdmitted.\n")
    interface = create_coq_interface(source)
    yield RocqBackend(interface)
    interface.close()


def test_unavailable_goals_raise_instead_of_appearing_solved(backend, monkeypatch):
    checkpoint = backend.checkpoint()
    with monkeypatch.context() as patch:
        patch.setattr(backend._interface, "_get_current_goals_cached", lambda: None)
        with pytest.raises(RocqSessionDesync, match="unavailable"):
            backend.get_goals()
        with pytest.raises(RocqSessionDesync, match="unavailable"):
            backend.apply_tactic("exact I.")
        assert not backend.completion_status().finalized
    assert backend.matches_checkpoint(checkpoint)
    assert backend.get_goals()[0].conclusion == "True"


def test_lost_goal_response_after_command_restores_prior_state(backend, monkeypatch):
    checkpoint = backend.checkpoint()
    before = backend.get_goals(), backend.get_proof_file_content()
    native_apply = backend._interface.apply_tactic
    with monkeypatch.context() as patch:
        def lose_response(command):
            result = native_apply(command)
            patch.setattr(backend._interface, "_get_current_goals_cached", lambda: None)
            return result

        patch.setattr(backend._interface, "apply_tactic", lose_response)
        with pytest.raises(RocqSessionDesync, match="unavailable"):
            backend.apply_tactic("idtac.")
    assert backend.matches_checkpoint(checkpoint)
    assert (backend.get_goals(), backend.get_proof_file_content()) == before


def test_failed_native_undo_raises_instead_of_claiming_restoration(backend, monkeypatch):
    initial = backend.checkpoint()
    assert backend.apply_tactic("pose proof I.")
    current = backend.checkpoint()
    before = backend.get_goals(), backend.get_proof_file_content()
    with monkeypatch.context() as patch:
        patch.setattr(backend._interface.proof_file, "pop_step", lambda proof: None)
        with pytest.raises(RocqSessionDesync, match="did not remove"):
            backend.restore(initial)
    assert backend.matches_checkpoint(current)
    assert (backend.get_goals(), backend.get_proof_file_content()) == before
    backend.restore(initial)
    assert backend.matches_checkpoint(initial)


def test_relocated_interactor_and_cache_need_no_top_level_package(tmp_path, monkeypatch):
    import subprocess
    import sys
    from pathlib import Path

    from prover_backends.rocq.coqpyt.coq.proof_file import _AuxFile
    from prover_backends.rocq.coqpyt.coq.structs import Step, Term, TermType

    cache_path = tmp_path / _AuxFile.CACHE_NAME
    legacy_path = tmp_path / 'coqpyt_cache'
    legacy_path.mkdir()
    (legacy_path / 'library').write_bytes(b'incompatible legacy pickle')
    monkeypatch.setattr(_AuxFile, 'get_coqpyt_disk_cache_loc', classmethod(lambda cls: str(cache_path)))
    assert _AuxFile.get_from_disk_cache('library') is None
    term = Term(Step('Lemma t : True.', 't', None), TermType.LEMMA, 'proof.v', [])
    _AuxFile.to_disk_cache('library', {'t': term})

    script = '''
import importlib.abc
import sys
class RejectLegacy(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, *args):
        if fullname == "coqpyt" or fullname.startswith("coqpyt."):
            raise AssertionError("Top-level CoqPyt import: " + fullname)
sys.meta_path.insert(0, RejectLegacy())
from prover_backends.rocq.backend import RocqBackend
from prover_backends.rocq.session import RocqSession
from prover_backends.rocq.coqpyt.coq.proof_file import _AuxFile
from prover_backends.rocq.coqpyt.coq.structs import Term, TermType
_AuxFile.get_coqpyt_disk_cache_loc = classmethod(lambda cls: sys.argv[1])
term = _AuxFile.get_from_disk_cache('library')['t']
assert isinstance(term, Term) and term.type is TermType.LEMMA and term.text == 't'
assert 'coqpyt' not in sys.modules
'''
    result = subprocess.run([sys.executable, '-c', script, str(cache_path)],
                            cwd=Path(__file__).resolve().parents[1],
                            text=True, capture_output=True, timeout=60)
    assert result.returncode == 0, result.stderr
    assert (legacy_path / 'library').read_bytes() == b'incompatible legacy pickle'
