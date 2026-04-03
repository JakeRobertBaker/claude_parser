import logging
from typing import Any, cast

from claude_parser.domain.content import Content
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
    if "nodes" not in meta:
        return "missing 'nodes'"
    if not isinstance(meta["nodes"], list):
        return "'nodes' must be a list"

    for i, raw_node in enumerate(meta["nodes"]):
        node_data = cast(dict[str, Any], raw_node)
        if "id" not in node_data:
            return f"nodes[{i}] missing 'id'"
        if "title" not in node_data:
            return f"nodes[{i}] missing 'title'"
        node_type = node_data.get("node_type", "generic")
        if node_type not in VALID_NODE_TYPES:
            return f"nodes[{i}] invalid node_type '{node_type}'"

    return None


def check_intra_duplicates(metadata: dict) -> list[str]:
    """Return IDs that appear more than once in the output's nodes list."""
    seen: set[str] = set()
    duplicates: list[str] = []
    for node_data in metadata.get("nodes", []):
        node_id = node_data["id"]
        if node_id in seen:
            duplicates.append(node_id)
        seen.add(node_id)
    return duplicates


def validate_chunk_file(
    metadata: dict[str, Any],
    chunk_path: str,
    raw_start: int,
    raw_end: int,
) -> str | None:
    """Warn-only validation of chunk file vs metadata.

    Logs warnings for discrepancies but never rejects. Returns an error
    only if the chunk file is completely missing.
    """
    import os

    if not os.path.exists(chunk_path):
        return f"chunk file not found: {chunk_path}"

    with open(chunk_path, encoding="utf-8") as f:
        actual_lines = sum(1 for _ in f)

    # Find the max last_line claimed by metadata
    max_last_line = 0
    for node_data in metadata.get("nodes", []):
        for content in node_data.get("content", []):
            last = content.get("last_line", 0)
            if last > max_last_line:
                max_last_line = last

    line_diff = max_last_line - actual_lines
    if line_diff > 0:
        logger.warning(
            "Chunk file has %d lines but metadata claims %d (off by %d)",
            actual_lines,
            max_last_line,
            line_diff,
        )

    # Check cutoff vs content coverage — warn if very low
    cutoff = metadata.get("cutoff_line", raw_end)
    raw_lines_covered = cutoff - raw_start
    if raw_lines_covered > 0 and actual_lines > 0:
        ratio = actual_lines / raw_lines_covered
        if ratio < 0.15:
            logger.warning(
                "Low coverage: %d cleaned lines for %d raw lines (%.0f%%) "
                "— content may have been skipped",
                actual_lines,
                raw_lines_covered,
                ratio * 100,
            )
        if ratio < 0.30:
            logger.warning(
                "Low coverage ratio: %d cleaned lines for %d raw lines (%.0f%%)",
                actual_lines,
                raw_lines_covered,
                ratio * 100,
            )

    return None


def merge_chunk(
    tree_dict: TreeDict,
    root: Node,
    metadata: dict,
    chunk_number: int,
) -> None:
    """Apply Haiku's metadata to the domain tree.

    Iterates the flat nodes list in order:
    - Existing ID -> add content to existing node
    - New ID -> create new node as child of parent_id
    """
    for node_data in metadata["nodes"]:
        node_id = node_data["id"]

        if node_id in tree_dict._data:
            existing = tree_dict[node_id]
            for content_data in node_data.get("content", []):
                content = Content(
                    chunk_number=chunk_number,
                    first_line=content_data["first_line"],
                    last_line=content_data["last_line"],
                )
                existing.add_content(content)
                logger.debug(
                    "Added content (chunk %d, lines %d-%d) to existing node '%s'",
                    chunk_number,
                    content_data["first_line"],
                    content_data["last_line"],
                    node_id,
                )
        else:
            parent_id = node_data.get("parent_id")
            if not parent_id:
                raise ValueError(f"New node '{node_id}' missing required 'parent_id'")
            parent_node = tree_dict[parent_id]

            node_type = NodeType(node_data.get("node_type", "generic"))

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
                node_dict=tree_dict,
                dependency_ids=node_data.get("dependencies", []),
                proves_id=node_data.get("proves_id"),
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

        if not node._dependency_ids:
            zero_deps.append(node_id)
            continue

        for dep_id in node._dependency_ids:
            if dep_id not in tree_dict._data:
                unresolved.append({"node_id": node_id, "missing_dep": dep_id})

    report = {
        "unresolved_dependencies": unresolved,
        "theory_nodes_with_zero_dependencies": zero_deps,
        "total_theory_nodes": sum(1 for n in tree_dict._data.values() if n.theory),
    }

    if unresolved:
        logger.warning(
            "%d unresolved dependencies found",
            len(unresolved),
        )
    logger.info(
        "Dependency report: %d theory nodes, %d with zero deps, %d unresolved",
        report["total_theory_nodes"],
        len(zero_deps),
        len(unresolved),
    )

    return report
