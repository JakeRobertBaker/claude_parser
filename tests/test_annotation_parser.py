from claude_parser.domain.annotation_parser import parse_annotations


class TestParseHeaders:
    def test_basic_header(self):
        text = '@ - id="ch_1" title="Chapter 1"\nContent'
        events = parse_annotations(text)
        assert len(events) == 1
        e = events[0]
        assert e.event_type == "header"
        assert e.id == "ch_1"
        assert e.depth == 1
        assert e.title == "Chapter 1"
        assert e.line_number == 1

    def test_parse_type_proves_deps(self):
        text = '@ --- id="prf_1" type="proof" proves="thm_1" deps=["lem_1","def_2"]'
        events = parse_annotations(text)
        assert len(events) == 1
        e = events[0]
        assert e.depth == 3
        assert e.node_type == "proof"
        assert e.proves == "thm_1"
        assert e.deps == ["lem_1", "def_2"]

    def test_missing_id_header_is_ignored(self):
        text = '@ -- title="No ID"\n@ - id="book"'
        events = parse_annotations(text)
        assert len(events) == 1
        assert events[0].id == "book"


class TestCutoff:
    def test_cutoff_stops_parsing(self):
        text = """\
@ - id="book"
<!-- cutoff -->
@ -- id="ignored"""
        events = parse_annotations(text)
        assert [e.event_type for e in events] == ["header", "cutoff"]
        assert events[1].line_number == 2

    def test_no_cutoff_is_ok(self):
        text = '@ - id="book"\n@ -- id="ch_1"'
        events = parse_annotations(text)
        assert [e.id for e in events] == ["book", "ch_1"]
