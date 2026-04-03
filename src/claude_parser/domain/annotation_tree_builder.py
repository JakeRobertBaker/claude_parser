"""Build/extend a domain tree from parsed annotation events.

Handles fragment ASTs where nodes may span batches. The open_stack
tracks nodes started in a previous batch that haven't been closed yet.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from claude_parser.domain.annotation_parser import AnnotationEvent
from claude_parser.domain.content import Content
from claude_parser.domain.node import Node, NodeType, TreeDict


@dataclass
class FragmentResult:
    new_nodes: list[str] = field(default_factory=list)
    closed_nodes: list[str] = field(default_factory=list)
    open_stack: list[str] = field(default_factory=list)
    last_closed_node_id: str | None = None


def process_batch_annotations(
    events: list[AnnotationEvent],
    tree_dict: TreeDict,
    open_stack: list[str],
    chunk_number: int,
    total_content_lines: int,
) -> FragmentResult:
    """Process annotation events from one batch and update the tree.

    Content is added to nodes immediately (in document order) to ensure
    parent/child content ordering rules are respected.

    Args:
        events: Parsed annotation events (start/end/cutoff) for this batch.
        tree_dict: The global node registry. Modified in place.
        open_stack: Node IDs from previous batch that are still open.
        chunk_number: Current batch number for Content objects.
        total_content_lines: Total lines in the cleaned chunk file.

    Returns:
        FragmentResult with new/closed nodes and updated open_stack.
    """
    result = FragmentResult()
    stack = list(open_stack)  # copy — working stack of open node IDs

    last_annotation_line = 0  # line of last processed annotation (0 = start of file)
    hit_cutoff = False

    def _flush_content(up_to_line: int) -> None:
        """Add content lines (last_annotation_line+1, up_to_line-1) to top of stack node."""
        nonlocal last_annotation_line
        if not stack:
            last_annotation_line = up_to_line
            return
        first = last_annotation_line + 1
        last = up_to_line - 1
        if first <= last:
            top_id = stack[-1]
            node = tree_dict[top_id]
            content = Content(
                chunk_number=chunk_number,
                first_line=first,
                last_line=last,
            )
            node.add_content(content)
        last_annotation_line = up_to_line

    for event in events:
        if event.event_type == "cutoff":
            _flush_content(event.line_number)
            hit_cutoff = True
            break

        if event.event_type == "start":
            _flush_content(event.line_number)

            # Determine parent: top of stack, or root
            parent: Node | None = None
            if stack:
                parent = tree_dict[stack[-1]]
            elif tree_dict.root_node is not None:
                parent = tree_dict.root_node

            node_type = NodeType(event.node_type) if event.node_type else NodeType.GENERIC

            new_node = Node(
                id=event.id,
                title=event.title or event.id,
                children=[],
                content_list=[],
                node_type=node_type,
                node_dict=tree_dict,
                dependency_ids=event.dependencies if event.dependencies else None,
                proves_id=event.proves,
            )

            if parent is not None:
                parent.add_child(new_node)

            if tree_dict.root_node is None:
                tree_dict.set_root(new_node)

            stack.append(event.id)
            result.new_nodes.append(event.id)

        elif event.event_type == "end":
            _flush_content(event.line_number)

            if stack and stack[-1] == event.id:
                stack.pop()
                result.closed_nodes.append(event.id)
                result.last_closed_node_id = event.id

    # Flush remaining content after last annotation to end of file
    if not hit_cutoff and total_content_lines > last_annotation_line:
        _flush_content(total_content_lines + 1)

    result.open_stack = stack
    return result
