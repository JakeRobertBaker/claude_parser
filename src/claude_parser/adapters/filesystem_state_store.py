import json
import logging
import os

from claude_parser.application.pipeline_state import PipelineState
from claude_parser.application.serialization import tree_from_dict, tree_to_dict
from claude_parser.domain.node import Node, TreeDict

logger = logging.getLogger(__name__)


class FilesystemStateStore:
    """Implements StatePort via filesystem. Stores state.json and tree.json."""

    def __init__(self, state_dir: str):
        self.state_dir = os.path.abspath(state_dir)

    @property
    def state_path(self) -> str:
        return os.path.join(self.state_dir, "state.json")

    @property
    def tree_path(self) -> str:
        return os.path.join(self.state_dir, "tree.json")

    def init(self) -> None:
        os.makedirs(self.state_dir, exist_ok=True)
        logger.info("Initialized state directory: %s", self.state_dir)

    # -- PipelineState --

    def load_state(self) -> PipelineState | None:
        if not os.path.exists(self.state_path):
            return None
        data = self._read_json(self.state_path)
        return PipelineState(
            next_start_line=data["next_start_line"],
            next_chunk_id=data["next_chunk_id"],
            open_stack=data.get("open_stack", []),
            pending_edges=data.get("pending_edges", {}),
            last_closed_node_id=data.get("last_closed_node_id"),
        )

    def save_state(self, state: PipelineState) -> None:
        data = {
            "next_start_line": state.next_start_line,
            "next_chunk_id": state.next_chunk_id,
            "open_stack": state.open_stack,
            "pending_edges": state.pending_edges,
            "last_closed_node_id": state.last_closed_node_id,
        }
        self._write_json(self.state_path, data)
        logger.debug("Saved pipeline state to %s", self.state_path)

    # -- Tree --

    def load_tree(self) -> tuple[Node, TreeDict] | None:
        if not os.path.exists(self.tree_path):
            return None
        data = self._read_json(self.tree_path)
        return tree_from_dict(data)

    def save_tree(self, root: Node) -> None:
        data = tree_to_dict(root)
        self._write_json(self.tree_path, data)
        logger.debug("Saved tree to %s", self.tree_path)

    def tree_exists(self) -> bool:
        return os.path.exists(self.tree_path)

    # -- Helpers --

    def _read_json(self, path: str) -> dict:
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def _write_json(self, path: str, data: dict) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
