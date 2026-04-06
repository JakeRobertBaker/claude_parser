from claude_parser.domain.annotation_parser import parse_annotations


class TestParseHeaders:
    def test_basic_start(self):
        text = '@ - id="ch_1" title="Chapter 1"\nContent'
        events = parse_annotations(text)
        assert len(events) == 1
        e = events[0]
        assert e.event_type == "start"
        assert e.id == "ch_1"
        assert e.title == "Chapter 1"
        assert e.line_number == 1

    def test_parse_type_proves_deps(self):
        text = '@ --- id="prf_1" type="proof" proves="thm_1" deps=["lem_1","def_2"]'
        events = parse_annotations(text)
        assert events[0].node_type == "proof"
        assert events[0].proves == "thm_1"
        assert events[0].deps == ["lem_1", "def_2"]

    def test_parse_deps_fallback_dependencies(self):
        text = '@ -- id="thm_2" dependencies="def_1,thm_1"'
        events = parse_annotations(text)
        assert events[0].deps == ["def_1", "thm_1"]


class TestDepthTransitions:
    def test_same_depth_closes_previous_sibling(self):
        text = """\
@ - id="book"
@ -- id="ch1"
@ -- id="ch2"""
        events = parse_annotations(text)
        assert [e.event_type for e in events] == ["start", "start", "end", "start"]
        assert events[2].id == "ch1"
        assert events[2].line_number == 3

    def test_shallower_depth_closes_ancestors(self):
        text = """\
@ - id="book"
@ -- id="ch1"
@ --- id="sec1"
@ -- id="ch2"""
        events = parse_annotations(text)
        assert [e.event_type for e in events] == [
            "start",
            "start",
            "start",
            "end",
            "end",
            "start",
        ]
        assert events[3].id == "sec1"
        assert events[4].id == "ch1"

    def test_respects_open_stack(self):
        text = """\
@ --- id="sec2"
@ -- id="ch2"""
        events = parse_annotations(text, open_stack=["book", "ch1"])
        assert [e.event_type for e in events] == ["start", "end", "end", "start"]
        assert events[1].id == "sec2"
        assert events[2].id == "ch1"


class TestParseCutoff:
    def test_cutoff_stops_parsing(self):
        text = """\
@ - id="book"
<!-- cutoff -->
@ -- id="ignored"""
        events = parse_annotations(text)
        assert [e.event_type for e in events] == ["start", "cutoff"]
        assert events[1].line_number == 2
