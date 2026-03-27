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

    for child in children:
        child._assign_parent(node)

    # Rule 1: node's own content must precede each child's full span
    if node.content_list:
        node_max = max(node.content_list)
        for child in children:
            if not child.is_after_content(node_max):
                raise ValueError(
                    f"Node '{node.id}' content appears after child '{child.id}'."
                )

    # Rule 2: siblings must have strict non-interleaving ordering
    children_with_content = [c for c in children if c._content_extrema_min()]
    sorted_siblings = sorted(children_with_content, key=lambda c: c._content_extrema_min())
    for i in range(len(sorted_siblings) - 1):
        if not sorted_siblings[i + 1].is_after(sorted_siblings[i]):
            raise ValueError(
                f"Sibling nodes '{sorted_siblings[i].id}' and "
                f"'{sorted_siblings[i + 1].id}' have interleaving content."
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
