from claude_parser.domain.annotation_parser import parse_annotations
from claude_parser.domain.annotation_tree_builder import (
    INTERNAL_ROOT_ID,
    active_trace_ids,
    process_batch_annotations,
    visible_roots,
)
from claude_parser.domain.content import Content
from claude_parser.domain.node import NodeType, TreeDict


class TestSingleBatch:
    def test_build_tree_with_hidden_root(self):
        text = (
            '@ - id="book"\n'
            '@ -- id="ch1"\n'
            "Some content here\n"
            "More content\n"
            '@ -- id="ch2"'
        )
        events = parse_annotations(text)
        td = TreeDict()
        result = process_batch_annotations(
            events, td, chunk_number=0, total_content_lines=5
        )

        assert td.root_node is not None
        assert td.root_node.id == INTERNAL_ROOT_ID
        roots = visible_roots(td)
        assert [n.id for n in roots] == ["book"]

        assert "book" in td._data
        assert "ch1" in td._data
        assert "ch2" in td._data
        assert td["ch1"].parent is td["book"]
        assert td["ch2"].parent is td["book"]
        assert result.added_nodes == 3
        assert result.active_depth == 2

    def test_content_assigned_to_active_leaf(self):
        text = """\
@ - id="book"
Content line 1
Content line 2
<!-- cutoff -->"""
        events = parse_annotations(text)
        td = TreeDict()
        process_batch_annotations(events, td, chunk_number=0, total_content_lines=4)

        book = td["book"]
        assert len(book.content_list) == 1
        c = book.content_list[0]
        assert isinstance(c, Content)
        assert c.chunk_number == 0
        assert c.first_line == 2
        assert c.last_line == 3

    def test_node_types_proves_and_deps(self):
        text = """\
@ - id="book"
@ -- id="thm1" type="theorem"
Statement
@ -- id="prf1" type="proof" proves="thm1" deps=["thm1"]
Proof"""
        events = parse_annotations(text)
        td = TreeDict()
        process_batch_annotations(events, td, chunk_number=0, total_content_lines=5)

        assert td["thm1"].node_type == NodeType.THM
        prf = td["prf1"]
        assert prf.proves is not None
        assert prf.proves.id == "thm1"
        assert prf._dependency_ids == ["thm1"]


class TestCrossBatch:
    def test_resume_uses_derived_active_trace(self):
        text1 = """\
@ - id="book"
@ -- id="ch1"
Content batch 1"""
        events1 = parse_annotations(text1)
        td = TreeDict()
        r1 = process_batch_annotations(
            events1, td, chunk_number=0, total_content_lines=3
        )
        assert r1.active_depth == 2
        assert active_trace_ids(td) == ["book", "ch1"]

        text2 = """\
More content for ch1
@ -- id="ch2"
Ch2 content"""
        events2 = parse_annotations(text2)
        r2 = process_batch_annotations(
            events2, td, chunk_number=1, total_content_lines=3
        )

        assert r2.active_depth == 2
        assert active_trace_ids(td) == ["book", "ch2"]

        ch1 = td["ch1"]
        batch1_content = [
            c
            for c in ch1.content_list
            if isinstance(c, Content) and c.chunk_number == 1
        ]
        assert len(batch1_content) > 0

    def test_deeper_jump_attaches_to_active_node(self):
        td = TreeDict()
        process_batch_annotations(
            parse_annotations('@ - id="book"\n@ -- id="ch1"'),
            td,
            chunk_number=0,
            total_content_lines=2,
        )
        process_batch_annotations(
            parse_annotations('@ ---- id="lemma_x"'),
            td,
            chunk_number=1,
            total_content_lines=1,
        )

        assert td["lemma_x"].parent is td["ch1"]
