from dataclasses import dataclass
from typing import Any, Dict, Literal, Hashable


@dataclass(frozen=True)
class Goal:
    """A proof goal whose ID is unique and stays the same while it remains open."""
    goal_id: Hashable
    conclusion: str
    hypotheses: str = ""


@dataclass(frozen=True)
class CompletionStatus:
    ready_to_finalize: bool
    finalized: bool


@dataclass
class SearchResult:
    """Represents a search result and how it was reduced."""
    content: str
    source: str
    metadata: Dict[str, Any] = None
    result_size: int = 0
    original_size: int = 0  # Track original size before reduction
    reduction_applied: str = None  # Track what reduction was applied


@dataclass(frozen=True)
class TacticEffect:
    """How a command affects the ordered goals.

    "single" selects target_index before the command.
    "focus" reorders goals.
    "all" applies to every goal, as required by the proof tree.
    """
    kind: Literal["single", "all", "focus"] = "single"
    target_index: int = 0
