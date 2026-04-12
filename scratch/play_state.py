from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path

from claude_parser.application.serialization import tree_from_dict
from claude_parser.domain.annotation_tree_builder import visible_roots
from claude_parser.domain.content import Content
from claude_parser.domain.node import Node

_CLEAN_FILE_RE = re.compile(r"^clean_(\d+)\.md$")


def _load_tree(state_dir: Path):
    tree_path = state_dir / "tree.json"
    if not tree_path.exists():
        raise FileNotFoundError(f"Missing tree file: {tree_path}")

    with tree_path.open(encoding="utf-8") as f:
        tree_data = json.load(f)

    return tree_from_dict(tree_data)


def _load_clean_chunks(state_dir: Path) -> dict[int, list[str]]:
    clean_dir = state_dir / "clean"
    if not clean_dir.exists():
        raise FileNotFoundError(f"Missing clean directory: {clean_dir}")

    clean_files: list[tuple[int, Path]] = []
    for path in clean_dir.iterdir():
        if not path.is_file():
            continue
        match = _CLEAN_FILE_RE.match(path.name)
        if not match:
            continue
        clean_files.append((int(match.group(1)), path))

    chunks: dict[int, list[str]] = {}
    for ordinal, path in sorted(clean_files, key=lambda item: item[0]):
        lines = path.read_text(encoding="utf-8").splitlines()
        cutoff_idx = len(lines)
        for i, line in enumerate(lines):
            if "<!-- cutoff -->" in line:
                cutoff_idx = i
                break
        chunks[ordinal] = lines[:cutoff_idx]

    return chunks


def _render_span(content: Content, chunks: dict[int, list[str]]) -> str:
    lines = chunks.get(content.chunk_number)
    if lines is None:
        return (
            f"[missing clean_{content.chunk_number}.md for span "
            f"{content.first_line}-{content.last_line}]"
        )

    if content.first_line < 1 or content.last_line < content.first_line:
        return (
            f"[invalid span {content.first_line}-{content.last_line} "
            f"for chunk {content.chunk_number}]"
        )

    start = content.first_line - 1
    if start >= len(lines):
        return (
            f"[span starts past chunk end: {content.first_line}-{content.last_line} "
            f"for chunk {content.chunk_number}, chunk lines={len(lines)}]"
        )

    end = min(content.last_line, len(lines))
    return "\n".join(lines[start:end])


def _render_node(node: Node, depth: int, chunks: dict[int, list[str]]) -> list[str]:
    output = [f"{'#' * depth} {node.title} [{node.id}]", ""]

    content_parts = sorted(
        (content for content in node.content_list if isinstance(content, Content)),
        key=lambda content: (
            content.chunk_number,
            content.first_line,
            content.last_line,
        ),
    )

    for i, content in enumerate(content_parts):
        output.append(_render_span(content, chunks))
        if i < len(content_parts) - 1:
            output.append("")

    if content_parts:
        output.append("")

    for child in node.children:
        output.extend(_render_node(child, depth + 1, chunks))

    return output


def render_state_markdown(state_dir: Path) -> str:
    _, tree_dict = _load_tree(state_dir)
    chunks = _load_clean_chunks(state_dir)
    roots = visible_roots(tree_dict)

    lines: list[str] = []
    for root in roots:
        lines.extend(_render_node(root, depth=1, chunks=chunks))

    return "\n".join(lines).rstrip() + "\n"


def _normalize_path(path: Path) -> Path:
    expanded = os.path.expandvars(str(path))
    return Path(expanded).expanduser().resolve()


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Render a parser state directory to markdown headings based on Node depth."
        )
    )
    parser.add_argument(
        "--state-dir",
        type=Path,
        required=True,
        help="Path to state directory containing tree.json and clean/",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Optional output markdown path (defaults to stdout)",
    )
    args = parser.parse_args()

    state_dir = _normalize_path(args.state_dir)
    out_path = _normalize_path(args.out) if args.out is not None else None

    rendered = render_state_markdown(state_dir)
    if out_path is None:
        print(rendered, end="")
        return

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(rendered, encoding="utf-8")


if __name__ == "__main__":
    main()
