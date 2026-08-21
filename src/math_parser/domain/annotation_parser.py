"""Parse depth-marked annotation headers from cleaned markdown.

Node headers use the form:
    @ --- id="node_id" title="Node Title" [type="theorem"] [deps=["a"]]

The parser also recognizes the explicit cutoff marker:
    <!-- cutoff -->
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class AnnotationEvent:
    line_number: int  # 1-indexed
    event_type: str  # "header" | "cutoff"
    id: str = ""  # required for header
    depth: int = 0  # required for header (visible depth: '-'=1, '--'=2, ...)
    title: str | None = None
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


def parse_annotations(text: str) -> list[AnnotationEvent]:
    """Parse header/cutoff events from cleaned markdown."""
    events: list[AnnotationEvent] = []

    for line_number, line in enumerate(text.splitlines(), start=1):
        if _CUTOFF_RE.search(line):
            events.append(
                AnnotationEvent(
                    line_number=line_number,
                    event_type="cutoff",
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

        events.append(
            AnnotationEvent(
                line_number=line_number,
                event_type="header",
                id=node_id,
                depth=depth,
                title=attrs.get("title"),
                node_type=attrs.get("type"),
                proves=attrs.get("proves"),
                deps=_parse_deps(attrs.get("deps")),
            )
        )

    return events
