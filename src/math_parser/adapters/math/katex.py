"""KaTeX validator implemented by a small, deterministic Node worker."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess

from math_parser.ports.math_validation import (
    MathCorrection,
    MathDiagnostic,
    MathValidationResult,
)


class KaTeXMathValidator:
    """Validate Markdown math without exposing agent text to a shell."""

    def __init__(
        self,
        node_binary: str = "node",
        worker_path: str | os.PathLike[str] | None = None,
        timeout: int = 30,
    ) -> None:
        self._node_binary = node_binary
        self._worker_path = Path(
            worker_path or Path(__file__).with_name("katex_worker.mjs")
        )
        self._timeout = timeout

    def validate(self, markdown: str) -> MathValidationResult:
        try:
            completed = subprocess.run(
                [self._node_binary, str(self._worker_path)],
                input=json.dumps({"markdown": markdown}, ensure_ascii=False),
                capture_output=True,
                text=True,
                timeout=self._timeout,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError(f"Could not run KaTeX validation: {exc}") from exc

        if completed.returncode != 0:
            detail = completed.stderr.strip().splitlines()
            suffix = f": {detail[-1]}" if detail else ""
            raise RuntimeError(f"KaTeX validation worker failed{suffix}")

        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError("KaTeX validation worker returned invalid JSON") from exc

        def diagnostic(item: dict[str, object]) -> MathDiagnostic:
            return MathDiagnostic(
                line=int(str(item["line"])),
                column=int(str(item["column"])),
                code=str(item["code"]),
                message=str(item["message"]),
            )

        return MathValidationResult(
            normalized_text=str(payload["normalizedText"]),
            expressions_checked=int(payload.get("expressionsChecked", 0)),
            corrections=[
                MathCorrection(
                    line=int(str(item["line"])),
                    column=int(str(item["column"])),
                    code=str(item["code"]),
                    command=str(item["command"]),
                )
                for item in payload.get("corrections", [])
            ],
            warnings=[diagnostic(item) for item in payload.get("warnings", [])],
            errors=[diagnostic(item) for item in payload.get("errors", [])],
        )
