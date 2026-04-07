from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from claude_parser.domain.node import TreeDict


@dataclass(frozen=True)
class BatchContext:
    raw_content: str
    raw_start_line: int
    raw_end_line: int
    raw_line_count: int
    prior_clean_tail: str
    memory_text: str
    min_tokens: int


class StatePort(Protocol):
    # -- Lifecycle --
    def init(self) -> None: ...
    def init_repo(self) -> None: ...

    # -- Progression --
    @property
    def complete(self) -> bool: ...

    @property
    def sections_completed(self) -> int: ...

    # -- Current batch (valid between prepare_next and advance) --
    @property
    def current_id(self) -> str: ...

    @property
    def current_ordinal(self) -> int: ...

    @property
    def known_ids(self) -> list[str]: ...

    @property
    def tree_dict(self) -> TreeDict: ...

    def prepare_next(self, batch_tokens: int, context_lines: int) -> None: ...

    def advance(self) -> None: ...

    def get_batch_context(self) -> BatchContext: ...

    def set_cutoff(self, source_line: int) -> None: ...

    # -- Clean batches (current batch) --
    def clean_batch_exists(self) -> bool: ...
    def read_clean_batch(self) -> str | None: ...
    def write_clean_batch(self, content: str) -> None: ...
    def read_all_clean_before_cutoff(self) -> str: ...

    # -- Logging (uses current_id internally) --
    def write_log(self, content: str) -> None: ...
    def write_failure(self, content: str) -> None: ...

    # -- Final output --
    def write_final(self, content: str) -> None: ...

    # -- Version control --
    def commit_all(self, message: str) -> None: ...
