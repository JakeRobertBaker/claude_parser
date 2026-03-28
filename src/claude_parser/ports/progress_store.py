from __future__ import annotations
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from claude_parser.application.progress import ProgressState


class ProgressStorePort(Protocol):
    def load(self) -> ProgressState | None: ...
    def save(self, state: ProgressState) -> None: ...
