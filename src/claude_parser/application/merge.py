import logging
from typing import Any, cast

from claude_parser.adapters.chunk_lines.content import Content
from claude_parser.domain.node import Node, NodeType, TreeDict

logger = logging.getLogger(__name__)

VALID_NODE_TYPES = {t.value for t in NodeType}


def validate_metadata(meta: dict[str, Any]) -> str | None:
    """Validate Haiku's output metadata schema. Returns error message or None."""
    if not isinstance(meta, dict):
        return "metadata is not a dict"
    if "chunk_id" not in meta:
        return "missing 'chunk_id'"
    if "cutoff_line" not in meta:
        return "missing 'cutoff_line'"
    if "section_node_id" not in meta:
        return "missing 'section_node_id'"
    if "new_nodes" not in meta:
        return "missing 'new_nodes'"
    if not isinstance(meta["new_nodes"], list):
        return "'new_nodes' must be a list"

    for i, raw_node in enumerate(meta["new_nodes"]):
        node_data = cast(dict[str, Any], raw_node)
        if "id" not in node_data:
            return f"new_nodes[{i}] missing 'id'"
        if "title" not in node_data:
            return f"new_nodes[{i}] missing 'title'"
        if "parent_id" not in node_data:
            return f"new_nodes[{i}] missing 'parent_id'"
        node_type = node_data.get("node_type", "generic")
        if node_type not in VALID_NODE_TYPES:
            return f"new_nodes[{i}] invalid node_type '{node_type}'"

    return None


def check_duplicate_ids(tree_dict: TreeDict, metadata: dict) -> list[str]:
    """Return list of IDs in metadata that already exist in tree_dict."""
    duplicates = []
    for node_data in metadata.get("new_nodes", []):
        node_id = node_data["id"]
        if node_id in tree_dict._data:
            duplicates.append(node_id)
    return duplicates


def merge_chunk(
    tree_dict: TreeDict,
    root: Node,
    metadata: dict,
    chunk_number: int,
) -> None:
    """Apply Haiku's metadata to the domain tree.

    1. Add section_content to the existing section node.
    2. Create new child nodes from new_nodes.
    """
    section_node_id = metadata["section_node_id"]
    section_node = tree_dict[section_node_id]

    # Add section content to existing node
    for content_data in metadata.get("section_content", []):
        content = Content(
            chunk_number=chunk_number,
            first_line=content_data["first_line"],
            last_line=content_data["last_line"],
        )
        section_node.add_content(content)
        logger.debug(
            "Added content (chunk %d, lines %d-%d) to node '%s'",
            chunk_number, content_data["first_line"],
            content_data["last_line"], section_node_id,
        )

    # Create new child nodes
    for node_data in metadata.get("new_nodes", []):
        parent_id = node_data["parent_id"]
        parent_node = tree_dict[parent_id]

        node_type = NodeType(node_data.get("node_type", "generic"))
        is_theory = node_type != NodeType.GENERIC

        content_list = [
            Content(
                chunk_number=chunk_number,
                first_line=c["first_line"],
                last_line=c["last_line"],
            )
            for c in node_data.get("content", [])
        ]

        new_node = Node(
            id=node_data["id"],
            title=node_data["title"],
            children=[],
            content_list=content_list,
            node_type=node_type,
            theory=is_theory,
            node_dict=tree_dict,
            dependency_ids=node_data.get("dependencies", []),
        )
        parent_node.add_child(new_node)
        logger.info("Created node '%s' under '%s'", node_data["id"], parent_id)


def build_dependency_report(tree_dict: TreeDict) -> dict:
    """Build a report of dependency issues in the completed tree."""
    unresolved = []
    zero_deps = []

    for node_id, node in tree_dict._data.items():
        if not node.theory:
            continue

        if not node._dependencies:
            zero_deps.append(node_id)
            continue

        for dep_id in node._dependencies:
            if dep_id not in tree_dict._data:
                unresolved.append({"node_id": node_id, "missing_dep": dep_id})

    report = {
        "unresolved_dependencies": unresolved,
        "theory_nodes_with_zero_dependencies": zero_deps,
        "total_theory_nodes": sum(
            1 for n in tree_dict._data.values() if n.theory
        ),
    }

    if unresolved:
        logger.warning(
            "%d unresolved dependencies found", len(unresolved),
        )
    logger.info(
        "Dependency report: %d theory nodes, %d with zero deps, %d unresolved",
        report["total_theory_nodes"],
        len(zero_deps),
        len(unresolved),
    )

    return report
