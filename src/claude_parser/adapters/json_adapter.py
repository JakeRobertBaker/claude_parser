from __future__ import annotations
from collections.abc import Callable
from claude_parser.domain.ports import ContentBase
from claude_parser.domain.node import Node, TreeDict, NodeType


def node_from_dict(
    node_dict: dict,
    node_registry: TreeDict,
    content_deserializer: Callable[[dict], ContentBase],
) -> Node:
    children_dicts = node_dict.get("children", [])
    if not isinstance(children_dicts, list):
        raise ValueError("'children' must be a list.")

    children = [
        node_from_dict(child_dict, node_registry, content_deserializer)
        for child_dict in children_dicts
    ]

    node = Node(
        id=node_dict["id"],
        title=node_dict["title"],
        children=children,
        content_list=[
            content_deserializer(c) for c in node_dict.get("content", [])
        ],
        node_type=NodeType(node_dict.get("node_type", "generic")),
        theory=node_dict.get("theory", False),
        node_dict=node_registry,
        dependency_ids=node_dict.get("dependencies", []),
    )

    return node


def tree_from_dict(
    data: dict,
    content_deserializer: Callable[[dict], ContentBase],
) -> tuple[Node, TreeDict]:
    """
    Build a full tree from a nested dict. Returns (root_node, tree_dict).
    Both ordering rules are validated recursively during construction.
    """
    node_registry = TreeDict()
    root = node_from_dict(data, node_registry, content_deserializer)
    node_registry.set_root(root)
    return root, node_registry
