import json
import logging
import os

from claude_parser.adapters.chunk_lines.json_adapter import (
    tree_from_dict,
    tree_to_dict,
)
from claude_parser.application.progress import ProgressState
from claude_parser.domain.node import Node, TreeDict

logger = logging.getLogger(__name__)


class FilesystemStore:
    """Implements TreeRepositoryPort and ProgressStorePort via filesystem."""

    def __init__(self, state_dir: str):
        self.state_dir = os.path.abspath(state_dir)

    @property
    def tree_path(self) -> str:
        return os.path.join(self.state_dir, "tree.json")

    @property
    def progress_path(self) -> str:
        return os.path.join(self.state_dir, "progress.json")

    @property
    def chunks_dir(self) -> str:
        return os.path.join(self.state_dir, "chunks")

    @property
    def logs_dir(self) -> str:
        return os.path.join(self.state_dir, "logs")

    @property
    def failures_dir(self) -> str:
        return os.path.join(self.state_dir, "failures")

    def init(self) -> None:
        for d in [self.state_dir, self.chunks_dir, self.logs_dir, self.failures_dir]:
            os.makedirs(d, exist_ok=True)
        logger.info("Initialized state directory: %s", self.state_dir)

    # -- TreeRepositoryPort --

    def load(self) -> tuple[Node, TreeDict] | None:
        if not os.path.exists(self.tree_path):
            return None
        data = self._read_json(self.tree_path)
        return tree_from_dict(data)

    def save(self, root: Node) -> None:
        data = tree_to_dict(root)
        self._write_json(self.tree_path, data)
        logger.debug("Saved tree to %s", self.tree_path)

    def exists(self) -> bool:
        return os.path.exists(self.tree_path)

    # -- ProgressStorePort --

    def load_progress(self) -> ProgressState | None:
        if not os.path.exists(self.progress_path):
            return None
        data = self._read_json(self.progress_path)
        return ProgressState(
            next_start_line=data["next_start_line"],
            next_chunk_id=data["next_chunk_id"],
            section_index=data["section_index"],
        )

    def save_progress(self, state: ProgressState) -> None:
        data = {
            "next_start_line": state.next_start_line,
            "next_chunk_id": state.next_chunk_id,
            "section_index": state.section_index,
        }
        self._write_json(self.progress_path, data)
        logger.debug("Saved progress to %s", self.progress_path)

    # -- Helpers --

    def _read_json(self, path: str) -> dict:
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def _write_json(self, path: str, data: dict) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
