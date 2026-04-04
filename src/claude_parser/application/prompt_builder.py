from claude_parser.application.prompt_templates import ANNOTATION_BATCH_TEMPLATE


def build_batch_prompt() -> str:
    """Build the annotation batch prompt (raw content comes from read_batch tool)."""
    return ANNOTATION_BATCH_TEMPLATE
