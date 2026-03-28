from __future__ import annotations
from content import Content
from tree import Node, TreeDict, NodeType


def content_from_dict(content_dict: dict) -> Content:
    return Content(
        chunk_number=content_dict["chunk_number"],
        first_line=content_dict["first_line"],
        last_line=content_dict["last_line"],
    )


def node_from_dict(node_dict: dict, node_registry: TreeDict) -> Node:
    children_dicts = node_dict.get("children", [])
    if not isinstance(children_dicts, list):
        raise ValueError("'children' must be a list.")

    children = [
        node_from_dict(child_dict, node_registry) for child_dict in children_dicts
    ]

    node = Node(
        id=node_dict["id"],
        title=node_dict["title"],
        children=children,
        content_list=[content_from_dict(c) for c in node_dict.get("content", [])],
        node_type=NodeType(node_dict.get("node_type", "generic")),
        theory=node_dict.get("theory", False),
        node_dict=node_registry,
        dependency_ids=node_dict.get("dependencies", []),
    )

    return node


def tree_from_dict(data: dict) -> tuple[Node, TreeDict]:
    """
    Build a full tree from a nested dict. Returns (root_node, tree_dict).
    Both ordering rules are validated recursively during construction.
    """
    node_registry = TreeDict()
    root = node_from_dict(data, node_registry)
    node_registry.set_root(root)
    return root, node_registry
