"""Apply parsed annotation headers to the domain tree.

This module uses an internal, hidden depth-0 root. Visible headers begin at
depth 1 (`@ - ...`). The active trace is derived from the current tree
structure (rightmost path in document order).
"""

from __future__ import annotations

from dataclasses import dataclass

from claude_parser.domain.annotation_parser import AnnotationEvent
from claude_parser.domain.content import Content
from claude_parser.domain.node import Node, NodeType, TreeDict

INTERNAL_ROOT_ID = "__doc_root__"
INTERNAL_ROOT_TITLE = "Document Root"


@dataclass
class ApplyResult:
    added_nodes: int
    active_depth: int


def _node_type_from_value(value: str | None) -> NodeType:
    if value is None:
        return NodeType.GENERIC
    try:
        return NodeType(value)
    except ValueError:
        return NodeType.GENERIC


def ensure_internal_root(tree_dict: TreeDict) -> Node:
    """Ensure tree_dict has a hidden internal root at depth 0."""
    root = tree_dict.root_node
    if root is None:
        root = Node(
            id=INTERNAL_ROOT_ID,
            title=INTERNAL_ROOT_TITLE,
            children=[],
            content_list=[],
            node_type=NodeType.GENERIC,
            node_dict=tree_dict,
        )
        tree_dict.set_root(root)
        return root

    if root.id == INTERNAL_ROOT_ID:
        return root

    internal_root = Node(
        id=INTERNAL_ROOT_ID,
        title=INTERNAL_ROOT_TITLE,
        children=[],
        content_list=[],
        node_type=NodeType.GENERIC,
        node_dict=tree_dict,
    )
    tree_dict.root_node = internal_root
    internal_root.add_child(root)
    return internal_root


def visible_roots(tree_dict: TreeDict) -> list[Node]:
    root = tree_dict.root_node
    if root is None:
        return []
    if root.id == INTERNAL_ROOT_ID:
        return list(root.children)
    return [root]


def active_trace_nodes(tree_dict: TreeDict) -> list[Node]:
    """Return active trace from internal root to current active visible leaf."""
    root = ensure_internal_root(tree_dict)
    trace = [root]
    if not root.children:
        return trace

    node = root.children[-1]
    trace.append(node)
    while node.children:
        node = node.children[-1]
        trace.append(node)
    return trace


def active_trace_ids(tree_dict: TreeDict, include_internal: bool = False) -> list[str]:
    ids = [node.id for node in active_trace_nodes(tree_dict)]
    if include_internal:
        return ids
    return [node_id for node_id in ids if node_id != INTERNAL_ROOT_ID]


def has_visible_nodes(tree_dict: TreeDict) -> bool:
    return len(visible_roots(tree_dict)) > 0


def process_batch_annotations(
    events: list[AnnotationEvent],
    tree_dict: TreeDict,
    chunk_number: int,
    total_content_lines: int,
) -> ApplyResult:
    """Apply one batch of parsed annotations to tree_dict.

    Depth transitions are implicit. For each header of depth d:
    - pop active trace until visible depth < d
    - append new node under current trace leaf

    Deeper-than-expected jumps are allowed and interpreted as direct children of
    the current active node.
    """
    ensure_internal_root(tree_dict)
    trace = active_trace_nodes(tree_dict)
    last_annotation_line = 0
    hit_cutoff = False
    added_nodes = 0

    def _flush_content(up_to_line: int) -> None:
        nonlocal last_annotation_line
        first = last_annotation_line + 1
        last = up_to_line - 1
        if first <= last and len(trace) > 1:
            leaf = trace[-1]
            leaf.add_content(
                Content(
                    chunk_number=chunk_number,
                    first_line=first,
                    last_line=last,
                )
            )
        last_annotation_line = up_to_line

    for event in events:
        if event.event_type == "cutoff":
            _flush_content(event.line_number)
            hit_cutoff = True
            break

        if event.event_type != "header":
            continue

        _flush_content(event.line_number)

        depth = max(1, event.depth)
        while len(trace) > 1 and (len(trace) - 1) >= depth:
            trace.pop()

        parent = trace[-1]
        new_node = Node(
            id=event.id,
            title=event.title or event.id,
            children=[],
            content_list=[],
            node_type=_node_type_from_value(event.node_type),
            node_dict=tree_dict,
            dependency_ids=event.deps if event.deps else None,
            proves_id=event.proves,
        )
        parent.add_child(new_node)
        trace.append(new_node)
        added_nodes += 1

    if not hit_cutoff and total_content_lines > last_annotation_line:
        _flush_content(total_content_lines + 1)

    return ApplyResult(added_nodes=added_nodes, active_depth=max(0, len(trace) - 1))
