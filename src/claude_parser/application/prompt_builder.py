from claude_parser.application.prompt_templates import ANNOTATION_BATCH_TEMPLATE


def build_batch_prompt() -> str:
    """Build the annotation batch prompt.

    With MCP tools, the prompt is static — all batch-specific context
    (raw content, open stack, known IDs, etc.) is provided by the
    read_batch tool at runtime.
    """
    return ANNOTATION_BATCH_TEMPLATE
