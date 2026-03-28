import json
import pytest
from pathlib import Path
from content import Content
from tree import NodeType, TreeDict
from adapters.json_adapter import tree_from_dict, node_from_dict

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict:
    with open(FIXTURES / name) as f:
        return json.load(f)


class TestTreeFromDict:
    def test_node_count(self):
        data = load_fixture("basic_tree.json")
        root, td = tree_from_dict(data)
        # root, ch01, sec01_01, def_metric, ch02 = 5 nodes
        assert len(td) == 5

    def test_root_is_set(self):
        data = load_fixture("basic_tree.json")
        root, td = tree_from_dict(data)
        assert td.root_node is root
        assert root.id == "root"

    def test_root_has_two_children(self):
        data = load_fixture("basic_tree.json")
        root, td = tree_from_dict(data)
        assert len(root.children) == 2
        assert root.children[0].id == "ch01"
        assert root.children[1].id == "ch02"

    def test_parent_references_set(self):
        data = load_fixture("basic_tree.json")
        root, td = tree_from_dict(data)
        ch01 = td["ch01"]
        sec01_01 = td["sec01_01"]
        assert ch01.parent is root
        assert sec01_01.parent is ch01

    def test_content_parsed(self):
        data = load_fixture("basic_tree.json")
        _, td = tree_from_dict(data)
        ch01 = td["ch01"]
        assert len(ch01.content_list) == 1
        c = ch01.content_list[0]
        assert c.chunk_number == 0
        assert c.first_line == 1
        assert c.last_line == 50

    def test_node_type_parsed(self):
        data = load_fixture("basic_tree.json")
        _, td = tree_from_dict(data)
        assert td["def_metric"].node_type == NodeType.DEF

    def test_theory_flag_parsed(self):
        data = load_fixture("basic_tree.json")
        _, td = tree_from_dict(data)
        assert td["def_metric"].theory is True
        assert td["ch01"].theory is False

    def test_fixture_constructs_without_error(self):
        data = load_fixture("basic_tree.json")
        _, td = tree_from_dict(data)  # validation happens during construction

    def test_root_no_content(self):
        data = load_fixture("basic_tree.json")
        root, _ = tree_from_dict(data)
        assert root.content_list == []


class TestValidationDuringConstruction:
    def test_parent_after_child_raises(self):
        data = load_fixture("invalid_ordering.json")
        with pytest.raises(ValueError):
            tree_from_dict(data)

    def test_sibling_interleaving_raises(self):
        # s1 span: min=1, max=10; s2 span: min=5, max=15 — interleave
        data = {
            "id": "root", "title": "Root",
            "content": [], "dependencies": [], "children": [
                {
                    "id": "s1", "title": "S1",
                    "content": [
                        {"chunk_number": 0, "first_line": 1, "last_line": 2},
                        {"chunk_number": 0, "first_line": 10, "last_line": 11}
                    ],
                    "dependencies": [], "children": []
                },
                {
                    "id": "s2", "title": "S2",
                    "content": [
                        {"chunk_number": 0, "first_line": 5, "last_line": 6},
                        {"chunk_number": 0, "first_line": 15, "last_line": 16}
                    ],
                    "dependencies": [], "children": []
                }
            ]
        }
        with pytest.raises(ValueError):
            tree_from_dict(data)


class TestDefaultFields:
    def test_missing_node_type_defaults_to_generic(self):
        data = {
            "id": "n1", "title": "N1",
            "content": [], "dependencies": [], "children": []
        }
        td = TreeDict()
        node = node_from_dict(data, td)
        assert node.node_type == NodeType.GENERIC

    def test_missing_theory_defaults_to_false(self):
        data = {
            "id": "n1", "title": "N1",
            "content": [], "dependencies": [], "children": []
        }
        td = TreeDict()
        node = node_from_dict(data, td)
        assert node.theory is False
