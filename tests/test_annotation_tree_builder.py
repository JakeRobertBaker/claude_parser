from claude_parser.domain.annotation_parser import parse_annotations
from claude_parser.domain.annotation_tree_builder import process_batch_annotations
from claude_parser.domain.content import Content
from claude_parser.domain.node import NodeType, TreeDict


class TestSingleBatch:
    def test_simple_tree(self):
        text = (
            '@ - id="root"\n'
            '@ -- id="ch1"\n'
            "Some content here\n"
            "More content\n"
            '@ -- id="ch2"'
        )
        events = parse_annotations(text)
        td = TreeDict()
        result = process_batch_annotations(
            events, td, [], chunk_number=0, total_content_lines=5
        )

        assert "root" in td._data
        assert "ch1" in td._data
        assert "ch2" in td._data
        assert td.root_node is not None
        assert td.root_node.id == "root"
        assert td["ch1"].parent is td["root"]
        assert td["ch2"].parent is td["root"]
        assert result.open_stack == ["root", "ch2"]

    def test_content_assigned(self):
        text = """\
@ - id="root"
Content line 1
Content line 2
<!-- cutoff -->"""
        events = parse_annotations(text)
        td = TreeDict()
        process_batch_annotations(events, td, [], chunk_number=0, total_content_lines=4)

        root = td["root"]
        assert len(root.content_list) == 1
        c = root.content_list[0]
        assert isinstance(c, Content)
        assert c.chunk_number == 0
        assert c.first_line == 2
        assert c.last_line == 3

    def test_node_types_proves_and_deps(self):
        text = """\
@ - id="root"
@ -- id="thm1" type="theorem"
Statement
@ -- id="prf1" type="proof" proves="thm1" deps=["thm1"]
Proof"""
        events = parse_annotations(text)
        td = TreeDict()
        process_batch_annotations(events, td, [], chunk_number=0, total_content_lines=5)

        assert td["thm1"].node_type == NodeType.THM
        prf = td["prf1"]
        assert prf.proves is not None
        assert prf.proves.id == "thm1"
        assert prf._dependency_ids == ["thm1"]


class TestCrossBatch:
    def test_open_stack_returned(self):
        text = """\
@ - id="root"
@ -- id="ch1"
Content that continues..."""
        events = parse_annotations(text)
        td = TreeDict()
        result = process_batch_annotations(
            events, td, [], chunk_number=0, total_content_lines=3
        )
        assert result.open_stack == ["root", "ch1"]

    def test_resume_from_open_stack(self):
        text1 = """\
@ - id="root"
@ -- id="ch1"
Content batch 1"""
        events1 = parse_annotations(text1)
        td = TreeDict()
        r1 = process_batch_annotations(
            events1, td, [], chunk_number=0, total_content_lines=3
        )
        assert r1.open_stack == ["root", "ch1"]

        text2 = """\
More content for ch1
@ -- id="ch2"
Ch2 content"""
        events2 = parse_annotations(text2, open_stack=r1.open_stack)
        r2 = process_batch_annotations(
            events2, td, r1.open_stack, chunk_number=1, total_content_lines=3
        )

        assert r2.open_stack == ["root", "ch2"]
        assert "ch1" in r2.closed_nodes
        assert "ch2" in r2.new_nodes

        ch1 = td["ch1"]
        batch1_content = [
            c
            for c in ch1.content_list
            if isinstance(c, Content) and c.chunk_number == 1
        ]
        assert len(batch1_content) > 0
