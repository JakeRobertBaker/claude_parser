from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, Sequence

from claude_parser.application.run_engine import RunSnapshot

if TYPE_CHECKING:
    from claude_parser.domain.node import TreeDict


@dataclass(frozen=True)
class BatchContext:
    """Snapshot of batch metadata exposed to parsing + MCP services."""

    raw_content: str
    raw_start_line: int
    raw_end_line: int
    raw_line_count: int
    raw_token_count: int
    next_raw_context: str
    next_raw_context_line_count: int
    next_raw_context_token_count: int
    prior_clean_context: str
    prior_continuation_node_id: str | None
    memory_text: str
    clean_token_target: int


class StatePort(Protocol):
    """Abstraction for persistence and run artifacts."""

    # -- Lifecycle --
    def init(self) -> None: ...
    def init_repo(self) -> None: ...

    # -- Run state --
    @property
    def raw_lines(self) -> Sequence[str]: ...

    @property
    def snapshot(self) -> RunSnapshot: ...

    def save_snapshot(self, snapshot: RunSnapshot) -> None: ...

    @property
    def known_ids(self) -> list[str]: ...

    @property
    def tree_dict(self) -> TreeDict: ...

    def save_tree(self) -> None: ...

    # -- Context helpers --
    def read_prior_clean(self, ordinal: int) -> str: ...
    def read_memory(self) -> str: ...

    # -- Batch artifacts --
    def write_raw_batch(self, ordinal: int, content: str) -> None: ...
    def write_next_raw_context(self, ordinal: int, content: str) -> None: ...
    def clean_batch_exists(self, ordinal: int) -> bool: ...
    def read_clean_batch(self, ordinal: int) -> str | None: ...
    def write_clean_batch(self, ordinal: int, content: str) -> None: ...
    def read_all_clean_before_cutoff(self) -> str: ...

    # -- Logging --
    def write_log(self, chunk_id: str, content: str) -> None: ...
    def write_failure(self, chunk_id: str, content: str) -> None: ...

    # -- Final output --
    def write_final(self, content: str) -> None: ...

    # -- Version control --
    def commit_all(self, message: str) -> None: ...
