import tiktoken


def approximate_claude_tokens(text):
    # p50k_base is the closest common offline proxy for Claude
    encoding = tiktoken.get_encoding("p50k_base")
    return len(encoding.encode(text))
