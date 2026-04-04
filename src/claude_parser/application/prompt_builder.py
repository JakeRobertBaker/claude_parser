from claude_parser.application.prompt_templates import ANNOTATION_BATCH_TEMPLATE


def build_batch_prompt(
    raw_content: str,
    raw_start: int,
    raw_end: int,
    raw_line_count: int,
) -> str:
    """Build the annotation batch prompt with raw content embedded."""
    return ANNOTATION_BATCH_TEMPLATE.format(
        raw_content=raw_content,
        raw_start=raw_start,
        raw_end=raw_end,
        raw_line_count=raw_line_count,
    )
