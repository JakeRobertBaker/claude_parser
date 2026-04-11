"""Protocol for MCP transport adapters (SSE, stdio, etc.)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from claude_parser.ports.state import BatchContext

if TYPE_CHECKING:
    from claude_parser.domain.node import TreeDict


class BatchToolsPort(Protocol):
    """Transport lifecycle around BatchToolsService."""

    def begin_batch(
        self,
        context: BatchContext,
        known_ids: list[str],
        tree_dict: TreeDict,
        current_ordinal: int,
    ) -> None: ...

    def succeeded(self) -> bool: ...

    def committed_source_line(self) -> int | None: ...

    @property
    def mcp_config_path(self) -> str: ...

    def start(self) -> None: ...

    def stop(self) -> None: ...
