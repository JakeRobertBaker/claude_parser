"""Advisories for likely source headings omitted from the annotation tree."""

from __future__ import annotations

import difflib
import html
import re
from dataclasses import dataclass
from typing import Sequence

from claude_parser.domain.annotation_parser import AnnotationEvent

_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*$")
_NUMBERED_HEADING_RE = re.compile(r"^\s*\d+(?:\.\d+)+\b")
_TEX_COMMAND_RE = re.compile(r"\\[A-Za-z]+\*?")
_WORD_RE = re.compile(r"[a-z0-9]+")
_MATCH_THRESHOLD = 0.58


@dataclass(frozen=True)
class _Heading:
    line: int
    title: str
    normalized: str


def _normalize(title: str) -> str:
    text = html.unescape(title).lower()
    text = _TEX_COMMAND_RE.sub(" ", text)
    return "".join(_WORD_RE.findall(text))


def _similar(left: _Heading, right: _Heading) -> bool:
    if not left.normalized or not right.normalized:
        return False
    if left.normalized in right.normalized or right.normalized in left.normalized:
        return True
    return (
        difflib.SequenceMatcher(
            a=left.normalized,
            b=right.normalized,
            autojunk=False,
        ).ratio()
        >= _MATCH_THRESHOLD
    )


def _matched_source_indexes(
    source: list[_Heading], annotated: list[_Heading]
) -> set[int]:
    """Return source indexes in a maximum order-preserving title match."""
    rows = len(source) + 1
    columns = len(annotated) + 1
    scores = [[0] * columns for _ in range(rows)]
    for source_index in range(1, rows):
        for annotated_index in range(1, columns):
            if _similar(
                source[source_index - 1], annotated[annotated_index - 1]
            ):
                scores[source_index][annotated_index] = (
                    scores[source_index - 1][annotated_index - 1] + 1
                )
            else:
                scores[source_index][annotated_index] = max(
                    scores[source_index - 1][annotated_index],
                    scores[source_index][annotated_index - 1],
                )

    matched: set[int] = set()
    source_index = len(source)
    annotated_index = len(annotated)
    while source_index and annotated_index:
        if (
            _similar(source[source_index - 1], annotated[annotated_index - 1])
            and scores[source_index][annotated_index]
            == scores[source_index - 1][annotated_index - 1] + 1
        ):
            matched.add(source_index - 1)
            source_index -= 1
            annotated_index -= 1
        elif (
            scores[source_index - 1][annotated_index]
            >= scores[source_index][annotated_index - 1]
        ):
            source_index -= 1
        else:
            annotated_index -= 1
    return matched


def source_heading_advisories(
    raw_lines: Sequence[str],
    cutoff_line: int,
    events: list[AnnotationEvent],
) -> list[dict[str, int | str]]:
    """Identify generic Markdown headings lacking an ordered generic-node match.

    Numbered mathematical headings are intentionally excluded: their semantic
    nodes are validated through IDs and types rather than fuzzy title matching.
    """
    source: list[_Heading] = []
    for line_number, line in enumerate(raw_lines[:cutoff_line], start=1):
        match = _HEADING_RE.match(line.rstrip("\n"))
        if match is None:
            continue
        title = match.group(1).strip()
        if _NUMBERED_HEADING_RE.match(title):
            continue
        source.append(_Heading(line_number, title, _normalize(title)))

    annotated = [
        _Heading(event.line_number, event.title, _normalize(event.title))
        for event in events
        if event.event_type == "header"
        and event.node_type is None
        and event.title is not None
    ]
    matched = _matched_source_indexes(source, annotated)
    return [
        {
            "code": "possibly_unrepresented_source_heading",
            "raw_line": heading.line,
            "title": heading.title,
        }
        for index, heading in enumerate(source)
        if index not in matched
    ]
