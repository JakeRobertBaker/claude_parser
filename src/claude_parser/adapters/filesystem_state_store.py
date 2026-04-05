"""StatePort implementation using filesystem storage.

Stores state.json, tree.json, raw/clean batch files, and logs on disk.
Version control (git) is handled internally.
"""

import json
import logging
import os
import subprocess

from claude_parser.application.serialization import tree_from_dict, tree_to_dict
from claude_parser.application.tokens import approximate_claude_tokens
from claude_parser.domain.annotation_tree_builder import FragmentResult
from claude_parser.domain.node import Node, TreeDict

logger = logging.getLogger(__name__)


class FilesystemStateStore:
    """Implements StatePort via filesystem."""

    def __init__(self, state_dir: str, raw_path: str, resume: bool = False):
        self.state_dir = os.path.abspath(state_dir)
        self._raw_path = raw_path
        self._resume = resume

        # Internal progression state
        self._raw_lines: list[str] = []
        self._next_start_line: int = 0
        self._next_chunk_id: int = 0
        self._sections_completed: int = 0
        self._open_stack: list[str] = []
        self._pending_edges: dict[str, list[str]] = {}
        self._last_closed_node_id: str | None = None
        self._tree_dict: TreeDict = TreeDict()
        self._root: Node | None = None

        # Current batch state (set by prepare_next, consumed by MCP server + service)
        self._current_id: str = ""
        self._current_ordinal: int = 0
        self._current_raw_content: str = ""
        self._current_raw_start: int = 0
        self._current_raw_end: int = 0
        self._current_raw_line_count: int = 0
        self._current_prior_clean_tail: str = ""
        self._current_memory_text: str = ""
        self._current_min_tokens: int = 0
        self._current_cutoff: int | None = None  # set by MCP server via set_cutoff

    # -- Directory paths --

    @property
    def _state_path(self) -> str:
        return os.path.join(self.state_dir, "state.json")

    @property
    def _tree_path(self) -> str:
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

    # -- Lifecycle --

    def init(self) -> None:
        os.makedirs(self.state_dir, exist_ok=True)
        for d in [self._clean_dir, self._raw_dir, self._logs_dir, self._failures_dir]:
            os.makedirs(d, exist_ok=True)

        with open(self._raw_path, encoding="utf-8") as f:
            self._raw_lines = f.readlines()

        if self._resume:
            self._load_saved_state()
            self._load_saved_tree()

        logger.info("Initialized state directory: %s", self.state_dir)

    def _load_saved_state(self) -> None:
        if not os.path.exists(self._state_path):
            return
        data = self._read_json(self._state_path)
        self._next_start_line = data["next_start_line"]
        self._next_chunk_id = data["next_chunk_id"]
        self._sections_completed = data.get("sections_completed", 0)
        self._open_stack = data.get("open_stack", [])
        self._pending_edges = data.get("pending_edges", {})
        self._last_closed_node_id = data.get("last_closed_node_id")

    def _load_saved_tree(self) -> None:
        if not os.path.exists(self._tree_path):
            return
        data = self._read_json(self._tree_path)
        root, tree_dict = tree_from_dict(data)
        self._root = root
        self._tree_dict = tree_dict

    # -- Progression (StatePort) --

    @property
    def complete(self) -> bool:
        return self._next_start_line >= len(self._raw_lines)

    @property
    def sections_completed(self) -> int:
        return self._sections_completed

    # -- Current batch properties (StatePort) --

    @property
    def current_id(self) -> str:
        return self._current_id

    @property
    def current_ordinal(self) -> int:
        return self._current_ordinal

    @property
    def open_stack(self) -> list[str]:
        return list(self._open_stack)

    @property
    def known_ids(self) -> list[str]:
        return list(self._tree_dict._data.keys())

    @property
    def tree_dict(self) -> TreeDict:
        return self._tree_dict

    # -- Adapter-specific properties (for MCP server, NOT on protocol) --

    @property
    def current_raw_content(self) -> str:
        return self._current_raw_content

    @property
    def current_raw_start(self) -> int:
        return self._current_raw_start

    @property
    def current_raw_end(self) -> int:
        return self._current_raw_end

    @property
    def current_raw_line_count(self) -> int:
        return self._current_raw_line_count

    @property
    def current_prior_clean_tail(self) -> str:
        return self._current_prior_clean_tail

    @property
    def current_memory_text(self) -> str:
        return self._current_memory_text

    @property
    def current_min_tokens(self) -> int:
        return self._current_min_tokens

    @property
    def current_known_ids(self) -> list[str]:
        return list(self._tree_dict._data.keys())

    @property
    def is_final_batch(self) -> bool:
        """True if this batch covers the remainder of the source file."""
        return self._current_raw_end >= len(self._raw_lines)

    # -- Batch lifecycle --

    def prepare_next(self, batch_tokens: int, context_lines: int) -> None:
        start = self._next_start_line
        end = self._compute_batch_end(start, batch_tokens)
        ordinal = self._next_chunk_id
        chunk_id = f"chunk_{ordinal:03d}"

        raw_content = "".join(self._raw_lines[start:end])

        # Write raw batch file for reference
        path = os.path.join(self._raw_dir, f"raw_{ordinal}.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write(raw_content)

        # Store current batch state
        self._current_id = chunk_id
        self._current_ordinal = ordinal
        self._current_raw_content = raw_content
        self._current_raw_start = start
        self._current_raw_end = end
        self._current_raw_line_count = end - start
        self._current_prior_clean_tail = self._get_prior_clean_tail(ordinal, context_lines)
        self._current_memory_text = self._read_memory()
        self._current_min_tokens = int(approximate_claude_tokens(raw_content) * 0.5)
        self._current_cutoff = None

        logger.info("[%s] Processing raw lines %d–%d", chunk_id, start + 1, end)

    def set_cutoff(self, source_line: int) -> None:
        """Called by MCP server when Haiku submits a result. Not on protocol."""
        # Clamp to batch bounds
        self._current_cutoff = max(
            self._current_raw_start + 1,
            min(source_line, self._current_raw_end),
        )

    def advance(self, fragment: FragmentResult) -> None:
        assert self._current_cutoff is not None, "set_cutoff must be called before advance"

        self._next_start_line = self._current_cutoff
        self._next_chunk_id += 1
        self._sections_completed += 1
        self._open_stack = fragment.open_stack
        self._last_closed_node_id = fragment.last_closed_node_id

        if self._root is None and self._tree_dict.root_node is not None:
            self._root = self._tree_dict.root_node

        self._save_state()
        if self._root is not None:
            self._save_tree()
        self.commit_all(self._current_id)

    def _compute_batch_end(self, start: int, batch_tokens: int) -> int:
        tokens = 0
        for i in range(start, len(self._raw_lines)):
            tokens += approximate_claude_tokens(self._raw_lines[i])
            if tokens >= batch_tokens:
                return i + 1
        return len(self._raw_lines)

    # -- Clean batches (current batch) --

    def clean_batch_exists(self) -> bool:
        return os.path.exists(self._clean_path(self._current_ordinal))

    def read_clean_batch(self) -> str | None:
        path = self._clean_path(self._current_ordinal)
        if not os.path.exists(path):
            return None
        with open(path, encoding="utf-8") as f:
            return f.read()

    def write_clean_batch(self, content: str) -> None:
        path = self._clean_path(self._current_ordinal)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

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

    def _clean_path(self, ordinal: int) -> str:
        return os.path.join(self._clean_dir, f"clean_{ordinal}.md")

    # -- Logging (uses current_id) --

    def write_log(self, content: str) -> None:
        path = os.path.join(self._logs_dir, f"{self._current_id}.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

    def write_failure(self, content: str) -> None:
        path = os.path.join(self._failures_dir, f"{self._current_id}_raw_response.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

    # -- Context (internal) --

    def _get_prior_clean_tail(self, ordinal: int, n_lines: int) -> str:
        if ordinal == 0:
            return ""
        prev_path = self._clean_path(ordinal - 1)
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

    # -- Memory (internal) --

    def _read_memory(self) -> str:
        if not os.path.exists(self._memory_path):
            return ""
        with open(self._memory_path, encoding="utf-8") as f:
            return f.read()

    # -- State persistence (internal) --

    def _save_state(self) -> None:
        data = {
            "next_start_line": self._next_start_line,
            "next_chunk_id": self._next_chunk_id,
            "sections_completed": self._sections_completed,
            "open_stack": self._open_stack,
            "pending_edges": self._pending_edges,
            "last_closed_node_id": self._last_closed_node_id,
        }
        self._write_json(self._state_path, data)

    def _save_tree(self) -> None:
        assert self._root is not None
        data = tree_to_dict(self._root)
        self._write_json(self._tree_path, data)

    # -- Final output --

    def write_final(self, content: str) -> None:
        with open(self._final_path, "w", encoding="utf-8") as f:
            f.write(content)
        logger.info("Wrote final output to %s", self._final_path)

    # -- Version control --

    def init_repo(self) -> None:
        git_dir = os.path.join(self.state_dir, ".git")
        if os.path.isdir(git_dir):
            return
        self._git(["git", "init"])
        logger.info("Initialized git repo at %s", self.state_dir)

    def commit_all(self, message: str) -> None:
        self._git(["git", "add", "-A"])
        result = self._git(["git", "diff", "--cached", "--quiet"], check=False)
        if result.returncode == 0:
            return
        self._git(["git", "commit", "-m", message])

    def _git(
        self, cmd: list[str], check: bool = True
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            cmd, cwd=self.state_dir, capture_output=True, text=True, check=check,
        )

    # -- JSON helpers --

    def _read_json(self, path: str) -> dict:
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def _write_json(self, path: str, data: dict) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
