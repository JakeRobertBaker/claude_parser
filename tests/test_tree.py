import pytest
from content import Content
from tree import Node, NodeType, TreeDict


def make_tree_dict() -> TreeDict:
    return TreeDict()


def make_content(chunk: int, first: int, last: int) -> Content:
    return Content(chunk_number=chunk, first_line=first, last_line=last)


def make_node(
    id: str,
    node_dict: TreeDict,
    content_list: list[Content] | None = None,
    children: list[Node] | None = None,
    theory: bool = False,
    node_type: NodeType = NodeType.GENERIC,
) -> Node:
    return Node(
        id=id,
        title=id,
        children=children or [],
        content_list=content_list or [],
        node_type=node_type,
        theory=theory,
        node_dict=node_dict,
    )


class TestNodeConstruction:
    def test_attributes_set(self):
        td = make_tree_dict()
        n = make_node("n1", td, content_list=[make_content(0, 1, 10)])
        assert n.id == "n1"
        assert n.title == "n1"
        assert n.theory is False
        assert n.node_type == NodeType.GENERIC
        assert n.parent is None

    def test_registered_in_tree_dict(self):
        td = make_tree_dict()
        n = make_node("n1", td)
        assert td["n1"] is n

    def test_duplicate_id_raises(self):
        td = make_tree_dict()
        make_node("n1", td)
        with pytest.raises(ValueError):
            make_node("n1", td)


class TestContentBounds:
    def test_bounds_single_node(self):
        td = make_tree_dict()
        n = make_node("n1", td, content_list=[make_content(0, 5, 20)])
        lo, hi = n.content_bounds()
        assert lo == make_content(0, 5, 20)
        assert hi == make_content(0, 5, 20)

    def test_bounds_no_content(self):
        td = make_tree_dict()
        n = make_node("n1", td)
        lo, hi = n.content_bounds()
        assert lo is None
        assert hi is None

    def test_bounds_includes_children(self):
        td = make_tree_dict()
        child = make_node("child", td, content_list=[make_content(0, 51, 100)])
        parent = make_node("parent", td, content_list=[make_content(0, 1, 50)], children=[child])
        lo, hi = parent.content_bounds()
        assert lo == make_content(0, 1, 50)
        assert hi == make_content(0, 51, 100)

    def test_bounds_child_only_content(self):
        td = make_tree_dict()
        child = make_node("child", td, content_list=[make_content(0, 10, 20)])
        parent = make_node("parent", td, children=[child])
        lo, hi = parent.content_bounds()
        assert lo == make_content(0, 10, 20)
        assert hi == make_content(0, 10, 20)


class TestIsAfter:
    def test_is_after_true(self):
        td = make_tree_dict()
        a = make_node("a", td, content_list=[make_content(0, 50, 100)])
        b = make_node("b", td, content_list=[make_content(0, 1, 40)])
        assert a.is_after(b)

    def test_is_after_false(self):
        td = make_tree_dict()
        a = make_node("a", td, content_list=[make_content(0, 1, 40)])
        b = make_node("b", td, content_list=[make_content(0, 50, 100)])
        assert not a.is_after(b)

    def test_is_after_no_content_returns_false(self):
        td = make_tree_dict()
        a = make_node("a", td)
        b = make_node("b", td, content_list=[make_content(0, 1, 10)])
        assert not a.is_after(b)
        assert not b.is_after(a)


class TestIsBeforeContent:
    def test_is_before_true(self):
        td = make_tree_dict()
        n = make_node("n", td, content_list=[make_content(0, 1, 10)])
        bound = make_content(0, 20, 30)
        assert n.is_before_content(bound)

    def test_is_before_false(self):
        td = make_tree_dict()
        n = make_node("n", td, content_list=[make_content(0, 25, 40)])
        bound = make_content(0, 20, 30)
        assert not n.is_before_content(bound)

    def test_is_before_no_content_returns_false(self):
        td = make_tree_dict()
        n = make_node("n", td)
        bound = make_content(0, 20, 30)
        assert not n.is_before_content(bound)


class TestMaxSelfParentContent:
    def test_no_parent_no_content(self):
        td = make_tree_dict()
        n = make_node("n", td)
        assert n.max_self_parent_content() is None

    def test_self_content_only(self):
        td = make_tree_dict()
        n = make_node("n", td, content_list=[make_content(0, 1, 50)])
        assert n.max_self_parent_content() == make_content(0, 1, 50)

    def test_traverses_ancestors(self):
        td = make_tree_dict()
        child = make_node("child", td, content_list=[make_content(0, 51, 100)])
        parent = make_node("parent", td, content_list=[make_content(0, 1, 50)], children=[child])
        child._assign_parent(parent)
        # child's max_self_parent_content should include parent's max (chunk 0, line 1)
        # but parent max is line 1 which is less than child's own line 51
        result = child.max_self_parent_content()
        assert result == make_content(0, 51, 100)

    def test_ancestor_max_wins(self):
        td = make_tree_dict()
        grandchild = make_node("gc", td, content_list=[make_content(0, 51, 60)])
        child = make_node("child", td, children=[grandchild])
        parent = make_node("parent", td, content_list=[make_content(0, 1, 100)], children=[child])
        child._assign_parent(parent)
        grandchild._assign_parent(child)
        # grandchild has no own content > parent's max, parent max is line 1
        # max_self_parent_content for grandchild = max(gc content, parent max via child)
        result = grandchild.max_self_parent_content()
        assert result == make_content(0, 51, 60)


class TestAddChild:
    def test_add_child_wires_parent(self):
        td = make_tree_dict()
        parent = make_node("parent", td, content_list=[make_content(0, 1, 50)])
        child = make_node("child", td, content_list=[make_content(0, 51, 100)])
        parent.add_child(child)
        assert child in parent.children
        assert child.parent is parent

    def test_add_child_ordering_violation_raises(self):
        td = make_tree_dict()
        parent = make_node("parent", td, content_list=[make_content(0, 50, 100)])
        child = make_node("child", td, content_list=[make_content(0, 1, 40)])
        with pytest.raises(ValueError):
            parent.add_child(child)

    def test_add_child_no_parent_content_no_raise(self):
        td = make_tree_dict()
        parent = make_node("parent", td)
        child = make_node("child", td, content_list=[make_content(0, 1, 40)])
        parent.add_child(child)
        assert child in parent.children


class TestAssignParent:
    def test__assign_parent(self):
        td = make_tree_dict()
        parent = make_node("parent", td)
        child = make_node("child", td)
        child._assign_parent(parent)
        assert child.parent is parent

    def test_re_assign_parent_raises(self):
        td = make_tree_dict()
        p1 = make_node("p1", td)
        p2 = make_node("p2", td)
        child = make_node("child", td)
        child._assign_parent(p1)
        with pytest.raises(ValueError):
            child._assign_parent(p2)


class TestTreeDictValidate:
    def test_valid_tree_passes(self):
        td = make_tree_dict()
        child = make_node("child", td, content_list=[make_content(0, 51, 100)])
        parent = make_node("parent", td, content_list=[make_content(0, 1, 50)], children=[child])
        child._assign_parent(parent)
        td.set_root(parent)
        td.validate()  # should not raise

    def test_ordering_violation_raises(self):
        td = make_tree_dict()
        # child content is BEFORE parent content — violation
        child = make_node("child", td, content_list=[make_content(0, 1, 40)])
        parent = make_node("parent", td, content_list=[make_content(0, 50, 100)], children=[child])
        child._assign_parent(parent)
        td.set_root(parent)
        with pytest.raises(ValueError):
            td.validate()

    def test_no_content_skips_check(self):
        td = make_tree_dict()
        child = make_node("child", td, content_list=[make_content(0, 1, 10)])
        parent = make_node("parent", td, children=[child])
        child._assign_parent(parent)
        td.set_root(parent)
        td.validate()  # parent has no content — no bound to check against


class TestTreeDictSetRoot:
    def test_set_root(self):
        td = make_tree_dict()
        root = make_node("root", td)
        td.set_root(root)
        assert td.root_node is root

    def test_set_root_twice_raises(self):
        td = make_tree_dict()
        r1 = make_node("r1", td)
        td.set_root(r1)
        r2 = make_node("r2", td)
        with pytest.raises(ValueError):
            td.set_root(r2)


class TestDependencies:
    def test_dependency_resolved(self):
        td = make_tree_dict()
        dep = make_node("dep", td, theory=True, node_type=NodeType.DEF)
        n = Node(
            id="n", title="n", children=[], content_list=[],
            node_type=NodeType.GENERIC, theory=False,
            node_dict=td, dependency_ids=["dep"],
        )
        assert n.dependencies == [dep]

    def test_missing_dependency_raises(self):
        td = make_tree_dict()
        n = Node(
            id="n", title="n", children=[], content_list=[],
            node_type=NodeType.GENERIC, theory=False,
            node_dict=td, dependency_ids=["missing"],
        )
        with pytest.raises(KeyError):
            _ = n.dependencies
