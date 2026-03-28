import pytest
from claude_parser.adapters.chunk_lines.content import Content
from claude_parser.application.merge import (
    build_dependency_report,
    check_duplicate_ids,
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
    theory: bool = False,
    node_type: NodeType = NodeType.GENERIC,
    dependency_ids: list[str] | None = None,
) -> Node:
    return Node(
        id=id,
        title=id,
        children=children or [],
        content_list=content_list or [],
        node_type=node_type,
        theory=theory,
        node_dict=node_dict,
        dependency_ids=dependency_ids,
    )


class TestValidateMetadata:
    def test_valid_metadata(self):
        meta = {
            "chunk_id": "chunk_000",
            "cutoff_line": 100,
            "section_node_id": "sec01_01",
            "new_nodes": [],
        }
        assert validate_metadata(meta) is None

    def test_missing_chunk_id(self):
        meta = {"cutoff_line": 100, "section_node_id": "x", "new_nodes": []}
        result = validate_metadata(meta)
        assert result is not None and "chunk_id" in result

    def test_missing_cutoff_line(self):
        meta = {"chunk_id": "x", "section_node_id": "x", "new_nodes": []}
        result = validate_metadata(meta)
        assert result is not None and "cutoff_line" in result

    def test_invalid_node_type(self):
        meta = {
            "chunk_id": "chunk_000",
            "cutoff_line": 100,
            "section_node_id": "sec",
            "new_nodes": [
                {"id": "x", "title": "X", "parent_id": "sec", "node_type": "banana"}
            ],
        }
        result = validate_metadata(meta)
        assert result is not None and "banana" in result

    def test_new_node_missing_id(self):
        meta = {
            "chunk_id": "chunk_000",
            "cutoff_line": 100,
            "section_node_id": "sec",
            "new_nodes": [{"title": "X", "parent_id": "sec"}],
        }
        result = validate_metadata(meta)
        assert result is not None and "missing 'id'" in result


class TestCheckDuplicateIds:
    def test_no_duplicates(self):
        td = make_tree_dict()
        make_node("root", td)
        meta = {"new_nodes": [{"id": "new1"}, {"id": "new2"}]}
        assert check_duplicate_ids(td, meta) == []

    def test_detects_duplicate(self):
        td = make_tree_dict()
        make_node("root", td)
        make_node("existing", td)
        meta = {"new_nodes": [{"id": "existing"}, {"id": "new1"}]}
        assert check_duplicate_ids(td, meta) == ["existing"]


class TestMergeChunk:
    def test_add_section_content(self):
        td = make_tree_dict()
        root = make_node("root", td)
        td.set_root(root)
        sec = make_node("sec01", td)
        root.add_child(sec)

        metadata = {
            "section_node_id": "sec01",
            "section_content": [{"first_line": 1, "last_line": 50}],
            "new_nodes": [],
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
            "section_node_id": "sec01",
            "section_content": [{"first_line": 1, "last_line": 30}],
            "new_nodes": [
                {
                    "id": "def:vector_space",
                    "title": "Vector Space",
                    "node_type": "definition",
                    "parent_id": "sec01",
                    "content": [{"first_line": 31, "last_line": 55}],
                    "dependencies": [],
                }
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
            "section_node_id": "sec01",
            "section_content": [{"first_line": 1, "last_line": 10}],
            "new_nodes": [
                {
                    "id": "def:field",
                    "title": "Field",
                    "node_type": "definition",
                    "parent_id": "sec01",
                    "content": [{"first_line": 11, "last_line": 30}],
                    "dependencies": [],
                },
                {
                    "id": "eg:field_examples",
                    "title": "Field Examples",
                    "node_type": "example",
                    "parent_id": "sec01",
                    "content": [{"first_line": 31, "last_line": 50}],
                    "dependencies": ["def:field"],
                },
            ],
        }
        merge_chunk(td, root, metadata, chunk_number=0)
        assert len(sec.children) == 2

    def test_merge_raises_on_missing_section_node(self):
        td = make_tree_dict()
        root = make_node("root", td)
        td.set_root(root)

        metadata = {
            "section_node_id": "nonexistent",
            "section_content": [],
            "new_nodes": [],
        }
        with pytest.raises(KeyError):
            merge_chunk(td, root, metadata, chunk_number=0)


class TestDependencyReport:
    def test_all_resolved(self):
        td = make_tree_dict()
        root = make_node("root", td)
        td.set_root(root)
        make_node("def:a", td, theory=True, node_type=NodeType.DEF)
        make_node(
            "thm:b", td, theory=True, node_type=NodeType.THM,
            dependency_ids=["def:a"],
        )
        report = build_dependency_report(td)
        assert report["unresolved_dependencies"] == []

    def test_unresolved(self):
        td = make_tree_dict()
        root = make_node("root", td)
        td.set_root(root)
        make_node(
            "thm:b", td, theory=True, node_type=NodeType.THM,
            dependency_ids=["def:missing"],
        )
        report = build_dependency_report(td)
        assert len(report["unresolved_dependencies"]) == 1
        assert report["unresolved_dependencies"][0]["missing_dep"] == "def:missing"

    def test_zero_deps_flagged(self):
        td = make_tree_dict()
        root = make_node("root", td)
        td.set_root(root)
        make_node("def:a", td, theory=True, node_type=NodeType.DEF)
        report = build_dependency_report(td)
        assert "def:a" in report["theory_nodes_with_zero_dependencies"]
