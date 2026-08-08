"""Protocol describing the minimal interface for LLM adapters."""

from dataclasses import dataclass
from typing import Protocol


@dataclass
class LLMResult:
    """Normalized response from an LLM invocation."""

    stdout: str
    success: bool
    stderr: str = ""


class LLMPort(Protocol):
    """Capability abstraction for invoking an LLM task agent."""

    def invoke(
        self,
        prompt: str,
        model: str | None,
        allowed_tools: list[str],
        add_dirs: list[str],
        timeout: int,
        invocation_id: str,
        mcp_config_path: str | None = None,
        tool_endpoint: str | None = None,
    ) -> LLMResult: ...
