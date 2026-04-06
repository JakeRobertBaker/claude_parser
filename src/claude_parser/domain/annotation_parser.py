"""Parse inline tree annotations from markdown text.

Node headers use the new depth-marked form:
    @ --- id="node_id" title="Node Title" [type="theorem"] [deps=["a"]]

Depth transitions generate implicit start/end events. The parser still reads
the explicit cutoff marker:
    <!-- cutoff -->
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class AnnotationEvent:
    line_number: int  # 1-indexed
    event_type: str  # "start" | "end" | "cutoff"
    id: str  # required for start/end, empty for cutoff
    title: str | None = None  # required on start
    node_type: str | None = None
    proves: str | None = None
    deps: list[str] = field(default_factory=list)


_ATTR_RE = re.compile(r'(\w+)=("[^"]*"|\[[^\]]*\]|[^\s]+)')

_NODE_RE = re.compile(r"^\s*@\s*(-+)\s+(.*?)\s*$")
_CUTOFF_RE = re.compile(r"<!--\s*cutoff\s*-->")


def _parse_attrs(attr_str: str) -> dict[str, str]:
    attrs: dict[str, str] = {}
    for key, raw_value in _ATTR_RE.findall(attr_str):
        value = raw_value.strip()
        if value.startswith('"') and value.endswith('"'):
            value = value[1:-1]
        attrs[key] = value
    return attrs


def _parse_deps(value: str | None) -> list[str]:
    if not value:
        return []
    text = value.strip()
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1]
    deps: list[str] = []
    for part in text.split(","):
        dep = part.strip().strip('"').strip("'")
        if dep:
            deps.append(dep)
    return deps


def parse_annotations(
    text: str, open_stack: list[str] | None = None
) -> list[AnnotationEvent]:
    """Parse start/end/cutoff events from depth-marked annotation headers.

    Args:
        text: Cleaned markdown with inline annotation headers.
        open_stack: IDs already open from prior batches (outer-to-inner).
            Used to resolve implicit closes when current batch depth decreases.
    """
    events: list[AnnotationEvent] = []
    stack = list(open_stack) if open_stack else []

    for line_number, line in enumerate(text.splitlines(), start=1):
        if _CUTOFF_RE.search(line):
            events.append(
                AnnotationEvent(
                    line_number=line_number,
                    event_type="cutoff",
                    id="",
                )
            )
            break

        node_match = _NODE_RE.match(line)
        if not node_match:
            continue

        depth = len(node_match.group(1))
        attrs = _parse_attrs(node_match.group(2))
        node_id = attrs.get("id", "")
        if not node_id:
            continue

        while len(stack) >= depth:
            events.append(
                AnnotationEvent(
                    line_number=line_number,
                    event_type="end",
                    id=stack.pop(),
                )
            )

        deps_value = attrs.get("deps")
        if deps_value is None:
            deps_value = attrs.get("dependencies")
        deps = _parse_deps(deps_value)

        events.append(
            AnnotationEvent(
                line_number=line_number,
                event_type="start",
                id=node_id,
                title=attrs.get("title"),
                node_type=attrs.get("type"),
                proves=attrs.get("proves"),
                deps=deps,
            )
        )
        stack.append(node_id)

    return events
