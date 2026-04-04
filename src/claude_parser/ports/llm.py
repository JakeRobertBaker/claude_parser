from dataclasses import dataclass
from typing import Protocol


@dataclass
class LLMResult:
    stdout: str
    success: bool
    stderr: str = ""


class LLMPort(Protocol):
    def invoke(
        self,
        prompt: str,
        model: str,
        allowed_tools: list[str],
        add_dirs: list[str],
        timeout: int,
        mcp_config_path: str | None = None,
    ) -> LLMResult: ...
