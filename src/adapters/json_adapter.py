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
        raise ValueError("children should always be a list.")

    children = [
        node_from_dict(child_dict, node_registry) for child_dict in children_dicts
    ]

    node = Node(
        id=node_dict["id"],
        title=node_dict["title"],
        children=children,
        content=[content_from_dict(c) for c in node_dict.get("content", [])],
        node_type=NodeType(node_dict["node_type"]),
        theory=node_dict["theory"],
        rank_increment=node_dict["rank_increment"],
        node_dict=node_registry,
        dependency_ids=node_dict.get("dependencies", []),
    )

    node_registry.register(node)

    for child in children:
        child.parent = node

    return node
