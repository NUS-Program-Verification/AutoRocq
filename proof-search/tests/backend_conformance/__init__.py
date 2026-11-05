"""Fixtures keep prover syntax out of the shared assertions."""

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from prover_backends.base import ProverBackend


@dataclass(frozen=True)
class BackendCase:
    """Fixtures for proving that P implies P and P.

    The two branch goals must have identical text and different IDs.
    verify_export must use the prover to reject unfinished or admitted proofs.
    """

    backend: ProverBackend
    source: Path
    introduce: str
    branch: str
    change_hypotheses: str
    focus_second: str
    solve_one: str
    solve_second: str
    solve_all: str
    rejected: dict[str, str]
    query: str
    query_identifier: str
    missing_identifier: str
    empty_search: str
    empty_result: str
    checkpoint_error: type[Exception]
    verify_export: Callable[[str], None]


@dataclass(frozen=True)
class SharedWitnessCase:
    """Two branches constrain one unresolved witness; solving one updates both."""

    backend: ProverBackend
    source: Path
    create_witness: str
    branch: str
    solve_one: str
    verify_export: Callable[[str], None]
