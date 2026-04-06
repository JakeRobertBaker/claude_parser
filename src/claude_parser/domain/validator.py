"""Validate parsed annotation headers and batch-level constraints."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from claude_parser.domain.annotation_parser import AnnotationEvent
from claude_parser.domain.node import NodeType, ProveableTargetTypes


_PROVEABLE_TARGET_VALUES = {t.value for t in ProveableTargetTypes}
_VALID_NODE_TYPES = {t.value for t in NodeType}
_CUTOFF_RE = re.compile(r"<!--\s*cutoff\s*-->")


@dataclass
class ValidationResult:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return len(self.errors) == 0


def _leading_nonempty_content_before_first_header(cleaned_text: str) -> bool:
    lines = cleaned_text.splitlines()
    for line in lines:
        if _CUTOFF_RE.search(line):
            break
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("@"):
            return False
        return True
    return False


def validate_annotations(
    events: list[AnnotationEvent],
    known_ids: set[str] | None = None,
    *,
    cleaned_text: str | None = None,
    has_existing_nodes: bool = False,
) -> ValidationResult:
    """Validate annotation events for semantic and batch-level correctness.

    Args:
        events: Parsed annotation events from a single batch.
        known_ids: IDs already in the tree from previous batches.
        cleaned_text: Full cleaned text for this batch (optional).
        has_existing_nodes: Whether the tree already has visible nodes before
            applying this batch.
    """
    result = ValidationResult()
    known = set(known_ids) if known_ids else set()
    seen_ids: set[str] = set()
    node_types: dict[str, str | None] = {}

    if cleaned_text is not None and not has_existing_nodes:
        if _leading_nonempty_content_before_first_header(cleaned_text):
            result.errors.append(
                "Batch starts with content before the first node header. "
                "Start the document with a depth-1 header like '@ - id=...'."
            )

    for event in events:
        if event.event_type != "header":
            continue

        if event.id in seen_ids or event.id in known:
            result.errors.append(f"Line {event.line_number}: duplicate id '{event.id}'")
        seen_ids.add(event.id)
        node_types[event.id] = event.node_type

        if event.node_type is not None and event.node_type not in _VALID_NODE_TYPES:
            result.warnings.append(
                f"Line {event.line_number}: unknown type '{event.node_type}' "
                f"on node '{event.id}'"
            )

        if event.proves and event.node_type != "proof":
            result.warnings.append(
                f"Line {event.line_number}: non-proof node '{event.id}' "
                f"has proves='{event.proves}'"
            )

        if event.node_type == "proof" and not event.proves:
            result.warnings.append(
                f"Line {event.line_number}: proof node '{event.id}' "
                "missing proves attribute"
            )

        if event.proves:
            target_type = node_types.get(event.proves)
            if target_type is None and event.proves in known:
                pass
            elif (
                target_type is not None and target_type not in _PROVEABLE_TARGET_VALUES
            ):
                result.warnings.append(
                    f"Line {event.line_number}: proves='{event.proves}' "
                    f"targets type '{target_type}', expected one of "
                    f"{sorted(_PROVEABLE_TARGET_VALUES)}"
                )

        all_known = seen_ids | known
        for dep_id in event.deps:
            if dep_id not in all_known:
                result.warnings.append(
                    f"Line {event.line_number}: dependency '{dep_id}' "
                    f"on node '{event.id}' not found"
                )

    return result
