"""Token-based cutoff alignment for cleaned batches."""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from typing import Sequence

_WORD_RE = re.compile(r"[a-z0-9]{3,}")
_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_MATH_BLOCK_RE = re.compile(r"\$\$.*?\$\$", re.DOTALL)
_MATH_INLINE_RE = re.compile(r"\$[^$\n]*?\$")
_NODE_LINE_RE = re.compile(r"^\s*@\s*-+\s+.*$", re.MULTILINE)
_MIN_CLEANED_CONTENT_TOKENS = 20


@dataclass(frozen=True)
class CutoffAlignmentResult:
    """Outcome details for token-based cutoff alignment."""

    ok: bool
    cutoff_line: int | None
    confidence: float | None
    cleaned_token_count: int
    raw_token_count: int
    matched_token_count: int
    cutoff_token_count: int | None
    min_cleaned_token_requirement: int
    error_code: str | None = None


def _content_tokens(text: str) -> list[str]:
    text = _COMMENT_RE.sub(" ", text)
    text = _NODE_LINE_RE.sub(" ", text)
    text = _MATH_BLOCK_RE.sub(" ", text)
    text = _MATH_INLINE_RE.sub(" ", text)
    return _WORD_RE.findall(text.lower())


def infer_cutoff_line(
    cleaned_text: str, raw_lines: Sequence[str]
) -> CutoffAlignmentResult:
    cleaned_toks = _content_tokens(cleaned_text)
    raw_toks: list[str] = []
    tok_to_line: list[int] = []
    for idx, line in enumerate(raw_lines):
        for token in _content_tokens(line):
            raw_toks.append(token)
            tok_to_line.append(idx + 1)

    raw_token_count = len(raw_toks)
    min_cleaned_tokens = min(_MIN_CLEANED_CONTENT_TOKENS, raw_token_count)

    if raw_token_count == 0:
        return CutoffAlignmentResult(
            ok=False,
            cutoff_line=None,
            confidence=None,
            cleaned_token_count=len(cleaned_toks),
            raw_token_count=0,
            matched_token_count=0,
            cutoff_token_count=None,
            min_cleaned_token_requirement=0,
            error_code="raw_has_no_content_tokens",
        )

    if len(cleaned_toks) < min_cleaned_tokens:
        return CutoffAlignmentResult(
            ok=False,
            cutoff_line=None,
            confidence=None,
            cleaned_token_count=len(cleaned_toks),
            raw_token_count=raw_token_count,
            matched_token_count=0,
            cutoff_token_count=None,
            min_cleaned_token_requirement=min_cleaned_tokens,
            error_code="cleaned_too_short_for_alignment",
        )

    sm = difflib.SequenceMatcher(a=cleaned_toks, b=raw_toks, autojunk=False)
    blocks = [block for block in sm.get_matching_blocks() if block.size > 0]
    if not blocks:
        return CutoffAlignmentResult(
            ok=False,
            cutoff_line=None,
            confidence=None,
            cleaned_token_count=len(cleaned_toks),
            raw_token_count=raw_token_count,
            matched_token_count=0,
            cutoff_token_count=None,
            min_cleaned_token_requirement=min_cleaned_tokens,
            error_code="no_token_overlap",
        )

    last = blocks[-1]
    raw_end_tok_idx = last.b + last.size - 1
    cutoff_line = tok_to_line[raw_end_tok_idx]
    matched_token_count = sum(block.size for block in blocks)
    confidence = matched_token_count / len(cleaned_toks)
    return CutoffAlignmentResult(
        ok=True,
        cutoff_line=cutoff_line,
        confidence=confidence,
        cleaned_token_count=len(cleaned_toks),
        raw_token_count=raw_token_count,
        matched_token_count=matched_token_count,
        cutoff_token_count=raw_end_tok_idx + 1,
        min_cleaned_token_requirement=min_cleaned_tokens,
        error_code=None,
    )
