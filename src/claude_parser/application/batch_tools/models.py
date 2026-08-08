"""Typed payloads exchanged between BatchToolsService and transports."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class PriorContinuationPayload:
    """Explicit semantic unit continued from the preceding batch."""

    node_id: str
    title: str
    node_type: str
    depth: int
    proves_id: str | None = None
    dependency_ids: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ReadBatchPayload:
    """Response body for `read_batch` (committable raw + read-only context)."""

    raw_content: str
    batch_line_count: int
    raw_token_count: int
    tree_context: dict[str, Any]
    prior_clean_context: str
    next_raw_context: str
    next_raw_context_line_count: int
    next_raw_context_token_count: int
    prior_continuation: PriorContinuationPayload | None
    known_ids: list[str]
    memory_text: str


@dataclass(slots=True)
class SubmitCleanResult:
    """Validation + alignment result produced by `submit_clean`."""

    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    inferred_cutoff_batch_line: int | None = None
    match_confidence: float | None = None
    raw_context_around_cutoff: list[str] = field(default_factory=list)
    clean_tail: list[str] = field(default_factory=list)
    proposed_tree: dict[str, Any] = field(default_factory=dict)
    math_validation: dict[str, Any] = field(default_factory=dict)
    batch_line_count: int | None = None
    rollback_lines: int = 0
    next_raw_context_violation: bool = False
    cutoff_kind: str | None = None
    continuation_node_id: str | None = None


@dataclass(slots=True)
class CommitResult:
    """Response body for `commit_batch`."""

    success: bool
    error: str | None = None


@dataclass(slots=True)
class AdjustDepthsResult:
    """Result of transactionally changing current-batch annotation depths."""

    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    applied_edits: list[dict[str, int | str]] = field(default_factory=list)
    proposed_tree: dict[str, Any] = field(default_factory=dict)
    math_validation: dict[str, Any] = field(default_factory=dict)


JSONLike = dict[str, Any]
