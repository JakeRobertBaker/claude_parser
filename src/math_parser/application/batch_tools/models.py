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
class CommittableRawPayload:
    """The only source text permitted in a clean submission."""

    scope: str
    content: str
    line_count: int
    token_count: int


@dataclass(slots=True)
class ReadOnlyContextPayload:
    """Boundary context that must never be copied into a submission."""

    scope: str
    prior_clean_content: str
    next_raw_content: str
    next_raw_line_count: int
    next_raw_token_count: int
    prior_continuation: PriorContinuationPayload | None
    memory_text: str


@dataclass(slots=True)
class ReadBatchPayload:
    """Response body for `read_batch` (committable raw + read-only context)."""

    committable_raw: CommittableRawPayload
    tree_context: dict[str, Any]
    known_ids: list[str]
    read_only_context: ReadOnlyContextPayload


@dataclass(slots=True)
class SubmitCleanResult:
    """Validation + alignment result produced by `submit_clean`."""

    valid: bool
    commit_ready: bool = False
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    inferred_cutoff_batch_line: int | None = None
    match_confidence: float | None = None
    committable_raw_context_around_cutoff: list[str] = field(default_factory=list)
    submitted_clean_tail: list[str] = field(default_factory=list)
    committable_raw_tail: list[str] = field(default_factory=list)
    read_only_next_raw_head: list[str] = field(default_factory=list)
    proposed_tree: dict[str, Any] = field(default_factory=dict)
    math_validation: dict[str, Any] = field(default_factory=dict)
    tree_advisories: list[dict[str, Any]] = field(default_factory=list)
    source_heading_advisories: list[dict[str, Any]] = field(default_factory=list)
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
    commit_ready: bool = False
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    applied_edits: list[dict[str, int | str]] = field(default_factory=list)
    proposed_tree: dict[str, Any] = field(default_factory=dict)
    math_validation: dict[str, Any] = field(default_factory=dict)
    tree_advisories: list[dict[str, Any]] = field(default_factory=list)
    source_heading_advisories: list[dict[str, Any]] = field(default_factory=list)


JSONLike = dict[str, Any]
