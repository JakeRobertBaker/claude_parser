import logging
import subprocess

from claude_parser.ports.llm import LLMResult

logger = logging.getLogger(__name__)


class ClaudeCLIAdapter:
    """Implements LLMPort via the `claude` CLI tool."""

    def invoke(
        self,
        prompt: str,
        model: str,
        allowed_tools: list[str],
        add_dirs: list[str],
        timeout: int,
    ) -> LLMResult:
        cmd = [
            "claude", "-p", prompt,
            "--model", model,
            "--verbose",
            "--output-format", "stream-json",
        ]
        if allowed_tools:
            cmd.extend(["--allowedTools", ",".join(allowed_tools)])
        for d in add_dirs:
            cmd.extend(["--add-dir", d])

        logger.debug("Invoking claude with model=%s, timeout=%d", model, timeout)

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            logger.error("Claude timed out after %ds", timeout)
            return LLMResult(stdout="", success=False, stderr="timeout")

        if result.returncode != 0:
            logger.error(
                "Claude exited with code %d: %s",
                result.returncode,
                result.stderr[:200],
            )
            return LLMResult(
                stdout=result.stdout,
                success=False,
                stderr=result.stderr,
            )

        return LLMResult(
            stdout=result.stdout,
            success=True,
            stderr=result.stderr,
        )
