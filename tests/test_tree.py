import pytest
from claude_parser.domain.content import Content
from claude_parser.domain.node import Node, NodeType, TreeDict


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
        bound = n.content_bound()
        assert bound is not None
        assert bound.lower == make_content(0, 5, 20)
        assert bound.upper == make_content(0, 5, 20)

    def test_bounds_no_content(self):
        td = make_tree_dict()
        n = make_node("n1", td)
        assert n.content_bound() is None

    def test_bounds_includes_children(self):
        td = make_tree_dict()
        child = make_node("child", td, content_list=[make_content(0, 51, 100)])
        parent = make_node(
            "parent", td, content_list=[make_content(0, 1, 50)], children=[child]
        )
        bound = parent.content_bound()
        assert bound is not None
        assert bound.lower == make_content(0, 1, 50)
        assert bound.upper == make_content(0, 51, 100)

    def test_bounds_child_only_content(self):
        td = make_tree_dict()
        child = make_node("child", td, content_list=[make_content(0, 10, 20)])
        parent = make_node("parent", td, children=[child])
        bound = parent.content_bound()
        assert bound is not None
        assert bound.lower == make_content(0, 10, 20)
        assert bound.upper == make_content(0, 10, 20)


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


class TestIsAfterContent:
    def test_is_after_true(self):
        td = make_tree_dict()
        n = make_node("n", td, content_list=[make_content(0, 20, 30)])
        bound = make_content(0, 10, 15)
        assert n.is_after_content(bound)

    def test_is_after_false(self):
        td = make_tree_dict()
        n = make_node("n", td, content_list=[make_content(0, 5, 10)])
        bound = make_content(0, 20, 30)
        assert not n.is_after_content(bound)

    def test_is_after_no_content_returns_false(self):
        td = make_tree_dict()
        n = make_node("n", td)
        bound = make_content(0, 1, 10)
        assert not n.is_after_content(bound)

    def test_interleaving_not_after(self):
        td = make_tree_dict()
        # node span min=5 is before bound first_line=10 → not after
        n = make_node("n", td, content_list=[make_content(0, 5, 50)])
        bound = make_content(0, 10, 20)
        assert not n.is_after_content(bound)


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


class TestMaxAncestorContent:
    def test_no_parent_no_content(self):
        td = make_tree_dict()
        n = make_node("n", td)
        assert n.max_ancestor_content() is None

    def test_self_content_only(self):
        td = make_tree_dict()
        n = make_node("n", td, content_list=[make_content(0, 1, 50)])
        assert n.max_ancestor_content() == make_content(0, 1, 50)

    def test_traverses_ancestors(self):
        td = make_tree_dict()
        child = make_node("child", td, content_list=[make_content(0, 51, 100)])
        _parent = make_node(
            "parent", td, content_list=[make_content(0, 1, 50)], children=[child]
        )
        result = child.max_ancestor_content()
        assert result == make_content(0, 51, 100)

    def test_ancestor_max_wins(self):
        td = make_tree_dict()
        grandchild = make_node("gc", td, content_list=[make_content(0, 51, 60)])
        child = make_node("child", td, children=[grandchild])
        _parent = make_node(
            "parent", td, content_list=[make_content(0, 1, 100)], children=[child]
        )
        result = grandchild.max_ancestor_content()
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

    def test_add_contentless_child_to_node_with_content(self):
        """Contentless structural child allowed on a node with content."""
        td = make_tree_dict()
        parent = make_node("parent", td, content_list=[make_content(0, 1, 50)])
        child = make_node("child", td)
        parent.add_child(child)
        assert child in parent.children
        assert child.parent is parent

    def test_add_contentless_grandchild_under_ancestor_with_content(self):
        """Contentless node added as grandchild where grandparent has content."""
        td = make_tree_dict()
        grandparent = make_node("gp", td, content_list=[make_content(0, 1, 50)])
        parent = make_node("parent", td, content_list=[make_content(0, 51, 100)])
        grandparent.add_child(parent)
        empty = make_node("empty", td)
        parent.add_child(empty)
        assert empty in parent.children

    def test_add_child_sibling_interleaving_raises(self):
        # s1 span: min=1, max=10; s2 span: min=5, max=15 — interleave
        td = make_tree_dict()
        parent = make_node("parent", td)
        s1 = make_node(
            "s1", td, content_list=[make_content(0, 1, 2), make_content(0, 10, 11)]
        )
        s2 = make_node(
            "s2", td, content_list=[make_content(0, 5, 6), make_content(0, 15, 16)]
        )
        parent.add_child(s1)
        with pytest.raises(ValueError):
            parent.add_child(s2)

    def test_add_child_out_of_order_insertion_succeeds(self):
        td = make_tree_dict()
        parent = make_node("parent", td)
        s1 = make_node("s1", td, content_list=[make_content(0, 1, 2)])
        s2 = make_node("s2", td, content_list=[make_content(0, 5, 6)])
        s3 = make_node("s3", td, content_list=[make_content(0, 3, 4)])
        parent.add_child(s1)
        parent.add_child(s2)
        parent.add_child(s3)  # inserted between s1 and s2 — should succeed
        assert len(parent.children) == 3


class TestRule2Propagation:
    """
    Tests for rule 2 checking that propagates upward when adding a child
    grows a parent's content span.
    """

    def test_plan_example_section_in_wrong_chapter(self):
        """
        plan.md example: Root -> Ch1, Ch2, Ch3 with sections.
        Adding sec 3.5 to Ch1 makes Ch1 span (1.1, 3.5) which interleaves
        with Ch2 span (2.1, 2.1) and Ch3 span (3.1, 3.2).
        """
        td = make_tree_dict()
        # Build chapters with sections
        sec_1_1 = make_node("s1.1", td, content_list=[make_content(0, 11, 12)])
        sec_1_2 = make_node("s1.2", td, content_list=[make_content(0, 13, 14)])
        ch1 = make_node("ch1", td, children=[sec_1_1, sec_1_2])

        sec_2_1 = make_node("s2.1", td, content_list=[make_content(0, 21, 22)])
        ch2 = make_node("ch2", td, children=[sec_2_1])

        sec_3_1 = make_node("s3.1", td, content_list=[make_content(0, 31, 32)])
        sec_3_2 = make_node("s3.2", td, content_list=[make_content(0, 33, 34)])
        ch3 = make_node("ch3", td, children=[sec_3_1, sec_3_2])

        _root = make_node("root", td, children=[ch1, ch2, ch3])

        # Adding sec 3.5 content to ch1 — locally fine among ch1's children,
        # but makes ch1 span interleave with ch2 and ch3
        sec_3_5 = make_node("s3.5", td, content_list=[make_content(0, 35, 36)])
        with pytest.raises(ValueError):
            ch1.add_child(sec_3_5)

    def test_propagation_valid_no_span_growth(self):
        """
        Adding a child whose content is within the parent's existing span
        does not grow the span — no propagation needed.
        """
        td = make_tree_dict()
        sec_a = make_node("sa", td, content_list=[make_content(0, 1, 10)])
        sec_c = make_node("sc", td, content_list=[make_content(0, 21, 30)])
        ch1 = make_node("ch1", td, children=[sec_a, sec_c])

        sec_x = make_node("sx", td, content_list=[make_content(0, 31, 40)])
        ch2 = make_node("ch2", td, children=[sec_x])

        _root = make_node("root", td, children=[ch1, ch2])

        # New child fits within ch1's existing span — no growth
        sec_b = make_node("sb", td, content_list=[make_content(0, 11, 20)])
        ch1.add_child(sec_b)  # should succeed
        assert sec_b in ch1.children

    def test_propagation_span_grows_but_still_valid(self):
        """
        Adding a child grows the parent's span, but the new span
        still doesn't interleave with siblings at the grandparent level.
        """
        td = make_tree_dict()
        sec_a = make_node("sa", td, content_list=[make_content(0, 1, 10)])
        ch1 = make_node("ch1", td, children=[sec_a])

        sec_x = make_node("sx", td, content_list=[make_content(0, 31, 40)])
        ch2 = make_node("ch2", td, children=[sec_x])

        _root = make_node("root", td, children=[ch1, ch2])

        # Grows ch1 span from (1,10) to (1,20) — still before ch2 (31,40)
        sec_b = make_node("sb", td, content_list=[make_content(0, 11, 20)])
        ch1.add_child(sec_b)  # should succeed
        assert sec_b in ch1.children

    def test_propagation_three_levels_deep(self):
        """
        Violation detected three levels up: adding a leaf to a subsection
        causes the chapter span to interleave with a sibling chapter.
        """
        td = make_tree_dict()
        # Ch1 -> Sec1.1 -> Subsec1.1.1
        subsec = make_node("subsec1.1.1", td, content_list=[make_content(0, 1, 5)])
        sec_1_1 = make_node("sec1.1", td, children=[subsec])
        ch1 = make_node("ch1", td, children=[sec_1_1])

        # Ch2 with content at lines 20-30
        sec_2_1 = make_node("sec2.1", td, content_list=[make_content(0, 20, 30)])
        ch2 = make_node("ch2", td, children=[sec_2_1])

        _root = make_node("root", td, children=[ch1, ch2])

        # Adding content at line 25 to subsec level — grows all the way up,
        # ch1 span becomes (1, 25) which interleaves with ch2 span (20, 30)
        leaf = make_node("leaf", td, content_list=[make_content(0, 25, 26)])
        with pytest.raises(ValueError):
            sec_1_1.add_child(leaf)

    def test_propagation_child_no_content_no_error(self):
        """
        Adding a child with no content never causes interleaving.
        """
        td = make_tree_dict()
        sec_a = make_node("sa", td, content_list=[make_content(0, 1, 10)])
        ch1 = make_node("ch1", td, children=[sec_a])
        sec_b = make_node("sb", td, content_list=[make_content(0, 20, 30)])
        ch2 = make_node("ch2", td, children=[sec_b])
        _root = make_node("root", td, children=[ch1, ch2])

        empty = make_node("empty", td)
        ch1.add_child(empty)  # should succeed
        assert empty in ch1.children

    def test_propagation_init_catches_violation(self):
        """
        Same violation caught during __init__ construction with children=[...].
        """
        td = make_tree_dict()
        sec_1_1 = make_node("s1.1", td, content_list=[make_content(0, 11, 12)])
        sec_3_5 = make_node("s3.5", td, content_list=[make_content(0, 35, 36)])
        ch1 = make_node("ch1", td, children=[sec_1_1, sec_3_5])

        sec_2_1 = make_node("s2.1", td, content_list=[make_content(0, 21, 22)])
        ch2 = make_node("ch2", td, children=[sec_2_1])

        with pytest.raises(ValueError):
            make_node("root", td, children=[ch1, ch2])

    def test_disjoint_content_but_overlapping_spans(self):
        """
        plan.md note: nodes with disjoint content can still violate rule 2.
        Node A has content [1, 2, 3, 5] and node B has content [4, 6].
        They are disjoint but spans overlap: A=(1,5) B=(4,6).
        """
        td = make_tree_dict()
        a = make_node(
            "a",
            td,
            content_list=[
                make_content(0, 1, 1),
                make_content(0, 2, 2),
                make_content(0, 3, 3),
                make_content(0, 5, 5),
            ],
        )
        b = make_node(
            "b",
            td,
            content_list=[make_content(0, 4, 4), make_content(0, 6, 6)],
        )
        with pytest.raises(ValueError):
            make_node("parent", td, children=[a, b])


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


class TestConstructionValidation:
    def test_valid_tree_constructs(self):
        td = make_tree_dict()
        child = make_node("child", td, content_list=[make_content(0, 51, 100)])
        parent = make_node(
            "parent", td, content_list=[make_content(0, 1, 50)], children=[child]
        )
        assert child in parent.children

    def test_ordering_violation_raises(self):
        td = make_tree_dict()
        # child content is BEFORE parent content — violation at construction
        child = make_node("child", td, content_list=[make_content(0, 1, 40)])
        with pytest.raises(ValueError):
            make_node(
                "parent", td, content_list=[make_content(0, 50, 100)], children=[child]
            )

    def test_no_content_skips_check(self):
        td = make_tree_dict()
        child = make_node("child", td, content_list=[make_content(0, 1, 10)])
        parent = make_node("parent", td, children=[child])
        assert child in parent.children

    def test_sibling_ordering_violation_raises(self):
        # s1 span: min=1, max=10; s2 span: min=5, max=15 — interleave
        td = make_tree_dict()
        s1 = make_node(
            "s1", td, content_list=[make_content(0, 1, 2), make_content(0, 10, 11)]
        )
        s2 = make_node(
            "s2", td, content_list=[make_content(0, 5, 6), make_content(0, 15, 16)]
        )
        with pytest.raises(ValueError):
            make_node("parent", td, children=[s1, s2])

    def test_valid_siblings_construct(self):
        td = make_tree_dict()
        s1 = make_node("s1", td, content_list=[make_content(0, 1, 10)])
        s2 = make_node("s2", td, content_list=[make_content(0, 11, 20)])
        parent = make_node("parent", td, children=[s1, s2])
        assert len(parent.children) == 2


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
            id="n",
            title="n",
            children=[],
            content_list=[],
            node_type=NodeType.GENERIC,
            theory=False,
            node_dict=td,
            dependency_ids=["dep"],
        )
        assert n.dependencies == [dep]

    def test_missing_dependency_raises(self):
        td = make_tree_dict()
        n = Node(
            id="n",
            title="n",
            children=[],
            content_list=[],
            node_type=NodeType.GENERIC,
            theory=False,
            node_dict=td,
            dependency_ids=["missing"],
        )
        with pytest.raises(KeyError):
            _ = n.dependencies


class TestAddContent:
    def test_add_content_to_empty_node(self):
        td = make_tree_dict()
        root = make_node("root", td)
        td.set_root(root)
        child = make_node("ch1", td)
        root.add_child(child)

        c = make_content(0, 1, 10)
        child.add_content(c)
        assert child.content_list == [c]

    def test_add_content_to_node_with_existing_content(self):
        td = make_tree_dict()
        root = make_node("root", td)
        td.set_root(root)
        child = make_node("ch1", td, content_list=[make_content(0, 1, 10)])
        root.add_child(child)

        c2 = make_content(0, 11, 20)
        child.add_content(c2)
        assert len(child.content_list) == 2

    def test_add_content_rule1_violation(self):
        """Content must come after ancestor content."""
        td = make_tree_dict()
        root = make_node("root", td)
        td.set_root(root)
        child = make_node("ch1", td)
        root.add_child(child)

        # Give root content first, then try to add earlier content to child
        root.add_content(make_content(0, 50, 100))
        with pytest.raises(ValueError, match="does not follow"):
            child.add_content(make_content(0, 1, 10))

    def test_add_content_causes_sibling_interleaving(self):
        """Adding content to a node can grow its span and interleave with siblings."""
        td = make_tree_dict()
        root = make_node("root", td)
        td.set_root(root)
        ch1 = make_node("ch1", td, content_list=[make_content(0, 1, 10)])
        ch2 = make_node("ch2", td, content_list=[make_content(0, 20, 30)])
        root.add_child(ch1)
        root.add_child(ch2)

        # Adding content at line 25 to ch1 would make ch1's span (1,25)
        # which interleaves with ch2's span (20,30)
        with pytest.raises(ValueError, match="interleaving"):
            ch1.add_content(make_content(0, 25, 28))

    def test_add_content_propagates_upward(self):
        """Span growth from add_content propagates to grandparent level."""
        td = make_tree_dict()
        root = make_node("root", td)
        td.set_root(root)
        ch1 = make_node("ch1", td)
        ch2 = make_node("ch2", td, content_list=[make_content(1, 1, 50)])
        root.add_child(ch1)
        root.add_child(ch2)

        sec = make_node("sec1_1", td, content_list=[make_content(0, 1, 10)])
        ch1.add_child(sec)

        # Adding chunk 1 content to sec would grow ch1's span into ch2's territory
        with pytest.raises(ValueError, match="interleave"):
            sec.add_content(make_content(1, 5, 20))

    def test_add_content_no_parent_skips_rule2(self):
        """Root node with no parent: rule 2 sibling check is skipped."""
        td = make_tree_dict()
        root = make_node("root", td)
        td.set_root(root)

        root.add_content(make_content(0, 1, 10))
        root.add_content(make_content(0, 20, 30))
        assert len(root.content_list) == 2
