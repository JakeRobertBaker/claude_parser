"""Protocol for MCP transport adapters (SSE, stdio, etc.)."""

from typing import Protocol


class BatchToolsPort(Protocol):
    """Transport lifecycle around BatchToolsService."""

    def prepare(self) -> None: ...

    def succeeded(self) -> bool: ...

    @property
    def mcp_config_path(self) -> str: ...

    def start(self) -> None: ...

    def stop(self) -> None: ...
