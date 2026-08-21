from math_parser.adapters.math import KaTeXMathValidator


def test_repairs_doubled_alphabetic_commands_inside_math() -> None:
    result = KaTeXMathValidator().validate(r"Inline $\\mathbf{R}^n$ text.")

    assert result.valid
    assert result.normalized_text == r"Inline $\mathbf{R}^n$ text."
    assert [(item.line, item.column, item.command) for item in result.corrections] == [
        (1, 9, "mathbf")
    ]


def test_preserves_tex_row_breaks_and_ignores_code() -> None:
    markdown = (
        r"$\begin{aligned}a&=b \\ c&=d\end{aligned}$ "
        r"and `$\\notARealCommand{x}$`"
    )

    result = KaTeXMathValidator().validate(markdown)

    assert result.valid
    assert result.normalized_text == markdown
    assert result.corrections == []
    assert result.expressions_checked == 1


def test_reports_sanitized_parse_error_after_safe_repair() -> None:
    result = KaTeXMathValidator().validate(r"Bad $\\notARealCommand{secret}$.")

    assert not result.valid
    assert result.corrections[0].command == "notARealCommand"
    assert result.errors[0].code == "katex_parse_error"
    assert "secret" not in result.errors[0].message


def test_rejects_unclosed_math_delimiter() -> None:
    result = KaTeXMathValidator().validate("Unclosed $x + 1")

    assert not result.valid
    assert result.errors[0].code == "unclosed_math_delimiter"
