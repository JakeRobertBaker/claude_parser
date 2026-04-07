"""Utilities for rendering tree previews for MCP responses."""

from __future__ import annotations

from claude_parser.domain.annotation_tree_builder import (
    INTERNAL_ROOT_ID,
    active_trace_ids,
    visible_roots,
)
from claude_parser.domain.node import Node, NodeType, TreeDict


def _node_label(node: Node) -> str:
    label = node.id
    details: list[str] = []
    if node.node_type != NodeType.GENERIC:
        if node.node_type == NodeType.PRF and node._proves_id:
            details.append(f"proof -> {node._proves_id}")
        else:
            details.append(node.node_type.value)
    if node._dependency_ids:
        deps = ", ".join(node._dependency_ids)
        details.append(f"deps: {deps}")
    if details:
        label += f" [{'; '.join(details)}]"
    return label


def _render_tree_lines(roots: list[Node]) -> list[tuple[str, str]]:
    lines: list[tuple[str, str]] = []

    def walk(node: Node, prefix: str, is_last: bool, plain: bool = False) -> None:
        if plain:
            lines.append((node.id, _node_label(node)))
        else:
            connector = "└── " if is_last else "├── "
            lines.append((node.id, f"{prefix}{connector}{_node_label(node)}"))

        child_prefix = prefix + ("    " if is_last else "│   ")
        for idx, child in enumerate(node.children):
            walk(child, child_prefix, idx == len(node.children) - 1)

    if len(roots) == 1:
        walk(roots[0], "", True, plain=True)
        return lines

    for idx, root in enumerate(roots):
        walk(root, "", idx == len(roots) - 1)
    return lines


def tree_preview(tree_dict: TreeDict, cap_non_trace: int = 100) -> str:
    roots = visible_roots(tree_dict)
    if not roots:
        return ""

    all_lines = _render_tree_lines(roots)
    trace_set = set(active_trace_ids(tree_dict))
    trace_set.discard(INTERNAL_ROOT_ID)

    preview_lines: list[str] = []
    non_trace_kept = 0
    for node_id, line in all_lines:
        if node_id in trace_set:
            preview_lines.append(line)
            continue
        if non_trace_kept < cap_non_trace:
            preview_lines.append(line)
            non_trace_kept += 1
    return "\n".join(preview_lines)
