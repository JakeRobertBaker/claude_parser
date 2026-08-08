"""Port for normalizing and validating rendered mathematics."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(slots=True)
class MathCorrection:
    line: int
    column: int
    code: str
    command: str


@dataclass(slots=True)
class MathDiagnostic:
    line: int
    column: int
    code: str
    message: str


@dataclass(slots=True)
class MathValidationResult:
    normalized_text: str
    expressions_checked: int = 0
    corrections: list[MathCorrection] = field(default_factory=list)
    warnings: list[MathDiagnostic] = field(default_factory=list)
    errors: list[MathDiagnostic] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return not self.errors


class MathValidationPort(Protocol):
    """Normalize safe, mechanical TeX defects and validate KaTeX syntax."""

    def validate(self, markdown: str) -> MathValidationResult: ...
