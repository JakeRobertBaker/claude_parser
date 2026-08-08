import tiktoken

from claude_parser.application.run_engine import TokenCounter


def approximate_claude_tokens(text: str) -> int:
    # p50k_base is the closest common offline proxy for Claude
    encoding = tiktoken.get_encoding("p50k_base")
    return len(encoding.encode(text))


def tail_within_token_budget(
    text: str,
    token_budget: int,
    token_counter: TokenCounter = approximate_claude_tokens,
) -> str:
    """Return the largest whole-line suffix that fits the token budget."""
    if not text or token_budget <= 0:
        return ""

    selected: list[str] = []
    for line in reversed(text.splitlines(keepends=True)):
        candidate = line + "".join(selected)
        if token_counter(candidate) > token_budget:
            break
        selected.insert(0, line)
    return "".join(selected)
