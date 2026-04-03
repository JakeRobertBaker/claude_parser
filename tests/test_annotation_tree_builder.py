from claude_parser.domain.annotation_parser import parse_annotations
from claude_parser.domain.annotation_tree_builder import (
    process_batch_annotations,
)
from claude_parser.domain.content import Content
from claude_parser.domain.node import NodeType, TreeDict


class TestSingleBatch:
    def test_simple_tree(self):
        text = """\
<!-- tree:start id="root" title="Root" -->
<!-- tree:start id="ch1" title="Chapter 1" -->
Some content here
More content
<!-- tree:end id="ch1" -->
<!-- tree:end id="root" -->"""
        events = parse_annotations(text)
        td = TreeDict()
        result = process_batch_annotations(events, td, [], chunk_number=0, total_content_lines=6)

        assert "root" in td._data
        assert "ch1" in td._data
        assert td.root_node is not None
        assert td.root_node.id == "root"
        assert td["ch1"].parent is td["root"]
        assert result.open_stack == []
        assert set(result.new_nodes) == {"root", "ch1"}

    def test_content_assigned(self):
        text = """\
<!-- tree:start id="root" title="Root" -->
Content line 1
Content line 2
<!-- tree:end id="root" -->"""
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

    def test_nested_content(self):
        text = """\
<!-- tree:start id="root" title="Root" -->
Root preamble
<!-- tree:start id="child" title="Child" -->
Child content
<!-- tree:end id="child" -->
<!-- tree:end id="root" -->"""
        events = parse_annotations(text)
        td = TreeDict()
        process_batch_annotations(events, td, [], chunk_number=0, total_content_lines=6)

        root = td["root"]
        child = td["child"]
        rc = root.content_list[0]
        cc = child.content_list[0]
        assert isinstance(rc, Content)
        assert isinstance(cc, Content)
        assert len(root.content_list) == 1
        assert rc.first_line == 2
        assert rc.last_line == 2
        assert len(child.content_list) == 1
        assert cc.first_line == 4
        assert cc.last_line == 4

    def test_node_types(self):
        text = """\
<!-- tree:start id="root" title="Root" -->
<!-- tree:start id="thm1" type="theorem" title="Theorem 1" -->
Statement
<!-- tree:end id="thm1" -->
<!-- tree:end id="root" -->"""
        events = parse_annotations(text)
        td = TreeDict()
        process_batch_annotations(events, td, [], chunk_number=0, total_content_lines=5)

        assert td["thm1"].node_type == NodeType.THM
        assert td["root"].node_type == NodeType.GENERIC

    def test_proves_and_dependencies(self):
        text = """\
<!-- tree:start id="root" title="Root" -->
<!-- tree:start id="thm1" type="theorem" title="Thm 1" -->
Statement
<!-- tree:end id="thm1" -->
<!-- tree:start id="prf1" type="proof" proves="thm1" dependencies="thm1" title="Proof" -->
Proof
<!-- tree:end id="prf1" -->
<!-- tree:end id="root" -->"""
        events = parse_annotations(text)
        td = TreeDict()
        process_batch_annotations(events, td, [], chunk_number=0, total_content_lines=8)

        prf = td["prf1"]
        assert prf.proves is not None
        assert prf.proves.id == "thm1"
        assert prf._dependency_ids == ["thm1"]


class TestCrossBatch:
    def test_open_stack_returned(self):
        """A node started but not closed goes onto open_stack."""
        text = """\
<!-- tree:start id="root" title="Root" -->
<!-- tree:start id="ch1" title="Chapter 1" -->
Content that continues..."""
        events = parse_annotations(text)
        td = TreeDict()
        result = process_batch_annotations(events, td, [], chunk_number=0, total_content_lines=3)

        assert result.open_stack == ["root", "ch1"]
        assert "root" in result.new_nodes
        assert "ch1" in result.new_nodes

    def test_resume_from_open_stack(self):
        """Second batch closes nodes that were left open."""
        # First batch: start root and ch1
        text1 = """\
<!-- tree:start id="root" title="Root" -->
<!-- tree:start id="ch1" title="Chapter 1" -->
Content batch 1"""
        events1 = parse_annotations(text1)
        td = TreeDict()
        r1 = process_batch_annotations(events1, td, [], chunk_number=0, total_content_lines=3)
        assert r1.open_stack == ["root", "ch1"]

        # Second batch: close ch1, add ch2, close root
        text2 = """\
More content for ch1
<!-- tree:end id="ch1" -->
<!-- tree:start id="ch2" title="Chapter 2" -->
Ch2 content
<!-- tree:end id="ch2" -->
<!-- tree:end id="root" -->"""
        events2 = parse_annotations(text2)
        r2 = process_batch_annotations(events2, td, r1.open_stack, chunk_number=1, total_content_lines=6)

        assert r2.open_stack == []
        assert "ch1" in r2.closed_nodes
        assert "ch2" in r2.new_nodes
        assert "ch2" in r2.closed_nodes
        # ch1 gets content from batch 2
        ch1 = td["ch1"]
        batch1_content = [c for c in ch1.content_list if isinstance(c, Content) and c.chunk_number == 1]
        assert len(batch1_content) > 0

    def test_content_assigned_to_open_stack_node(self):
        """Content before any annotation goes to the top of the open stack."""
        # Batch 1: start node
        text1 = "<!-- tree:start id=\"root\" title=\"Root\" -->\n<!-- tree:start id=\"n1\" title=\"N1\" -->\nContent"
        events1 = parse_annotations(text1)
        td = TreeDict()
        r1 = process_batch_annotations(events1, td, [], chunk_number=0, total_content_lines=3)

        # Batch 2: content then close
        text2 = "Continued content\n<!-- tree:end id=\"n1\" -->\n<!-- tree:end id=\"root\" -->"
        events2 = parse_annotations(text2)
        process_batch_annotations(events2, td, r1.open_stack, chunk_number=1, total_content_lines=3)

        n1 = td["n1"]
        # Should have content from both batches
        assert len(n1.content_list) == 2
        c0, c1 = n1.content_list
        assert isinstance(c0, Content) and c0.chunk_number == 0
        assert isinstance(c1, Content) and c1.chunk_number == 1


class TestCutoff:
    def test_cutoff_stops_processing(self):
        text = """\
<!-- tree:start id="root" title="Root" -->
Content before cutoff
<!-- cutoff -->
Raw unchanged text
More raw text"""
        events = parse_annotations(text)
        td = TreeDict()
        result = process_batch_annotations(events, td, [], chunk_number=0, total_content_lines=5)

        root = td["root"]
        assert len(root.content_list) == 1
        c = root.content_list[0]
        assert isinstance(c, Content)
        assert c.first_line == 2
        assert c.last_line == 2
        assert result.open_stack == ["root"]


class TestEdgeCases:
    def test_empty_events(self):
        td = TreeDict()
        result = process_batch_annotations([], td, [], chunk_number=0, total_content_lines=0)
        assert result.new_nodes == []
        assert result.open_stack == []

    def test_multiple_children(self):
        text = """\
<!-- tree:start id="root" title="Root" -->
<!-- tree:start id="a" title="A" -->
A content
<!-- tree:end id="a" -->
<!-- tree:start id="b" title="B" -->
B content
<!-- tree:end id="b" -->
<!-- tree:end id="root" -->"""
        events = parse_annotations(text)
        td = TreeDict()
        process_batch_annotations(events, td, [], chunk_number=0, total_content_lines=8)

        root = td["root"]
        assert len(root.children) == 2
        assert root.children[0].id == "a"
        assert root.children[1].id == "b"
