"""Conservative structural checks for semantic batch boundaries."""

from __future__ import annotations

import re
from collections.abc import Sequence


_MARKDOWN_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$")
_SEMANTIC_UNIT_RE = re.compile(
    r"\b(?:definition|theorem|lemma|proposition|corollary|proof|remark|example|exercise|axiom)\b",
    re.IGNORECASE,
)


def incomplete_trailing_semantic_unit_start(
    raw_lines: Sequence[str],
    next_raw_context_lines: Sequence[str],
) -> int | None:
    """Return the 1-based start line of a semantic unit continued in context.

    The check is deliberately narrow. A recognized semantic Markdown heading must
    be the final heading in ``raw_lines``, and the following context must begin with
    substantive content before its first heading. In Markdown, that content still
    belongs to the trailing headed unit.
    """
    first_following_content = next(
        (line for line in next_raw_context_lines if line.strip()),
        None,
    )
    if first_following_content is None or _MARKDOWN_HEADING_RE.match(
        first_following_content
    ):
        return None

    last_heading_line: int | None = None
    last_heading_title: str | None = None
    for line_number, line in enumerate(raw_lines, start=1):
        match = _MARKDOWN_HEADING_RE.match(line)
        if match is not None:
            last_heading_line = line_number
            last_heading_title = match.group(1)

    if (
        last_heading_line is None
        or last_heading_title is None
        or _SEMANTIC_UNIT_RE.search(last_heading_title) is None
    ):
        return None
    return last_heading_line
