from __future__ import annotations

from typing import cast

from claude_parser.application.batch_tools.service import BatchToolsService
from claude_parser.application.tokens import approximate_claude_tokens
from claude_parser.domain.node import TreeDict
from claude_parser.ports.state import BatchContext, StatePort


class _FakeState:
    def __init__(self):
        self._known_ids: list[str] = []
        self._tree = TreeDict()
        self.written_clean: str | None = None

    @property
    def known_ids(self) -> list[str]:
        return self._known_ids

    @property
    def tree_dict(self) -> TreeDict:
        return self._tree

    def write_clean_batch(self, ordinal: int, content: str) -> None:
        _ = ordinal
        self.written_clean = content

    def set_cutoff(self, source_line: int) -> None:
        _ = source_line


def _build_context(raw_content: str, clean_token_target: int = 1) -> BatchContext:
    raw_line_count = len(raw_content.splitlines())
    return BatchContext(
        raw_content=raw_content,
        raw_start_line=0,
        raw_end_line=raw_line_count,
        raw_line_count=raw_line_count,
        raw_token_count=approximate_claude_tokens(raw_content),
        prior_clean_tail="",
        memory_text="",
        clean_token_target=clean_token_target,
    )


def test_submit_clean_allows_tiny_final_batches() -> None:
    raw_content = "\nAMS on the Web www.ams.org\n"
    context = _build_context(raw_content, clean_token_target=1)
    state = _FakeState()
    service = BatchToolsService(cast(StatePort, state))
    service.begin_batch(context, state.known_ids, state.tree_dict, current_ordinal=0)

    result = service.handle_submit_clean(
        '@ - id="backmatter_footer"\n\nAMS on the Web www.ams.org\n'
    )

    assert result.valid is True
    assert result.errors == []
    assert state.written_clean is not None
    assert state.written_clean.endswith("<!-- cutoff -->\n")


def test_submit_clean_reports_confidence_and_cutoff_violations_separately() -> None:
    line = "alpha bravo charlie delta echo foxtrot golf hotel india juliet\n"
    raw_content = line * 30
    context = _build_context(raw_content, clean_token_target=1)
    state = _FakeState()
    service = BatchToolsService(cast(StatePort, state))
    service.begin_batch(context, state.known_ids, state.tree_dict, current_ordinal=0)

    first_twenty_tokens = "\n".join([line, line])
    low_overlap_tail = (
        "xray yankee zebra mango papaya saffron orchid walnut "
        "pepper almond cherry banana lychee guava pecan cashew "
        "hazelnut pistachio macadamia apricot"
    )
    cleaned_text = (
        '@ - id="sec_cutoff_test"\n\n'
        + first_twenty_tokens
        + "\n"
        + low_overlap_tail
        + "\n"
    )

    result = service.handle_submit_clean(cleaned_text)

    assert result.valid is False
    assert any("Alignment confidence check failed" in e for e in result.errors)
    assert any("Cutoff position check failed" in e for e in result.errors)
