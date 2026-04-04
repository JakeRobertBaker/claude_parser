from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class BatchResult:
    chunk_id: str
    cutoff_raw_line: int
    n_lines_cleaned: int
    notes: str | None = None


@dataclass
class SubmitCleanResponse:
    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    raw_context_lines: list[str] = field(default_factory=list)
    clean_tail_lines: list[str] = field(default_factory=list)
