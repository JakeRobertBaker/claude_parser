"""Token-based cutoff alignment for cleaned batches."""

from __future__ import annotations

import difflib
import re
from typing import Sequence

_WORD_RE = re.compile(r"[a-z]{4,}")
_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_MATH_BLOCK_RE = re.compile(r"\$\$.*?\$\$", re.DOTALL)
_MATH_INLINE_RE = re.compile(r"\$[^$\n]*?\$")
_NODE_LINE_RE = re.compile(r"^\s*@\s*-+\s+.*$", re.MULTILINE)


def _content_tokens(text: str) -> list[str]:
    text = _COMMENT_RE.sub(" ", text)
    text = _NODE_LINE_RE.sub(" ", text)
    text = _MATH_BLOCK_RE.sub(" ", text)
    text = _MATH_INLINE_RE.sub(" ", text)
    return _WORD_RE.findall(text.lower())


def infer_cutoff_line(
    cleaned_text: str, raw_lines: Sequence[str]
) -> tuple[int, float] | None:
    cleaned_toks = _content_tokens(cleaned_text)
    if len(cleaned_toks) < 20:
        return None

    raw_toks: list[str] = []
    tok_to_line: list[int] = []
    for idx, line in enumerate(raw_lines):
        for token in _content_tokens(line):
            raw_toks.append(token)
            tok_to_line.append(idx + 1)

    if not raw_toks:
        return None

    sm = difflib.SequenceMatcher(a=cleaned_toks, b=raw_toks, autojunk=False)
    blocks = [block for block in sm.get_matching_blocks() if block.size > 0]
    if not blocks:
        return None

    last = blocks[-1]
    raw_end_tok_idx = last.b + last.size - 1
    cutoff_line = tok_to_line[raw_end_tok_idx]
    confidence = sum(block.size for block in blocks) / len(cleaned_toks)
    return cutoff_line, confidence
