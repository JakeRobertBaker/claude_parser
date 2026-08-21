from __future__ import annotations

import json
from pathlib import Path
import subprocess
from typing import cast

from math_parser.adapters.llm.pi_sdk import PiSDKAdapter


def test_invoke_passes_structured_config_to_runner(
    monkeypatch, tmp_path: Path
) -> None:
    runner = tmp_path / "runner.mjs"
    runner.touch()
    captured: dict[str, object] = {}

    def fake_run(
        cmd: list[str],
        *,
        capture_output: bool,
        text: bool,
        timeout: int,
    ) -> subprocess.CompletedProcess[str]:
        captured["cmd"] = cmd
        captured["capture_output"] = capture_output
        captured["text"] = text
        captured["timeout"] = timeout
        with open(cmd[2], encoding="utf-8") as handle:
            captured["config"] = json.load(handle)
        return subprocess.CompletedProcess(cmd, 0, stdout='{"success":true}\n')

    monkeypatch.setattr(subprocess, "run", fake_run)

    log_root = tmp_path / "logs" / "pi"
    result = PiSDKAdapter(
        node_binary="node-test", runner_path=runner, log_root=log_root
    ).invoke(
        prompt="clean one batch",
        model="openrouter/anthropic/example:high",
        allowed_tools=["Bash"],
        add_dirs=["/should/not/be/exposed"],
        timeout=42,
        invocation_id="chunk_007",
        mcp_config_path="ignored.json",
        tool_endpoint="http://127.0.0.1:1234/batch-tools",
    )

    assert result.success is True
    assert result.stdout == '{"success":true}\n'
    assert cast(list[str], captured["cmd"])[:2] == ["node-test", str(runner)]
    assert captured["timeout"] == 42
    assert captured["config"] == {
        "cwd": str(Path.cwd()),
        "model": "openrouter/anthropic/example:high",
        "prompt": "clean one batch",
        "toolEndpoint": "http://127.0.0.1:1234/batch-tools",
        "invocationId": "chunk_007",
        "logRoot": str(log_root.resolve()),
        "debugStreamLog": False,
    }


def test_invoke_requires_tool_endpoint() -> None:
    result = PiSDKAdapter().invoke(
        prompt="prompt",
        model=None,
        allowed_tools=[],
        add_dirs=[],
        timeout=1,
        invocation_id="chunk_000",
    )

    assert result.success is False
    assert "requires a batch tool endpoint" in result.stderr


def test_invoke_normalizes_timeout(monkeypatch, tmp_path: Path) -> None:
    runner = tmp_path / "runner.mjs"
    runner.touch()

    def timeout_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(cmd="node", timeout=3)

    monkeypatch.setattr(subprocess, "run", timeout_run)

    result = PiSDKAdapter(runner_path=runner, log_root=tmp_path / "logs").invoke(
        prompt="prompt",
        model=None,
        allowed_tools=[],
        add_dirs=[],
        timeout=3,
        invocation_id="chunk_002",
        tool_endpoint="http://127.0.0.1:1234/batch-tools",
    )

    assert result.success is False
    assert result.stderr == "timeout"
    payload = json.loads(result.stdout)
    assert payload["artifacts"]["currentManifest"].endswith(
        "chunk_002/current.json"
    )
