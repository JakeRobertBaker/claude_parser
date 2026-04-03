from claude_parser.application.prompt_templates import ANNOTATION_BATCH_TEMPLATE
from claude_parser.config import ParserConfig


def build_batch_prompt(
    raw_path: str,
    clean_path: str,
    chunk_id: str,
    raw_start: int,
    raw_end: int,
    raw_line_count: int,
    open_stack: list[str],
    context_text: str,
    memory_text: str,
    known_ids: list[str],
    config: ParserConfig,
) -> str:
    """Build the annotation batch prompt."""
    min_lines = int((raw_end - raw_start) * 0.6)

    if open_stack:
        open_nodes_section = (
            "## Currently Open Nodes (from previous batch)\n"
            "These nodes were started but not yet closed. You should either "
            "continue adding content to them or close them with tree:end.\n\n"
            + "\n".join(f"- `{nid}`" for nid in open_stack)
            + "\n\n"
        )
    else:
        open_nodes_section = ""

    if context_text:
        context_section = (
            "## Context (last lines of previous batch, already processed)\n"
            f"{context_text}\n\n"
        )
    else:
        context_section = ""

    if memory_text:
        memory_section = (
            "## Memory (persistent notes across batches)\n"
            f"{memory_text}\n\n"
        )
    else:
        memory_section = ""

    if known_ids:
        known_ids_arg = " --known-ids " + " ".join(known_ids)
    else:
        known_ids_arg = ""

    return ANNOTATION_BATCH_TEMPLATE.format(
        raw_path=raw_path,
        clean_path=clean_path,
        chunk_id=chunk_id,
        raw_start=raw_start,
        raw_end=raw_end,
        raw_line_count=raw_line_count,
        min_lines=min_lines,
        open_nodes_section=open_nodes_section,
        context_section=context_section,
        memory_section=memory_section,
        known_ids_arg=known_ids_arg,
    )
