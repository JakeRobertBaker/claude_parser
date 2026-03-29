from claude_parser.application.prompt_templates import (
    PHASE0_TEMPLATE,
    SECTION_TEMPLATE,
)
from claude_parser.config import ParserConfig


def build_phase0_prompt(raw_content: str, config: ParserConfig) -> str:
    """Build the Phase 0 prompt with raw content inlined."""
    line_count = raw_content.count("\n")
    return PHASE0_TEMPLATE.format(
        raw_content=raw_content,
        line_count=line_count,
    )


def build_section_prompt(
    window_content: str,
    raw_start_line: int,
    raw_end_line: int,
    chunk_id: str,
    overlap_text: str,
    tree_state_json: str,
    chunk_path: str,
    config: ParserConfig,
) -> str:
    """Build the section prompt with window content and tree state inlined."""
    window_lines = raw_end_line - raw_start_line
    min_lines = int(window_lines * 0.6)

    if overlap_text:
        overlap_section = (
            "## Context (already processed, do not include in output)\n"
            f"{overlap_text}\n\n"
        )
    else:
        overlap_section = ""

    return SECTION_TEMPLATE.format(
        chunk_id=chunk_id,
        raw_start=raw_start_line + 1,
        raw_end=raw_end_line,
        min_lines=min_lines,
        chunk_path=chunk_path,
        tree_state_json=tree_state_json,
        overlap_section=overlap_section,
        window_content=window_content,
    )


def build_retry_prompt(original_prompt: str, duplicate_ids: list[str]) -> str:
    ids_str = ", ".join(f"'{i}'" for i in duplicate_ids)
    suffix = (
        f"\n\n## IMPORTANT CORRECTION\n"
        f"The following node IDs appear more than once in your output: {ids_str}.\n"
        f"Each node ID must be unique. Deduplicate these IDs."
    )
    return original_prompt + suffix
