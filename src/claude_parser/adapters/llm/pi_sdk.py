"""LLM adapter backed by a deliberately restricted Pi SDK agent."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import subprocess
import tempfile

from claude_parser.ports.llm import LLMResult

logger = logging.getLogger(__name__)


class PiSDKAdapter:
    """Run Pi's JavaScript SDK with only the batch workflow tools enabled."""

    def __init__(
        self,
        node_binary: str = "node",
        runner_path: str | os.PathLike[str] | None = None,
        log_root: str | os.PathLike[str] | None = None,
        debug_stream_log: bool = False,
    ) -> None:
        self._node_binary = node_binary
        self._runner_path = Path(runner_path or Path(__file__).with_name("pi_runner.mjs"))
        self._log_root = Path(log_root).resolve() if log_root is not None else None
        self._debug_stream_log = debug_stream_log

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
    ) -> LLMResult:
        # Pi receives no filesystem or shell tools. These legacy Claude options are
        # intentionally ignored; the only capabilities come from tool_endpoint.
        _ = (allowed_tools, add_dirs, mcp_config_path)
        if tool_endpoint is None:
            return LLMResult(
                stdout="",
                success=False,
                stderr="Pi SDK adapter requires a batch tool endpoint.",
            )
        if self._log_root is None:
            return LLMResult(
                stdout="",
                success=False,
                stderr="Pi SDK adapter requires a persistent log root.",
            )

        config = {
            "cwd": os.getcwd(),
            "model": model,
            "prompt": prompt,
            "toolEndpoint": tool_endpoint,
            "invocationId": invocation_id,
            "logRoot": str(self._log_root),
            "debugStreamLog": self._debug_stream_log,
        }

        logger.debug("Invoking Pi SDK with model=%s, timeout=%d", model, timeout)
        manifest = self._log_root / invocation_id / "current.json"

        def failure_report(error: str) -> str:
            payload = {
                "success": False,
                "invocationId": invocation_id,
                "error": error,
                "artifacts": {"currentManifest": str(manifest)},
            }
            return json.dumps(payload, ensure_ascii=False) + "\n"

        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", suffix=".json"
            ) as config_file:
                json.dump(config, config_file, ensure_ascii=False)
                config_file.flush()
                result = subprocess.run(
                    [
                        self._node_binary,
                        str(self._runner_path),
                        config_file.name,
                    ],
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                )
        except subprocess.TimeoutExpired:
            logger.error("Pi SDK agent timed out after %ds", timeout)
            return LLMResult(
                stdout=failure_report(f"Pi SDK agent timed out after {timeout}s"),
                success=False,
                stderr="timeout",
            )
        except OSError as exc:
            logger.error("Could not start Pi SDK agent: %s", exc)
            return LLMResult(
                stdout=failure_report(str(exc)), success=False, stderr=str(exc)
            )

        if result.returncode != 0:
            logger.error(
                "Pi SDK agent exited with code %d: %s",
                result.returncode,
                result.stderr[:500],
            )
            return LLMResult(
                stdout=result.stdout or failure_report(result.stderr or "runner failed"),
                success=False,
                stderr=result.stderr,
            )

        return LLMResult(
            stdout=result.stdout,
            success=True,
            stderr=result.stderr,
        )
