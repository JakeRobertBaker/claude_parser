"""Shared run progression logic used by state stores."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Sequence


TokenCounter = Callable[[str], int]


@dataclass(frozen=True)
class RunSnapshot:
    next_start_line: int = 0
    next_chunk_id: int = 0
    sections_completed: int = 0


@dataclass(frozen=True)
class BatchPlan:
    ordinal: int
    chunk_id: str
    start_line: int
    end_line: int
    raw_content: str
    raw_line_count: int
    min_tokens: int


class RunEngine:
    def __init__(self, token_counter: TokenCounter):
        self._token_counter = token_counter

    def complete(self, snapshot: RunSnapshot, total_raw_lines: int) -> bool:
        return snapshot.next_start_line >= total_raw_lines

    def plan_next(
        self,
        snapshot: RunSnapshot,
        raw_lines: Sequence[str],
        batch_tokens: int,
    ) -> BatchPlan:
        start = snapshot.next_start_line
        if start >= len(raw_lines):
            raise RuntimeError("No raw content left to plan a batch.")

        end = start
        tokens = 0
        while end < len(raw_lines):
            tokens += self._token_counter(raw_lines[end])
            end += 1
            if tokens >= batch_tokens:
                break

        raw_content = "".join(raw_lines[start:end])
        raw_line_count = end - start
        raw_tokens = self._token_counter(raw_content)
        min_tokens = max(1, int(raw_tokens * 0.5))

        ordinal = snapshot.next_chunk_id
        chunk_id = f"chunk_{ordinal:03d}"

        return BatchPlan(
            ordinal=ordinal,
            chunk_id=chunk_id,
            start_line=start,
            end_line=end,
            raw_content=raw_content,
            raw_line_count=raw_line_count,
            min_tokens=min_tokens,
        )

    def clamp_cutoff(self, plan: BatchPlan, source_line: int) -> int:
        lower = plan.start_line + 1
        upper = plan.end_line
        if upper <= lower:
            upper = lower
        return max(lower, min(source_line, upper))

    def advance(self, snapshot: RunSnapshot, cutoff_line: int) -> RunSnapshot:
        return RunSnapshot(
            next_start_line=cutoff_line,
            next_chunk_id=snapshot.next_chunk_id + 1,
            sections_completed=snapshot.sections_completed + 1,
        )
