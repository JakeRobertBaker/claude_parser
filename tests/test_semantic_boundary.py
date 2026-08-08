from claude_parser.application.batch_tools.semantic_boundary import (
    incomplete_trailing_semantic_unit_start,
)


def test_detects_semantic_heading_continued_by_following_content() -> None:
    assert incomplete_trailing_semantic_unit_start(
        ["# Section C\n", "# 0.42 Definition interval\n", "First clause.\n"],
        ["\n", "Second clause.\n", "# 0.43 Theorem\n"],
    ) == 2


def test_allows_semantic_unit_when_following_context_starts_with_heading() -> None:
    assert (
        incomplete_trailing_semantic_unit_start(
            ["# 0.42 Definition interval\n", "Complete definition.\n"],
            ["\n", "# 0.43 Theorem\n", "Statement.\n"],
        )
        is None
    )


def test_does_not_make_generic_heading_an_indivisible_semantic_unit() -> None:
    assert (
        incomplete_trailing_semantic_unit_start(
            ["# Background\n", "Ordinary prose.\n"],
            ["More ordinary prose.\n"],
        )
        is None
    )
