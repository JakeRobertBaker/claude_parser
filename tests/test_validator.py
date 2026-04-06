from claude_parser.domain.annotation_parser import AnnotationEvent, parse_annotations
from claude_parser.domain.validator import validate_annotations


def _header(line: int, id: str, depth: int = 1, **kwargs) -> AnnotationEvent:
    return AnnotationEvent(
        line_number=line,
        event_type="header",
        id=id,
        depth=depth,
        title=kwargs.get("title", id),
        node_type=kwargs.get("node_type"),
        proves=kwargs.get("proves"),
        deps=kwargs.get("deps", []),
    )


class TestDuplicateIds:
    def test_duplicate_id_error(self):
        events = [_header(1, "a"), _header(2, "a")]
        result = validate_annotations(events)
        assert not result.valid
        assert any("duplicate id" in e for e in result.errors)

    def test_duplicate_with_known_ids(self):
        events = [_header(1, "existing")]
        result = validate_annotations(events, known_ids={"existing"})
        assert not result.valid


class TestProvesWarnings:
    def test_proves_on_non_proof_warns(self):
        events = [_header(1, "t", node_type="theorem", proves="x")]
        result = validate_annotations(events)
        assert any("non-proof node" in w for w in result.warnings)

    def test_proof_without_proves_warns(self):
        events = [_header(1, "p", node_type="proof")]
        result = validate_annotations(events)
        assert any("missing proves" in w for w in result.warnings)

    def test_proves_non_proveable_target_warns(self):
        events = [
            _header(1, "rem_1", node_type="remark"),
            _header(2, "prf_1", node_type="proof", proves="rem_1"),
        ]
        result = validate_annotations(events)
        assert any("targets type 'remark'" in w for w in result.warnings)


class TestDepsWarnings:
    def test_missing_dep_warns(self):
        events = [_header(1, "n1", deps=["nonexistent"])]
        result = validate_annotations(events)
        assert any("not found" in w for w in result.warnings)

    def test_dep_in_known_ids_ok(self):
        events = [_header(1, "n1", deps=["prev_node"])]
        result = validate_annotations(events, known_ids={"prev_node"})
        assert not any("not found" in w for w in result.warnings)

    def test_dep_on_earlier_event_ok(self):
        events = [
            _header(1, "def_1", node_type="definition"),
            _header(2, "thm_1", node_type="theorem", deps=["def_1"]),
        ]
        result = validate_annotations(events)
        assert not any("not found" in w for w in result.warnings)


class TestBatchStartValidation:
    def test_first_batch_requires_header_before_content(self):
        text = 'Intro text without header\n@ - id="book"'
        events = parse_annotations(text)
        result = validate_annotations(
            events,
            cleaned_text=text,
            has_existing_nodes=False,
        )
        assert not result.valid
        assert any("starts with content" in e for e in result.errors)

    def test_existing_tree_allows_leading_content(self):
        text = 'Continuation line\n@ -- id="next"'
        events = parse_annotations(text)
        result = validate_annotations(
            events,
            cleaned_text=text,
            has_existing_nodes=True,
        )
        assert result.valid


class TestFromParsedText:
    def test_full_roundtrip(self):
        text = """\
@ - id="ch1" title="Ch 1"
@ -- id="thm1" type="theorem" title="Thm 1"
Statement
@ -- id="prf1" type="proof" proves="thm1" title="Proof"
Proof text"""
        events = parse_annotations(text)
        result = validate_annotations(
            events, cleaned_text=text, has_existing_nodes=False
        )
        assert result.valid
        assert result.warnings == []
