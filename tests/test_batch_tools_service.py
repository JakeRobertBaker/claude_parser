from __future__ import annotations

from typing import cast

from claude_parser.application.batch_tools.service import BatchToolsService
from claude_parser.application.tokens import approximate_claude_tokens
from claude_parser.domain.annotation_parser import parse_annotations
from claude_parser.domain.annotation_tree_builder import process_batch_annotations
from claude_parser.domain.node import TreeDict
from claude_parser.ports.math_validation import MathValidationResult
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


class _PassthroughMathValidator:
    def validate(self, markdown: str) -> MathValidationResult:
        return MathValidationResult(normalized_text=markdown)


def _make_service(state: _FakeState) -> BatchToolsService:
    return BatchToolsService(
        cast(StatePort, state),
        _PassthroughMathValidator(),
    )


def _build_context(
    raw_content: str,
    clean_token_target: int = 1,
    *,
    next_raw_context: str = "",
    prior_clean_context: str = "",
    prior_continuation_node_id: str | None = None,
) -> BatchContext:
    raw_line_count = len(raw_content.splitlines())
    return BatchContext(
        raw_content=raw_content,
        raw_start_line=0,
        raw_end_line=raw_line_count,
        raw_line_count=raw_line_count,
        raw_token_count=approximate_claude_tokens(raw_content),
        next_raw_context=next_raw_context,
        next_raw_context_line_count=len(next_raw_context.splitlines()),
        next_raw_context_token_count=approximate_claude_tokens(next_raw_context),
        prior_clean_context=prior_clean_context,
        prior_continuation_node_id=prior_continuation_node_id,
        memory_text="",
        clean_token_target=clean_token_target,
    )


def test_submit_clean_allows_tiny_final_batches() -> None:
    raw_content = "\nAMS on the Web www.ams.org\n"
    context = _build_context(raw_content, clean_token_target=1)
    state = _FakeState()
    service = _make_service(state)
    service.begin_batch(context, state.known_ids, state.tree_dict, current_ordinal=0)

    result = service.handle_submit_clean(
        '@ - id="backmatter_footer"\n\nAMS on the Web www.ams.org\n',
        cutoff_kind="clean_boundary",
    )

    assert result.valid is True
    assert result.errors == []
    assert state.written_clean is None
    assert service.handle_commit_batch().success is True
    assert state.written_clean is not None
    assert state.written_clean.endswith("<!-- cutoff -->\n")


def test_submit_clean_reports_confidence_and_cutoff_violations_separately() -> None:
    line = "alpha bravo charlie delta echo foxtrot golf hotel india juliet\n"
    raw_content = line * 30
    context = _build_context(raw_content, clean_token_target=1)
    state = _FakeState()
    service = _make_service(state)
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

    result = service.handle_submit_clean(
        cleaned_text, cutoff_kind="clean_boundary"
    )

    assert result.valid is False
    assert any("Alignment confidence check failed" in e for e in result.errors)
    assert any("Cutoff position check failed" in e for e in result.errors)


def test_submit_clean_validates_and_persists_explicit_continuation() -> None:
    raw_content = "Definition alpha has two clauses.\n"
    context = _build_context(
        raw_content,
        next_raw_context="The second clause continues here.\n",
    )
    state = _FakeState()
    service = _make_service(state)
    service.begin_batch(context, state.known_ids, state.tree_dict, current_ordinal=0)

    cleaned_text = (
        '@ - id="def_alpha" type="definition"\n\n'
        "Definition alpha has two clauses.\n"
    )
    result = service.handle_submit_clean(
        cleaned_text,
        cutoff_kind="continuation",
        continuation_node_id="def_alpha",
    )

    assert result.valid is True
    assert result.continuation_node_id == "def_alpha"
    assert service.handle_commit_batch().success is True
    assert service.committed_continuation_node_id() == "def_alpha"


def test_submit_clean_rejects_continuation_that_is_not_active_leaf() -> None:
    raw_content = "Definition alpha has two clauses.\n"
    context = _build_context(raw_content)
    state = _FakeState()
    service = _make_service(state)
    service.begin_batch(context, state.known_ids, state.tree_dict, current_ordinal=0)

    result = service.handle_submit_clean(
        '@ - id="def_alpha" type="definition"\n\n'
        "Definition alpha has two clauses.\n",
        cutoff_kind="continuation",
        continuation_node_id="wrong_node",
    )

    assert result.valid is False
    assert any("active leaf" in error for error in result.errors)


def test_read_batch_returns_structured_prior_continuation_only_when_declared() -> None:
    state = _FakeState()
    prior_clean = (
        '@ - id="def_alpha" type="definition"\n\n'
        "Definition alpha begins.\n"
    )
    process_batch_annotations(
        parse_annotations(prior_clean),
        state.tree_dict,
        chunk_number=0,
        total_content_lines=len(prior_clean.splitlines()),
    )
    context = _build_context(
        "Definition alpha finishes.\n",
        prior_continuation_node_id="def_alpha",
    )
    service = _make_service(state)
    service.begin_batch(context, state.known_ids, state.tree_dict, current_ordinal=1)

    payload = service.build_read_batch_payload()

    continuation = payload.read_only_context.prior_continuation
    assert continuation is not None
    assert continuation.node_id == "def_alpha"
    assert continuation.node_type == "definition"
    assert continuation.depth == 1


def test_submit_clean_allows_persisted_prior_continuation() -> None:
    state = _FakeState()
    prior_clean = (
        '@ - id="def_alpha" type="definition"\n\n'
        "Definition alpha begins and remains unfinished.\n"
    )
    process_batch_annotations(
        parse_annotations(prior_clean),
        state.tree_dict,
        chunk_number=0,
        total_content_lines=len(prior_clean.splitlines()),
    )
    raw_content = (
        "Its remaining clauses are alpha bravo charlie delta echo foxtrot golf hotel "
        "india juliet kilo lima mike november oscar papa quebec romeo.\n"
    )
    context = _build_context(
        raw_content,
        next_raw_context="The same definition continues again.\n",
        prior_continuation_node_id="def_alpha",
    )
    service = _make_service(state)
    service.begin_batch(context, state.known_ids, state.tree_dict, current_ordinal=1)

    result = service.handle_submit_clean(
        raw_content,
        cutoff_kind="continuation",
        continuation_node_id="def_alpha",
    )

    assert result.valid is True
    assert result.continuation_node_id == "def_alpha"


def test_submit_clean_rejects_text_copied_from_next_raw_context() -> None:
    raw_content = (
        "alpha bravo charlie delta echo foxtrot golf hotel india juliet kilo lima "
        "mike november oscar papa quebec romeo sierra tango uniform victor whiskey "
        "xray yankee zulu.\n"
    )
    next_raw_context = (
        "apricot banana cashew date elderberry fig grape hazelnut kiwi lemon mango "
        "nectarine orange peach quince raspberry strawberry.\n"
    )
    context = _build_context(
        raw_content,
        next_raw_context=next_raw_context,
    )
    state = _FakeState()
    service = _make_service(state)
    service.begin_batch(context, state.known_ids, state.tree_dict, current_ordinal=0)

    result = service.handle_submit_clean(
        '@ - id="sec_alpha"\n\n' + raw_content + next_raw_context,
        cutoff_kind="clean_boundary",
    )

    assert result.valid is False
    assert result.next_raw_context_violation is True
    assert any("read_only_context.next_raw_content" in error for error in result.errors)
    assert result.committable_raw_tail
    assert result.read_only_next_raw_head
    assert result.submitted_clean_tail
    assert "apricot banana" in " ".join(result.read_only_next_raw_head)
    assert state.written_clean is None


def test_submit_clean_allows_core_without_copying_next_raw_context() -> None:
    raw_content = (
        "alpha bravo charlie delta echo foxtrot golf hotel india juliet kilo lima "
        "mike november oscar papa quebec romeo sierra tango uniform victor whiskey "
        "xray yankee zulu.\n"
    )
    context = _build_context(
        raw_content,
        next_raw_context="Following material belongs to the next batch only.\n",
    )
    state = _FakeState()
    service = _make_service(state)
    service.begin_batch(context, state.known_ids, state.tree_dict, current_ordinal=0)

    result = service.handle_submit_clean(
        '@ - id="sec_alpha"\n\n' + raw_content,
        cutoff_kind="clean_boundary",
    )

    assert result.valid is True
    assert result.inferred_cutoff_batch_line == 1
    assert result.rollback_lines == 0
    assert result.next_raw_context_violation is False


def test_submit_clean_requires_rollback_before_trailing_semantic_unit() -> None:
    opening = (
        "alpha bravo charlie delta echo foxtrot golf hotel india juliet kilo lima "
        "mike november oscar papa quebec romeo sierra tango uniform.\n"
    )
    trailing_definition = (
        "# 0.42 Definition interval\n\n"
        "* The first clause uses victor whiskey xray yankee zulu apricot banana.\n"
    )
    context = _build_context(
        opening + trailing_definition,
        next_raw_context=(
            "* The second clause continues the same definition with cherry date fig.\n\n"
            "# 0.43 Theorem description of intervals\n"
        ),
    )
    state = _FakeState()
    service = _make_service(state)
    service.begin_batch(context, state.known_ids, state.tree_dict, current_ordinal=0)

    rejected = service.handle_submit_clean(
        '@ - id="sec_alpha"\n\n'
        + opening
        + '@ -- id="def_0_42" type="definition"\n\n'
        + "The first clause uses victor whiskey xray yankee zulu apricot banana.\n",
        cutoff_kind="clean_boundary",
    )

    assert rejected.valid is False
    assert any("Semantic boundary check failed" in error for error in rejected.errors)
    assert state.written_clean is None

    accepted = service.handle_submit_clean(
        '@ - id="sec_alpha"\n\n' + opening,
        cutoff_kind="clean_boundary",
    )

    assert accepted.valid is True
    assert accepted.inferred_cutoff_batch_line == 1
    assert accepted.rollback_lines == 3


def test_submit_clean_rejects_late_new_continuation() -> None:
    opening = (
        "Opening material alpha bravo charlie delta echo foxtrot golf hotel india "
        "juliet kilo lima mike november oscar.\n"
    )
    late_definition = (
        "Definition beta begins with papa quebec romeo sierra tango uniform victor "
        "whiskey xray yankee zulu and remains unfinished.\n"
    )
    context = _build_context(
        opening + late_definition,
        next_raw_context="The definition beta finishes in the following batch.\n",
    )
    state = _FakeState()
    service = _make_service(state)
    service.begin_batch(context, state.known_ids, state.tree_dict, current_ordinal=0)

    cleaned_text = (
        '@ - id="sec_opening"\n\n'
        + opening
        + '@ -- id="def_beta" type="definition"\n\n'
        + late_definition
    )
    result = service.handle_submit_clean(
        cleaned_text,
        cutoff_kind="continuation",
        continuation_node_id="def_beta",
    )

    assert result.valid is False
    assert any("opening annotation block" in error for error in result.errors)
    assert state.written_clean is None


def test_submit_clean_rejects_continuation_at_source_eof() -> None:
    raw_content = (
        "Definition alpha has clauses alpha bravo charlie delta echo foxtrot golf "
        "hotel india juliet kilo lima mike november oscar papa quebec romeo.\n"
    )
    context = _build_context(raw_content)
    state = _FakeState()
    service = _make_service(state)
    service.begin_batch(context, state.known_ids, state.tree_dict, current_ordinal=0)

    result = service.handle_submit_clean(
        '@ - id="def_alpha" type="definition"\n\n' + raw_content,
        cutoff_kind="continuation",
        continuation_node_id="def_alpha",
    )

    assert result.valid is False
    assert any("source EOF" in error for error in result.errors)


def test_tree_context_exposes_active_trace_and_explicit_sibling_omissions() -> None:
    state = _FakeState()
    annotations = ['@ - id="book"\nBook\n']
    for index in range(7):
        annotations.append(f'@ -- id="sec_{index}"\nSection {index}\n')
    text = "".join(annotations)
    process_batch_annotations(
        parse_annotations(text),
        state.tree_dict,
        chunk_number=0,
        total_content_lines=len(text.splitlines()),
    )
    service = _make_service(state)
    service.begin_batch(
        _build_context("Next section.\n"),
        state.known_ids,
        state.tree_dict,
        current_ordinal=1,
    )

    context = service.build_read_batch_payload().tree_context

    assert [node["id"] for node in context["active_trace"]] == ["book", "sec_6"]
    book_children = context["append_neighborhoods"][-1]
    assert book_children["total_children"] == 7
    assert book_children["omitted_before"] == 2
    assert [node["id"] for node in book_children["children"]] == [
        "sec_2",
        "sec_3",
        "sec_4",
        "sec_5",
        "sec_6",
    ]


def test_adjust_depths_previews_and_persists_only_reviewed_candidate() -> None:
    raw_content = (
        "Book title.\n"
        "Section C introduction.\n"
        "Interior subsection.\n"
        "Section D introduction.\n"
    )
    cleaned_text = (
        '@ - id="book"\nBook title.\n'
        '@ -- id="sec_c"\nSection C introduction.\n'
        '@ --- id="sec_c_interior"\nInterior subsection.\n'
        '@ --- id="sec_d"\nSection D introduction.\n'
    )
    state = _FakeState()
    service = _make_service(state)
    service.begin_batch(
        _build_context(raw_content),
        state.known_ids,
        state.tree_dict,
        current_ordinal=0,
    )

    submitted = service.handle_submit_clean(
        cleaned_text, cutoff_kind="clean_boundary"
    )

    assert submitted.valid
    assert submitted.commit_ready
    submitted_nodes = {
        item["id"]: item for item in submitted.proposed_tree["batch_nodes"]
    }
    assert submitted_nodes["sec_d"]["parent_id"] == "sec_c"
    assert state.written_clean is None

    failed = service.handle_adjust_depths([{"node_id": "older_node", "depth": 2}])
    assert not failed.valid
    assert not service.handle_commit_batch().success

    adjusted = service.handle_adjust_depths([{"node_id": "sec_d", "depth": 2}])

    assert adjusted.valid
    adjusted_nodes = {
        item["id"]: item for item in adjusted.proposed_tree["batch_nodes"]
    }
    assert adjusted_nodes["sec_d"]["parent_id"] == "book"
    assert service.handle_commit_batch().success
    assert state.written_clean is not None
    assert '@ -- id="sec_d"' in state.written_clean
    assert '@ --- id="sec_d"' not in state.written_clean


def test_proof_placement_advisory_is_resolved_by_depth_edit() -> None:
    raw_content = "Book.\nTheorem statement.\nProof text.\n"
    cleaned_text = (
        '@ - id="book"\nBook.\n'
        '@ -- id="thm_1" type="theorem"\nTheorem statement.\n'
        '@ --- id="proof_1" type="proof" proves="thm_1"\nProof text.\n'
    )
    state = _FakeState()
    service = _make_service(state)
    service.begin_batch(
        _build_context(raw_content),
        state.known_ids,
        state.tree_dict,
        current_ordinal=0,
    )

    submitted = service.handle_submit_clean(
        cleaned_text, cutoff_kind="clean_boundary"
    )

    assert submitted.valid
    assert not submitted.commit_ready
    assert submitted.tree_advisories == [
        {
            "code": "proof_should_be_statement_sibling",
            "node_id": "proof_1",
            "target_id": "thm_1",
            "current_parent_id": "thm_1",
            "expected_parent_id": "book",
            "suggested_depth": 2,
        }
    ]
    blocked_commit = service.handle_commit_batch()
    assert not blocked_commit.success
    assert "Tree review is unresolved" in (blocked_commit.error or "")

    adjusted = service.handle_adjust_depths([{"node_id": "proof_1", "depth": 2}])

    assert adjusted.valid
    assert adjusted.commit_ready
    assert adjusted.tree_advisories == []
    proof = next(
        item
        for item in adjusted.proposed_tree["batch_nodes"]
        if item["id"] == "proof_1"
    )
    assert proof["parent_id"] == "book"
    assert service.handle_commit_batch().success
