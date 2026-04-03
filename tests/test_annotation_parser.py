from claude_parser.domain.annotation_parser import parse_annotations


class TestParseStart:
    def test_basic_start(self):
        text = '<!-- tree:start id="ch_1" title="Chapter 1" -->\nContent\n<!-- tree:end id="ch_1" -->'
        events = parse_annotations(text)
        assert len(events) == 2
        e = events[0]
        assert e.event_type == "start"
        assert e.id == "ch_1"
        assert e.title == "Chapter 1"
        assert e.line_number == 1

    def test_start_with_type(self):
        text = '<!-- tree:start id="thm_1" type="theorem" title="Theorem 1" -->'
        events = parse_annotations(text)
        assert events[0].node_type == "theorem"

    def test_start_with_anc(self):
        text = '<!-- tree:start id="thm_1" anc="ch_1/sec_1" title="Thm" -->'
        events = parse_annotations(text)
        assert events[0].anc == "ch_1/sec_1"

    def test_start_with_proves(self):
        text = '<!-- tree:start id="prf_1" type="proof" proves="thm_1" title="Proof" -->'
        events = parse_annotations(text)
        assert events[0].proves == "thm_1"

    def test_start_with_dependencies(self):
        text = '<!-- tree:start id="thm_2" title="Thm 2" dependencies="def_1,thm_1" -->'
        events = parse_annotations(text)
        assert events[0].dependencies == ["def_1", "thm_1"]

    def test_empty_dependencies(self):
        text = '<!-- tree:start id="n1" title="N1" -->'
        events = parse_annotations(text)
        assert events[0].dependencies == []


class TestParseEnd:
    def test_basic_end(self):
        text = '<!-- tree:end id="ch_1" -->'
        events = parse_annotations(text)
        assert len(events) == 1
        assert events[0].event_type == "end"
        assert events[0].id == "ch_1"
        assert events[0].line_number == 1


class TestParseCutoff:
    def test_cutoff(self):
        text = 'line1\n<!-- cutoff -->\nline3'
        events = parse_annotations(text)
        assert len(events) == 1
        assert events[0].event_type == "cutoff"
        assert events[0].line_number == 2

    def test_cutoff_with_whitespace(self):
        text = '<!--  cutoff  -->'
        events = parse_annotations(text)
        assert len(events) == 1


class TestParseAnnotations:
    def test_full_example(self):
        text = """\
<!-- tree:start id="ch_x" title="Chapter X" -->
# Chapter X

<!-- tree:start id="thm_a" type="theorem" title="Theorem A" -->
Statement of Theorem A
<!-- tree:end id="thm_a" -->

<!-- tree:start id="prf_a" type="proof" proves="thm_a" title="Proof of A" -->
Proof content
<!-- tree:end id="prf_a" -->

<!-- tree:end id="ch_x" -->"""
        events = parse_annotations(text)
        assert len(events) == 6
        types = [e.event_type for e in events]
        assert types == ["start", "start", "end", "start", "end", "end"]
        assert events[0].id == "ch_x"
        assert events[1].id == "thm_a"
        assert events[3].proves == "thm_a"

    def test_no_annotations(self):
        text = "Just plain markdown\nNo annotations here"
        events = parse_annotations(text)
        assert events == []

    def test_start_without_id_skipped(self):
        text = '<!-- tree:start title="No ID" -->'
        events = parse_annotations(text)
        assert events == []

    def test_line_numbers_correct(self):
        text = "line 1\nline 2\n<!-- tree:start id=\"n1\" title=\"N1\" -->\nline 4"
        events = parse_annotations(text)
        assert events[0].line_number == 3

    def test_mixed_content_and_annotations(self):
        text = """\
Some preamble text
<!-- tree:start id="sec1" title="Section 1" -->
Content for section 1
More content
<!-- cutoff -->
unchanged raw text"""
        events = parse_annotations(text)
        assert len(events) == 2
        assert events[0].event_type == "start"
        assert events[0].line_number == 2
        assert events[1].event_type == "cutoff"
        assert events[1].line_number == 5
