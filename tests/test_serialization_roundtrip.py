import json
from claude_parser.adapters.chunk_lines.json_adapter import (
    tree_from_dict,
    tree_to_dict,
    content_to_dict,
    content_from_dict,
)
from claude_parser.adapters.chunk_lines.content import Content


class TestContentSerialization:
    def test_content_roundtrip(self):
        c = Content(chunk_number=3, first_line=10, last_line=50)
        d = content_to_dict(c)
        c2 = content_from_dict(d)
        assert c == c2

    def test_content_to_dict_keys(self):
        c = Content(chunk_number=0, first_line=1, last_line=10)
        d = content_to_dict(c)
        assert d == {"chunk_number": 0, "first_line": 1, "last_line": 10}


class TestTreeRoundtrip:
    def test_basic_tree_roundtrip(self):
        data = {
            "id": "root",
            "title": "Root",
            "children": [
                {
                    "id": "ch01",
                    "title": "Chapter 1",
                    "content": [
                        {"chunk_number": 0, "first_line": 1, "last_line": 50}
                    ],
                    "children": [
                        {
                            "id": "def:metric",
                            "title": "Metric Space",
                            "node_type": "definition",
                            "theory": True,
                            "content": [
                                {"chunk_number": 0, "first_line": 51, "last_line": 80}
                            ],
                            "dependencies": ["def:set"],
                        }
                    ],
                },
                {
                    "id": "ch02",
                    "title": "Chapter 2",
                    "content": [
                        {"chunk_number": 1, "first_line": 1, "last_line": 80}
                    ],
                },
            ],
        }

        root, td = tree_from_dict(data)
        output = tree_to_dict(root)

        # Roundtrip: deserialize output again and verify structure
        root2, td2 = tree_from_dict(output)
        assert len(td2) == len(td)
        assert root2.id == "root"
        assert root2.children[0].id == "ch01"
        assert root2.children[0].children[0].id == "def:metric"
        assert root2.children[0].children[0].theory is True
        assert root2.children[0].children[0]._dependencies == ["def:set"]
        assert root2.children[1].id == "ch02"

    def test_empty_tree_roundtrip(self):
        data = {"id": "root", "title": "Root"}
        root, td = tree_from_dict(data)
        output = tree_to_dict(root)
        root2, td2 = tree_from_dict(output)
        assert root2.id == "root"
        assert root2.children == []
        assert root2.content_list == []

    def test_skeleton_nodes_roundtrip(self):
        """Phase 0 skeleton: nodes with no content."""
        data = {
            "id": "root",
            "title": "Root",
            "children": [
                {"id": "ch01", "title": "Chapter 1"},
                {"id": "ch02", "title": "Chapter 2"},
            ],
        }
        root, _ = tree_from_dict(data)
        output = tree_to_dict(root)
        root2, _ = tree_from_dict(output)
        assert len(root2.children) == 2
        assert root2.children[0].content_list == []

    def test_roundtrip_is_json_serializable(self):
        data = {
            "id": "root",
            "title": "Root",
            "children": [
                {
                    "id": "ch01",
                    "title": "Ch 1",
                    "content": [
                        {"chunk_number": 0, "first_line": 1, "last_line": 10}
                    ],
                }
            ],
        }
        root, _ = tree_from_dict(data)
        output = tree_to_dict(root)
        # Must be JSON-serializable
        json_str = json.dumps(output)
        reparsed = json.loads(json_str)
        root2, _ = tree_from_dict(reparsed)
        assert root2.children[0].id == "ch01"
