from claude_parser.domain.annotation_parser import AnnotationEvent, parse_annotations
from claude_parser.domain.validator import validate_annotations


def _start(line: int, id: str, **kwargs) -> AnnotationEvent:
    return AnnotationEvent(
        line_number=line, event_type="start", id=id,
        title=kwargs.get("title", id),
        node_type=kwargs.get("node_type"),
        proves=kwargs.get("proves"),
        dependencies=kwargs.get("dependencies", []),
    )


def _end(line: int, id: str) -> AnnotationEvent:
    return AnnotationEvent(line_number=line, event_type="end", id=id)


class TestProperNesting:
    def test_valid_nesting(self):
        events = [_start(1, "a"), _start(2, "b"), _end(3, "b"), _end(4, "a")]
        result = validate_annotations(events)
        assert result.valid

    def test_crossing_spans_error(self):
        events = [_start(1, "a"), _start(2, "b"), _end(3, "a"), _end(4, "b")]
        result = validate_annotations(events)
        assert not result.valid
        assert any("improper nesting" in e for e in result.errors)

    def test_end_without_start_error(self):
        events = [_end(1, "a")]
        result = validate_annotations(events)
        assert not result.valid
        assert any("no matching open node" in e for e in result.errors)


class TestDuplicateIds:
    def test_duplicate_id_error(self):
        events = [_start(1, "a"), _end(2, "a"), _start(3, "a"), _end(4, "a")]
        result = validate_annotations(events)
        assert not result.valid
        assert any("duplicate id" in e for e in result.errors)

    def test_duplicate_with_known_ids(self):
        events = [_start(1, "existing")]
        result = validate_annotations(events, known_ids={"existing"})
        assert not result.valid

    def test_unique_ids_valid(self):
        events = [_start(1, "a"), _end(2, "a"), _start(3, "b"), _end(4, "b")]
        result = validate_annotations(events)
        assert result.valid


class TestProvesWarnings:
    def test_proves_on_non_proof_warns(self):
        events = [_start(1, "t", node_type="theorem", proves="x")]
        result = validate_annotations(events)
        assert any("non-proof node" in w for w in result.warnings)

    def test_proof_without_proves_warns(self):
        events = [_start(1, "p", node_type="proof")]
        result = validate_annotations(events)
        assert any("missing proves" in w for w in result.warnings)

    def test_proof_with_proves_ok(self):
        events = [
            _start(1, "thm_1", node_type="theorem"),
            _end(2, "thm_1"),
            _start(3, "prf_1", node_type="proof", proves="thm_1"),
            _end(4, "prf_1"),
        ]
        result = validate_annotations(events)
        assert not any("proves" in w for w in result.warnings)

    def test_proves_non_proveable_target_warns(self):
        events = [
            _start(1, "rem_1", node_type="remark"),
            _end(2, "rem_1"),
            _start(3, "prf_1", node_type="proof", proves="rem_1"),
        ]
        result = validate_annotations(events)
        assert any("targets type 'remark'" in w for w in result.warnings)


class TestDependencyWarnings:
    def test_missing_dependency_warns(self):
        events = [_start(1, "n1", dependencies=["nonexistent"])]
        result = validate_annotations(events)
        assert any("not found" in w for w in result.warnings)

    def test_dependency_in_known_ids_ok(self):
        events = [_start(1, "n1", dependencies=["prev_node"])]
        result = validate_annotations(events, known_ids={"prev_node"})
        assert not any("not found" in w for w in result.warnings)

    def test_dependency_on_earlier_event_ok(self):
        events = [
            _start(1, "def_1", node_type="definition"),
            _end(2, "def_1"),
            _start(3, "thm_1", node_type="theorem", dependencies=["def_1"]),
        ]
        result = validate_annotations(events)
        assert not any("not found" in w for w in result.warnings)


class TestUnknownType:
    def test_unknown_type_warns(self):
        events = [_start(1, "n1", node_type="bogus")]
        result = validate_annotations(events)
        assert any("unknown type" in w for w in result.warnings)


class TestFromParsedText:
    def test_full_roundtrip(self):
        text = """\
<!-- tree:start id="ch1" title="Ch 1" -->
<!-- tree:start id="thm1" type="theorem" title="Thm 1" -->
Statement
<!-- tree:end id="thm1" -->
<!-- tree:start id="prf1" type="proof" proves="thm1" title="Proof" -->
Proof text
<!-- tree:end id="prf1" -->
<!-- tree:end id="ch1" -->"""
        events = parse_annotations(text)
        result = validate_annotations(events)
        assert result.valid
        assert result.warnings == []
