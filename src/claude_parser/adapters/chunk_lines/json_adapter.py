from claude_parser.adapters.chunk_lines.content import Content
from claude_parser.domain.node import Node, TreeDict
from claude_parser.adapters.json_adapter import (
    tree_from_dict as _tree_from_dict,
    node_from_dict as _node_from_dict,
)


def content_from_dict(content_dict: dict) -> Content:
    return Content(
        chunk_number=content_dict["chunk_number"],
        first_line=content_dict["first_line"],
        last_line=content_dict["last_line"],
    )


def node_from_dict(node_dict: dict, node_registry: TreeDict) -> Node:
    return _node_from_dict(node_dict, node_registry, content_from_dict)


def tree_from_dict(data: dict) -> tuple[Node, TreeDict]:
    return _tree_from_dict(data, content_from_dict)
