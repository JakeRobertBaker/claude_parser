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

    @property
    def _clean_dir(self) -> str:
        return os.path.join(self.state_dir, "clean")

    @property
    def _raw_dir(self) -> str:
        return os.path.join(self.state_dir, "raw")

    @property
    def _logs_dir(self) -> str:
        return os.path.join(self.state_dir, "logs")

    @property
    def _failures_dir(self) -> str:
        return os.path.join(self.state_dir, "failures")

    @property
    def _memory_path(self) -> str:
        return os.path.join(self.state_dir, "memory.md")

    @property
    def _final_path(self) -> str:
        return os.path.join(self.state_dir, "final.md")

    def init(self) -> None:
        os.makedirs(self.state_dir, exist_ok=True)
        logger.info("Initialized state directory: %s", self.state_dir)

    # -- Directory setup --

    def init_dirs(self) -> None:
        for d in [self._clean_dir, self._raw_dir, self._logs_dir, self._failures_dir]:
            os.makedirs(d, exist_ok=True)

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

    # -- Raw batches --

    def write_raw_batch(self, batch_num: int, content: str) -> None:
        path = os.path.join(self._raw_dir, f"raw_{batch_num}.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

    def resolve_raw_path(self, batch_num: int) -> str:
        return os.path.join(self._raw_dir, f"raw_{batch_num}.md")

    # -- Clean batches --

    def resolve_clean_path(self, batch_num: int) -> str:
        return os.path.join(self._clean_dir, f"clean_{batch_num}.md")

    def clean_batch_exists(self, batch_num: int) -> bool:
        return os.path.exists(self.resolve_clean_path(batch_num))

    def read_clean_batch(self, batch_num: int) -> str | None:
        path = self.resolve_clean_path(batch_num)
        if not os.path.exists(path):
            return None
        with open(path, encoding="utf-8") as f:
            return f.read()

    def read_all_clean_before_cutoff(self) -> str:
        clean_files = sorted(
            f for f in os.listdir(self._clean_dir) if f.endswith(".md")
        )
        parts: list[str] = []
        for clean_file in clean_files:
            path = os.path.join(self._clean_dir, clean_file)
            with open(path, encoding="utf-8") as f:
                for line in f:
                    if "<!-- cutoff -->" in line:
                        break
                    parts.append(line)
        return "".join(parts)

    # -- Logs and failures --

    def write_log(self, chunk_id: str, content: str) -> None:
        path = os.path.join(self._logs_dir, f"{chunk_id}.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

    def write_failure(self, chunk_id: str, content: str) -> None:
        path = os.path.join(self._failures_dir, f"{chunk_id}_raw_response.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        logger.debug("Saved failure log to %s", path)

    # -- Memory --

    def read_memory(self) -> str:
        if not os.path.exists(self._memory_path):
            return ""
        with open(self._memory_path, encoding="utf-8") as f:
            return f.read()

    # -- Context --

    def get_context_lines(self, batch_num: int, n_lines: int) -> str:
        if batch_num == 0:
            return ""
        prev_path = self.resolve_clean_path(batch_num - 1)
        if not os.path.exists(prev_path):
            return ""
        with open(prev_path, encoding="utf-8") as f:
            lines = f.readlines()
        cutoff_idx = len(lines)
        for i, line in enumerate(lines):
            if "<!-- cutoff -->" in line:
                cutoff_idx = i
                break
        context_start = max(0, cutoff_idx - n_lines)
        return "".join(lines[context_start:cutoff_idx])

    # -- Final output --

    def write_final(self, content: str) -> None:
        with open(self._final_path, "w", encoding="utf-8") as f:
            f.write(content)
        logger.info("Wrote final output to %s", self._final_path)

    # -- Helpers --

    def _read_json(self, path: str) -> dict:
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def _write_json(self, path: str, data: dict) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
