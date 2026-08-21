from math_parser.application.tokens import tail_within_token_budget


def test_tail_within_token_budget_keeps_largest_whole_line_suffix() -> None:
    text = "one\ntwo-two\nthree\n"

    tail = tail_within_token_budget(text, token_budget=14, token_counter=len)

    assert tail == "two-two\nthree\n"


def test_tail_within_token_budget_returns_empty_when_last_line_does_not_fit() -> None:
    assert tail_within_token_budget(
        "short\nvery-long-final-line\n",
        token_budget=5,
        token_counter=len,
    ) == ""
