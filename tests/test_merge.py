import pytest
from claude_parser.domain.content import Content
from claude_parser.application.merge import (
    build_dependency_report,
    check_intra_duplicates,
    merge_chunk,
    validate_metadata,
)
from claude_parser.domain.node import Node, NodeType, TreeDict


def make_tree_dict() -> TreeDict:
    return TreeDict()


def make_node(
    id: str,
    node_dict: TreeDict,
    content_list: list[Content] | None = None,
    children: list[Node] | None = None,
    node_type: NodeType = NodeType.GENERIC,
    dependency_ids: list[str] | None = None,
) -> Node:
    return Node(
        id=id,
        title=id,
        children=children or [],
        content_list=content_list or [],
        node_type=node_type,
        node_dict=node_dict,
        dependency_ids=dependency_ids,
    )


class TestValidateMetadata:
    def test_valid_metadata(self):
        meta = {
            "chunk_id": "chunk_000",
            "cutoff_line": 100,
            "nodes": [],
        }
        assert validate_metadata(meta) is None

    def test_valid_metadata_with_nodes(self):
        meta = {
            "chunk_id": "chunk_000",
            "cutoff_line": 100,
            "nodes": [
                {"id": "sec01", "title": "Section 1", "content": [{"first_line": 1, "last_line": 50}]},
                {"id": "def:1_5_x", "title": "Def 1.5", "node_type": "definition", "parent_id": "sec01"},
            ],
        }
        assert validate_metadata(meta) is None

    def test_missing_chunk_id(self):
        meta = {"cutoff_line": 100, "nodes": []}
        result = validate_metadata(meta)
        assert result is not None and "chunk_id" in result

    def test_missing_cutoff_line(self):
        meta = {"chunk_id": "x", "nodes": []}
        result = validate_metadata(meta)
        assert result is not None and "cutoff_line" in result

    def test_missing_nodes(self):
        meta = {"chunk_id": "x", "cutoff_line": 100}
        result = validate_metadata(meta)
        assert result is not None and "nodes" in result

    def test_nodes_not_list(self):
        meta = {"chunk_id": "x", "cutoff_line": 100, "nodes": "bad"}
        result = validate_metadata(meta)
        assert result is not None and "list" in result

    def test_invalid_node_type(self):
        meta = {
            "chunk_id": "chunk_000",
            "cutoff_line": 100,
            "nodes": [
                {"id": "x", "title": "X", "node_type": "banana"}
            ],
        }
        result = validate_metadata(meta)
        assert result is not None and "banana" in result

    def test_node_missing_id(self):
        meta = {
            "chunk_id": "chunk_000",
            "cutoff_line": 100,
            "nodes": [{"title": "X"}],
        }
        result = validate_metadata(meta)
        assert result is not None and "missing 'id'" in result

    def test_node_missing_title(self):
        meta = {
            "chunk_id": "chunk_000",
            "cutoff_line": 100,
            "nodes": [{"id": "x"}],
        }
        result = validate_metadata(meta)
        assert result is not None and "missing 'title'" in result


class TestCheckIntraDuplicates:
    def test_no_duplicates(self):
        meta = {"nodes": [{"id": "a"}, {"id": "b"}]}
        assert check_intra_duplicates(meta) == []

    def test_detects_intra_duplicate(self):
        meta = {"nodes": [{"id": "a"}, {"id": "b"}, {"id": "a"}]}
        assert check_intra_duplicates(meta) == ["a"]

    def test_empty_nodes(self):
        meta = {"nodes": []}
        assert check_intra_duplicates(meta) == []


class TestMergeChunk:
    def test_add_content_to_existing_node(self):
        td = make_tree_dict()
        root = make_node("root", td)
        td.set_root(root)
        sec = make_node("sec01", td)
        root.add_child(sec)

        metadata = {
            "nodes": [
                {"id": "sec01", "title": "Section 1",
                 "content": [{"first_line": 1, "last_line": 50}]},
            ],
        }
        merge_chunk(td, root, metadata, chunk_number=0)
        assert len(sec.content_list) == 1
        content = sec.content_list[0]
        assert isinstance(content, Content)
        assert content.chunk_number == 0
        assert content.first_line == 1

    def test_create_theory_child(self):
        td = make_tree_dict()
        root = make_node("root", td)
        td.set_root(root)
        sec = make_node("sec01", td)
        root.add_child(sec)

        metadata = {
            "nodes": [
                {"id": "sec01", "title": "Section 1",
                 "content": [{"first_line": 1, "last_line": 30}]},
                {"id": "def:vector_space", "title": "Vector Space",
                 "node_type": "definition", "parent_id": "sec01",
                 "content": [{"first_line": 31, "last_line": 55}],
                 "dependencies": []},
            ],
        }
        merge_chunk(td, root, metadata, chunk_number=0)

        assert "def:vector_space" in td._data
        defn = td["def:vector_space"]
        assert defn.theory is True
        assert defn.node_type == NodeType.DEF
        assert defn.parent is sec

    def test_create_multiple_nodes(self):
        td = make_tree_dict()
        root = make_node("root", td)
        td.set_root(root)
        sec = make_node("sec01", td)
        root.add_child(sec)

        metadata = {
            "nodes": [
                {"id": "sec01_preamble", "title": "Preamble",
                 "node_type": "generic", "parent_id": "sec01",
                 "content": [{"first_line": 1, "last_line": 30}]},
                {"id": "def:field", "title": "Field",
                 "node_type": "definition", "parent_id": "sec01",
                 "content": [{"first_line": 31, "last_line": 50}],
                 "dependencies": []},
                {"id": "eg:field_examples", "title": "Field Examples",
                 "node_type": "example", "parent_id": "sec01",
                 "content": [{"first_line": 51, "last_line": 70}],
                 "dependencies": ["def:field"]},
            ],
        }
        merge_chunk(td, root, metadata, chunk_number=0)
        assert len(sec.children) == 3

    def test_new_node_referencing_new_parent(self):
        td = make_tree_dict()
        root = make_node("root", td)
        td.set_root(root)
        sec = make_node("sec01", td)
        root.add_child(sec)

        metadata = {
            "nodes": [
                {"id": "sec01_discussion", "title": "Discussion",
                 "node_type": "generic", "parent_id": "sec01",
                 "content": []},
                {"id": "def:x", "title": "Def X",
                 "node_type": "definition", "parent_id": "sec01_discussion",
                 "content": [{"first_line": 1, "last_line": 10}]},
            ],
        }
        merge_chunk(td, root, metadata, chunk_number=0)
        assert "sec01_discussion" in td._data
        assert "def:x" in td._data
        assert td["def:x"].parent is td["sec01_discussion"]

    def test_new_node_missing_parent_id_raises(self):
        td = make_tree_dict()
        root = make_node("root", td)
        td.set_root(root)

        metadata = {
            "nodes": [
                {"id": "orphan", "title": "Orphan",
                 "content": [{"first_line": 1, "last_line": 10}]},
            ],
        }
        with pytest.raises(ValueError, match="missing required 'parent_id'"):
            merge_chunk(td, root, metadata, chunk_number=0)

    def test_merge_raises_on_missing_parent(self):
        td = make_tree_dict()
        root = make_node("root", td)
        td.set_root(root)

        metadata = {
            "nodes": [
                {"id": "orphan", "title": "Orphan",
                 "parent_id": "nonexistent",
                 "content": [{"first_line": 1, "last_line": 10}]},
            ],
        }
        with pytest.raises(KeyError):
            merge_chunk(td, root, metadata, chunk_number=0)

    def test_existing_node_no_content(self):
        """Existing node listed with no content — no-op, no error."""
        td = make_tree_dict()
        root = make_node("root", td)
        td.set_root(root)
        sec = make_node("sec01", td)
        root.add_child(sec)

        metadata = {
            "nodes": [
                {"id": "sec01", "title": "Section 1"},
            ],
        }
        merge_chunk(td, root, metadata, chunk_number=0)
        assert len(sec.content_list) == 0


class TestDependencyReport:
    def test_all_resolved(self):
        td = make_tree_dict()
        root = make_node("root", td)
        td.set_root(root)
        make_node("def:a", td, node_type=NodeType.DEF)
        make_node(
            "thm:b", td, node_type=NodeType.THM,
            dependency_ids=["def:a"],
        )
        report = build_dependency_report(td)
        assert report["unresolved_dependencies"] == []

    def test_unresolved(self):
        td = make_tree_dict()
        root = make_node("root", td)
        td.set_root(root)
        make_node(
            "thm:b", td, node_type=NodeType.THM,
            dependency_ids=["def:missing"],
        )
        report = build_dependency_report(td)
        assert len(report["unresolved_dependencies"]) == 1
        assert report["unresolved_dependencies"][0]["missing_dep"] == "def:missing"

    def test_zero_deps_flagged(self):
        td = make_tree_dict()
        root = make_node("root", td)
        td.set_root(root)
        make_node("def:a", td, node_type=NodeType.DEF)
        report = build_dependency_report(td)
        assert "def:a" in report["theory_nodes_with_zero_dependencies"]
