"""StatePort implementation using filesystem storage.

Stores state.json, tree.json, raw/clean batch files, and logs on disk.
Version control (git) is handled internally.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess

from claude_parser.application.run_engine import RunSnapshot
from claude_parser.application.serialization import tree_from_dict, tree_to_dict
from claude_parser.domain.annotation_tree_builder import (
    INTERNAL_ROOT_ID,
    ensure_internal_root,
)
from claude_parser.domain.node import Node, TreeDict

logger = logging.getLogger(__name__)
_CLEAN_FILE_RE = re.compile(r"^clean_(\d+)\.md$")


class FilesystemStateStore:
    """Implements StatePort via filesystem."""

    def __init__(self, state_dir: str, raw_path: str, resume: bool = False):
        self.state_dir = os.path.abspath(state_dir)
        self._raw_path = raw_path
        self._resume = resume

        self._snapshot: RunSnapshot = RunSnapshot()
        self._raw_lines: list[str] = []
        self._tree_dict: TreeDict = TreeDict()
        self._root: Node | None = None

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

        self._root = ensure_internal_root(self._tree_dict)
        logger.info("Initialized state directory: %s", self.state_dir)

    def _load_saved_state(self) -> None:
        if not os.path.exists(self._state_path):
            return
        data = self._read_json(self._state_path)
        self._snapshot = RunSnapshot(
            next_start_line=data["next_start_line"],
            next_chunk_id=data["next_chunk_id"],
            sections_completed=data.get("sections_completed", 0),
        )

    def _load_saved_tree(self) -> None:
        if not os.path.exists(self._tree_path):
            return
        data = self._read_json(self._tree_path)
        root, tree_dict = tree_from_dict(data)
        self._root = root
        self._tree_dict = tree_dict
        self._root = ensure_internal_root(self._tree_dict)

    # -- Run state --

    @property
    def raw_lines(self) -> list[str]:
        return self._raw_lines

    @property
    def snapshot(self) -> RunSnapshot:
        return self._snapshot

    def save_snapshot(self, snapshot: RunSnapshot) -> None:
        self._snapshot = snapshot
        self._save_state()

    @property
    def known_ids(self) -> list[str]:
        return [
            node_id
            for node_id in self._tree_dict._data.keys()
            if node_id != INTERNAL_ROOT_ID
        ]

    @property
    def tree_dict(self) -> TreeDict:
        return self._tree_dict

    def save_tree(self) -> None:
        if self._tree_dict.root_node is None:
            return
        self._root = self._tree_dict.root_node
        self._save_tree()

    # -- Context helpers --

    def read_prior_clean_tail(self, ordinal: int, n_lines: int) -> str:
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

    def read_memory(self) -> str:
        if not os.path.exists(self._memory_path):
            return ""
        with open(self._memory_path, encoding="utf-8") as f:
            return f.read()

    # -- Batch artifacts --

    def write_raw_batch(self, ordinal: int, content: str) -> None:
        path = os.path.join(self._raw_dir, f"raw_{ordinal}.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

    def clean_batch_exists(self, ordinal: int) -> bool:
        return os.path.exists(self._clean_path(ordinal))

    def read_clean_batch(self, ordinal: int) -> str | None:
        path = self._clean_path(ordinal)
        if not os.path.exists(path):
            return None
        with open(path, encoding="utf-8") as f:
            return f.read()

    def write_clean_batch(self, ordinal: int, content: str) -> None:
        path = self._clean_path(ordinal)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

    def read_all_clean_before_cutoff(self) -> str:
        clean_files = sorted(
            (f for f in os.listdir(self._clean_dir) if f.endswith(".md")),
            key=self._clean_file_sort_key,
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

    def _clean_file_sort_key(self, filename: str) -> tuple[int, int | str]:
        match = _CLEAN_FILE_RE.match(filename)
        if match:
            return (0, int(match.group(1)))
        return (1, filename)

    def _clean_path(self, ordinal: int) -> str:
        return os.path.join(self._clean_dir, f"clean_{ordinal}.md")

    # -- Logging --

    def write_log(self, chunk_id: str, content: str) -> None:
        path = os.path.join(self._logs_dir, f"{chunk_id}.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

    def write_failure(self, chunk_id: str, content: str) -> None:
        path = os.path.join(self._failures_dir, f"{chunk_id}_raw_response.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

    # -- State persistence (internal) --

    def _save_state(self) -> None:
        data = {
            "next_start_line": self._snapshot.next_start_line,
            "next_chunk_id": self._snapshot.next_chunk_id,
            "sections_completed": self._snapshot.sections_completed,
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
            cmd,
            cwd=self.state_dir,
            capture_output=True,
            text=True,
            check=check,
        )

    # -- JSON helpers --

    def _read_json(self, path: str) -> dict:
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def _write_json(self, path: str, data: dict) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
