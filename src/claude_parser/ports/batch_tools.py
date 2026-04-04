from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from claude_parser.domain.batch_types import BatchResult


class BatchToolsPort(Protocol):
    def setup_batch(
        self,
        batch_num: int,
        raw_content: str,
        chunk_id: str,
        raw_start: int,
        raw_end: int,
        open_stack: list[str],
        context_text: str,
        known_ids: list[str],
        memory_text: str,
        min_clean_lines: int,
    ) -> None: ...

    def get_result(self) -> BatchResult | None: ...

    @property
    def mcp_config_path(self) -> str: ...

    def start(self) -> None: ...

    def stop(self) -> None: ...
