import json
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
            "--allowedTools", ",".join(allowed_tools),
        ]
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


def extract_json_from_stream(stream_output: str) -> dict | None:
    """Extract the metadata JSON from claude's stream-json output.

    Looks for the last assistant result message in the stream,
    then parses the JSON from its content.
    """
    last_result_text = None

    for line in stream_output.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue

        # stream-json emits {"type": "result", "result": "..."} at the end
        if event.get("type") == "result":
            last_result_text = event.get("result", "")
        # Also check for assistant messages with text content
        elif event.get("type") == "assistant" and "message" in event:
            for block in event["message"].get("content", []):
                if block.get("type") == "text":
                    last_result_text = block["text"]

    if last_result_text is None:
        logger.error("No result found in stream output")
        return None

    return _parse_json_text(last_result_text)


def _parse_json_text(text: str) -> dict | None:
    """Parse JSON from text that may contain markdown fences."""
    text = text.strip()

    # Try direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try extracting from markdown code fence
    if "```" in text:
        parts = text.split("```")
        for part in parts:
            candidate = part.strip()
            if candidate.startswith("json"):
                candidate = candidate[4:].strip()
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                continue

    logger.error("Could not parse JSON from response")
    return None
