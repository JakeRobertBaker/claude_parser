from __future__ import annotations
from collections.abc import Callable
from typing import Any
from claude_parser.domain.protocols import ContentBase
from claude_parser.domain.content import Content
from claude_parser.domain.node import Node, TreeDict, NodeType


def content_from_dict(content_dict: dict) -> Content:
    return Content(
        chunk_number=content_dict["chunk_number"],
        first_line=content_dict["first_line"],
        last_line=content_dict["last_line"],
    )


def content_to_dict(content: Content) -> dict:
    return {
        "chunk_number": content.chunk_number,
        "first_line": content.first_line,
        "last_line": content.last_line,
    }


def node_from_dict(
    node_dict: dict,
    node_registry: TreeDict,
    content_deserializer: Callable[[dict], ContentBase] = content_from_dict,
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
        content_list=[content_deserializer(c) for c in node_dict.get("content", [])],
        node_type=NodeType(node_dict.get("node_type", "generic")),
        theory=node_dict.get("theory", False),
        node_dict=node_registry,
        dependency_ids=node_dict.get("dependencies", []),
    )

    return node


def node_to_dict(
    node: Node,
    content_serializer: Callable[[Any], dict] = content_to_dict,
) -> dict:
    result: dict = {
        "id": node.id,
        "title": node.title,
    }
    if node.content_list:
        result["content"] = [content_serializer(c) for c in node.content_list]
    if node.node_type != NodeType.GENERIC:
        result["node_type"] = node.node_type.value
    if node.theory:
        result["theory"] = True
    if node._dependency_ids:
        result["dependencies"] = node._dependency_ids
    if node.children:
        result["children"] = [
            node_to_dict(child, content_serializer) for child in node.children
        ]
    return result


def tree_from_dict(
    data: dict,
    content_deserializer: Callable[[dict], ContentBase] = content_from_dict,
) -> tuple[Node, TreeDict]:
    """
    Build a full tree from a nested dict. Returns (root_node, tree_dict).
    Both ordering rules are validated recursively during construction.
    """
    node_registry = TreeDict()
    root = node_from_dict(data, node_registry, content_deserializer)
    node_registry.set_root(root)
    return root, node_registry


def tree_to_dict(
    root: Node,
    content_serializer: Callable[[Any], dict] = content_to_dict,
) -> dict:
    return node_to_dict(root, content_serializer)
