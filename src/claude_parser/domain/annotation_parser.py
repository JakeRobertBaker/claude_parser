"""Parse inline tree annotations from markdown text.

Annotations are HTML comments of the form:
    <!-- tree:start id="node_id" title="Node Title" [type="theorem"] ... -->
    <!-- tree:end id="node_id" -->
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
    anc: str | None = None
    proves: str | None = None
    dependencies: list[str] = field(default_factory=list)


_ATTR_RE = re.compile(r'(\w+)="([^"]*)"')

_START_RE = re.compile(r"<!--\s*tree:start\s+(.*?)\s*-->")
_END_RE = re.compile(r'<!--\s*tree:end\s+id="([^"]+)"\s*-->')
_CUTOFF_RE = re.compile(r"<!--\s*cutoff\s*-->")


def _parse_attrs(attr_str: str) -> dict[str, str]:
    return dict(_ATTR_RE.findall(attr_str))


def parse_annotations(text: str) -> list[AnnotationEvent]:
    """Parse all tree:start, tree:end, and cutoff comments from markdown text."""
    events: list[AnnotationEvent] = []

    for line_number, line in enumerate(text.splitlines(), start=1):
        start_match = _START_RE.search(line)
        if start_match:
            attrs = _parse_attrs(start_match.group(1))
            node_id = attrs.get("id", "")
            if not node_id:
                continue
            deps_str = attrs.get("dependencies", "")
            deps = [d.strip() for d in deps_str.split(",") if d.strip()] if deps_str else []
            events.append(AnnotationEvent(
                line_number=line_number,
                event_type="start",
                id=node_id,
                title=attrs.get("title"),
                node_type=attrs.get("type"),
                anc=attrs.get("anc"),
                proves=attrs.get("proves"),
                dependencies=deps,
            ))
            continue

        end_match = _END_RE.search(line)
        if end_match:
            events.append(AnnotationEvent(
                line_number=line_number,
                event_type="end",
                id=end_match.group(1),
            ))
            continue

        if _CUTOFF_RE.search(line):
            events.append(AnnotationEvent(
                line_number=line_number,
                event_type="cutoff",
                id="",
            ))

    return events
