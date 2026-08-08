"""Structured, topology-aware tree views for batch tools."""

from __future__ import annotations

from typing import Any

from claude_parser.domain.annotation_parser import AnnotationEvent
from claude_parser.domain.annotation_tree_builder import (
    INTERNAL_ROOT_ID,
    active_trace_nodes,
    visible_roots,
)
from claude_parser.domain.node import Node, NodeType, TreeDict

_SIBLING_WINDOW_SIZE = 5
_INSPECT_CHILD_LIMIT_MAX = 100


def _depth(node: Node) -> int:
    depth = 0
    cursor = node
    while cursor.parent is not None:
        if cursor.id != INTERNAL_ROOT_ID:
            depth += 1
        cursor = cursor.parent
    return depth


def _summary(node: Node) -> dict[str, Any]:
    return {
        "id": node.id,
        "title": node.title,
        "node_type": node.node_type.value,
        "depth": _depth(node),
        "parent_id": (
            node.parent.id
            if node.parent is not None and node.parent.id != INTERNAL_ROOT_ID
            else None
        ),
        "child_count": len(node.children),
        "proves_id": node._proves_id,
        "dependency_ids": list(node._dependency_ids),
    }


def _walk(nodes: list[Node]) -> list[Node]:
    result: list[Node] = []

    def visit(node: Node) -> None:
        result.append(node)
        for child in node.children:
            visit(child)

    for node in nodes:
        visit(node)
    return result


def _active_nodes(tree_dict: TreeDict) -> list[Node]:
    return [
        node for node in active_trace_nodes(tree_dict) if node.id != INTERNAL_ROOT_ID
    ]


def tree_context(tree_dict: TreeDict) -> dict[str, Any]:
    """Describe the whole-document skeleton and the exact append neighborhood."""
    roots = visible_roots(tree_dict)
    all_nodes = _walk(roots)
    active = _active_nodes(tree_dict)
    outline = [
        _summary(node)
        for node in all_nodes
        if node.node_type == NodeType.GENERIC and _depth(node) <= 2
    ]

    neighborhoods: list[dict[str, Any]] = []
    for node in active:
        if node.parent is None or node.parent.id == INTERNAL_ROOT_ID:
            siblings = roots
            parent_id = None
        else:
            siblings = node.parent.children
            parent_id = node.parent.id
        start = max(0, len(siblings) - _SIBLING_WINDOW_SIZE)
        neighborhoods.append(
            {
                "parent_id": parent_id,
                "total_children": len(siblings),
                "omitted_before": start,
                "children": [_summary(child) for child in siblings[start:]],
            }
        )

    return {
        "node_count": len(all_nodes),
        "major_outline": outline,
        "active_trace": [_summary(node) for node in active],
        "append_neighborhoods": neighborhoods,
    }


def inspect_tree(
    tree_dict: TreeDict,
    node_id: str,
    *,
    child_offset: int = 0,
    child_limit: int = 50,
) -> dict[str, Any]:
    if child_offset < 0:
        raise ValueError("child_offset must be non-negative.")
    if child_limit < 1 or child_limit > _INSPECT_CHILD_LIMIT_MAX:
        raise ValueError(
            f"child_limit must be between 1 and {_INSPECT_CHILD_LIMIT_MAX}."
        )
    try:
        node = tree_dict[node_id]
    except KeyError as exc:
        raise ValueError(f"Unknown tree node: {node_id!r}.") from exc
    if node.id == INTERNAL_ROOT_ID:
        raise ValueError("The internal document root cannot be inspected.")

    ancestors: list[Node] = []
    cursor = node.parent
    while cursor is not None and cursor.id != INTERNAL_ROOT_ID:
        ancestors.append(cursor)
        cursor = cursor.parent
    ancestors.reverse()
    children = node.children[child_offset : child_offset + child_limit]
    next_offset = child_offset + len(children)
    return {
        "node": _summary(node),
        "ancestors": [_summary(ancestor) for ancestor in ancestors],
        "children": [_summary(child) for child in children],
        "child_offset": child_offset,
        "child_limit": child_limit,
        "total_children": len(node.children),
        "next_child_offset": next_offset if next_offset < len(node.children) else None,
    }


def proposed_tree(
    before: TreeDict,
    after: TreeDict,
    events: list[AnnotationEvent],
) -> dict[str, Any]:
    batch_nodes: list[dict[str, Any]] = []
    for event in events:
        if event.event_type != "header":
            continue
        node = after[event.id]
        item = _summary(node)
        item.update(
            {
                "line": event.line_number,
                "annotation_depth": event.depth,
                "resolved_depth": item.pop("depth"),
            }
        )
        batch_nodes.append(item)
    return {
        "attachment_trace_before": [
            _summary(node) for node in _active_nodes(before)
        ],
        "batch_nodes": batch_nodes,
        "active_trace_after": [_summary(node) for node in _active_nodes(after)],
    }
