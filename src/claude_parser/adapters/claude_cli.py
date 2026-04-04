import logging
import os
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
        mcp_config_path: str | None = None,
    ) -> LLMResult:
        cmd = [
            "claude", "-p", prompt,
            "--model", model,
            "--verbose",
            "--output-format", "stream-json",
        ]

        if mcp_config_path:
            # MCP mode: disable all built-in tools, use only our MCP server.
            # --system-prompt overrides the default system prompt so Claude
            # won't try to read project memory or CLAUDE.md.
            # --tools "" disables all built-in tools (Read, Write, Bash).
            # --strict-mcp-config ensures only our MCP server is loaded.
            # --allowedTools pre-approves our MCP tools (no permission prompts in -p mode).
            cmd.extend([
                "--system-prompt", "You are a task agent. Use only the MCP tools provided.",
                "--tools", "",
                "--mcp-config", mcp_config_path,
                "--strict-mcp-config",
                "--allowedTools",
                "mcp__batch_tools__read_batch,"
                "mcp__batch_tools__submit_clean,"
                "mcp__batch_tools__submit_result",
            ])
        else:
            # Legacy mode: use built-in tools directly
            if allowed_tools:
                cmd.extend(["--allowedTools", ",".join(allowed_tools)])
            for d in add_dirs:
                cmd.extend(["--add-dir", d])

        logger.debug("Invoking claude with model=%s, timeout=%d", model, timeout)

        # Raise MCP output token limit so large read_batch results are not
        # persisted to disk and replaced with a 2KB preview. Default is 25000.
        env = os.environ.copy()
        env["MAX_MCP_OUTPUT_TOKENS"] = "200000"

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
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
