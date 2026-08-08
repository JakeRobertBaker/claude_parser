"""Shared run progression logic used by application services/adapters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Sequence


TokenCounter = Callable[[str], int]


@dataclass(frozen=True)
class RunSnapshot:
    next_start_line: int = 0
    next_chunk_id: int = 0
    sections_completed: int = 0
    continuation_node_id: str | None = None


@dataclass(frozen=True)
class BatchPlan:
    ordinal: int
    chunk_id: str
    start_line: int
    end_line: int
    next_context_end_line: int
    raw_content: str
    next_raw_context: str
    raw_line_count: int
    raw_token_count: int
    next_raw_context_line_count: int
    next_raw_context_token_count: int
    clean_token_target: int


def complete(snapshot: RunSnapshot, total_raw_lines: int) -> bool:
    return snapshot.next_start_line >= total_raw_lines


def plan_next(
    snapshot: RunSnapshot,
    raw_lines: Sequence[str],
    batch_tokens: int,
    next_raw_context_tokens: int,
    token_counter: TokenCounter,
) -> BatchPlan:
    start = snapshot.next_start_line
    if start >= len(raw_lines):
        raise RuntimeError("No raw content left to plan a batch.")

    end = start
    tokens_by_line = 0
    while end < len(raw_lines):
        tokens_by_line += token_counter(raw_lines[end])
        end += 1
        if tokens_by_line >= batch_tokens:
            break

    next_context_end = end
    next_context_tokens_by_line = 0
    while (
        next_context_end < len(raw_lines)
        and next_context_tokens_by_line < next_raw_context_tokens
    ):
        next_context_tokens_by_line += token_counter(raw_lines[next_context_end])
        next_context_end += 1

    raw_content = "".join(raw_lines[start:end])
    next_raw_context = "".join(raw_lines[end:next_context_end])
    raw_line_count = end - start
    raw_tokens = token_counter(raw_content)
    next_context_token_count = token_counter(next_raw_context)
    clean_token_target = max(1, int(raw_tokens * 0.5))

    ordinal = snapshot.next_chunk_id
    chunk_id = f"chunk_{ordinal:03d}"

    return BatchPlan(
        ordinal=ordinal,
        chunk_id=chunk_id,
        start_line=start,
        end_line=end,
        next_context_end_line=next_context_end,
        raw_content=raw_content,
        next_raw_context=next_raw_context,
        raw_line_count=raw_line_count,
        raw_token_count=raw_tokens,
        next_raw_context_line_count=next_context_end - end,
        next_raw_context_token_count=next_context_token_count,
        clean_token_target=clean_token_target,
    )


def clamp_cutoff(plan: BatchPlan, source_line: int) -> int:
    lower = plan.start_line + 1
    upper = plan.end_line
    if upper <= lower:
        upper = lower
    return max(lower, min(source_line, upper))


def advance(
    snapshot: RunSnapshot,
    cutoff_line: int,
    continuation_node_id: str | None = None,
) -> RunSnapshot:
    return RunSnapshot(
        next_start_line=cutoff_line,
        next_chunk_id=snapshot.next_chunk_id + 1,
        sections_completed=snapshot.sections_completed + 1,
        continuation_node_id=continuation_node_id,
    )
