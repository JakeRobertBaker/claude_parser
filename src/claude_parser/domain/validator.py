"""Validate inline tree annotations for structural consistency.

Checks annotation events for proper nesting, unique IDs, and semantic
rules (proves, dependencies). Returns errors (fatal) and warnings.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from claude_parser.domain.annotation_parser import AnnotationEvent
from claude_parser.domain.node import NodeType, ProveableTargetTypes


_PROVEABLE_TARGET_VALUES = {t.value for t in ProveableTargetTypes}
_VALID_NODE_TYPES = {t.value for t in NodeType}


@dataclass
class ValidationResult:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return len(self.errors) == 0


def validate_annotations(
    events: list[AnnotationEvent],
    known_ids: set[str] | None = None,
    open_stack: list[str] | None = None,
) -> ValidationResult:
    """Validate annotation events for structural and semantic correctness.

    Args:
        events: Parsed annotation events from a single batch.
        known_ids: IDs already in the tree from previous batches.
        open_stack: Nodes left open by previous batches (outer-to-inner).
            The current batch may close these as if they were opened here.
    """
    result = ValidationResult()
    known = set(known_ids) if known_ids else set()
    stack: list[str] = list(open_stack) if open_stack else []
    seen_ids: set[str] = set()
    node_types: dict[str, str | None] = {}  # id -> type for proves validation

    for event in events:
        if event.event_type == "cutoff":
            continue

        if event.event_type == "start":
            if event.id in seen_ids or event.id in known:
                result.errors.append(
                    f"Line {event.line_number}: duplicate id '{event.id}'"
                )
            seen_ids.add(event.id)
            node_types[event.id] = event.node_type
            stack.append(event.id)

            # Validate node_type value
            if event.node_type is not None and event.node_type not in _VALID_NODE_TYPES:
                result.warnings.append(
                    f"Line {event.line_number}: unknown type '{event.node_type}' "
                    f"on node '{event.id}'"
                )

            # proves on non-proof node
            if event.proves and event.node_type != "proof":
                result.warnings.append(
                    f"Line {event.line_number}: non-proof node '{event.id}' "
                    f"has proves='{event.proves}'"
                )

            # proof node without proves
            if event.node_type == "proof" and not event.proves:
                result.warnings.append(
                    f"Line {event.line_number}: proof node '{event.id}' "
                    f"missing proves attribute"
                )

            # proves target type check
            if event.proves:
                target_type = node_types.get(event.proves)
                if target_type is None and event.proves in known:
                    pass  # can't check type of previously known nodes here
                elif target_type is not None and target_type not in _PROVEABLE_TARGET_VALUES:
                    result.warnings.append(
                        f"Line {event.line_number}: proves='{event.proves}' "
                        f"targets type '{target_type}', expected one of "
                        f"{sorted(_PROVEABLE_TARGET_VALUES)}"
                    )

            # dependency references
            all_known = seen_ids | known
            for dep_id in event.dependencies:
                if dep_id not in all_known:
                    result.warnings.append(
                        f"Line {event.line_number}: dependency '{dep_id}' "
                        f"on node '{event.id}' not found"
                    )

        elif event.event_type == "end":
            if not stack:
                result.errors.append(
                    f"Line {event.line_number}: tree:end for '{event.id}' "
                    f"with no matching open node"
                )
            elif stack[-1] != event.id:
                result.errors.append(
                    f"Line {event.line_number}: improper nesting — "
                    f"expected end of '{stack[-1]}', got end of '{event.id}'"
                )
            else:
                stack.pop()

    return result
