from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ReadBatchPayload:
    raw_content: str
    batch_line_count: int
    current_tree: str
    prior_clean_tail: str
    known_ids: list[str]
    memory_text: str


@dataclass(slots=True)
class SubmitCleanResult:
    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    inferred_cutoff_batch_line: int | None = None
    match_confidence: float | None = None
    raw_context_around_cutoff: list[str] = field(default_factory=list)
    clean_tail: list[str] = field(default_factory=list)
    proposed_tree: str = ""


@dataclass(slots=True)
class CommitResult:
    success: bool
    error: str | None = None


JSONLike = dict[str, Any]
