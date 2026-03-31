from __future__ import annotations
from collections.abc import Mapping, Sequence
from enum import Enum
from claude_parser.domain.protocols import ContentBase
from claude_parser.domain.content_bound import ContentBound


class NodeType(Enum):
    GENERIC = "generic"
    DEF = "definition"
    THM = "theorem"
    LEM = "lemma"
    PROP = "proposition"
    REM = "remark"
    EXC = "exercise"
    EG = "example"


class TreeDict(Mapping):
    """
    Registry of Nodes keyed by Node.id.
    """

    def __init__(self):
        self._data: dict[str, Node] = {}
        self.root_node: Node | None = None

    def register(self, node: Node) -> None:
        if node.id in self._data:
            raise ValueError(f"Node with id '{node.id}' is already registered.")
        self._data[node.id] = node

    def set_root(self, node: Node) -> None:
        if self.root_node is not None:
            raise ValueError("Root node has already been set.")
        self.root_node = node

    def remove(self, node_id: str) -> None:
        if node_id not in self._data:
            raise KeyError(f"Node with id '{node_id}' not found.")
        del self._data[node_id]

    def __getitem__(self, node_id: str) -> Node:
        if node_id not in self._data:
            raise KeyError(f"Node with id '{node_id}' not found.")
        return self._data[node_id]

    def __len__(self) -> int:
        return len(self._data)

    def __iter__(self):
        if not self.root_node:
            raise ValueError(
                "Cannot iterate through TreeDict until root has been defined."
            )
        raise NotImplementedError("To be implemented.")


class Node:
    id: str
    title: str
    children: list[Node]
    content_list: list[ContentBase]
    node_type: NodeType
    theory: bool
    parent: Node | None
    _node_dict: TreeDict
    _dependencies: list[str]

    def __init__(
        self,
        id: str,
        title: str,
        children: list[Node],
        content_list: Sequence[ContentBase] | None,
        node_type: NodeType,
        theory: bool,
        node_dict: TreeDict,
        dependency_ids: list[str] | None = None,
        parent: Node | None = None,
    ):
        self.id = id
        self.title = title
        self.children = []
        self.content_list: list[ContentBase] = list(content_list) if content_list else []
        self.node_type = node_type
        self.theory = theory
        self._node_dict = node_dict
        self._dependencies = dependency_ids or []
        self.parent = None

        if parent:
            self._assign_parent(parent)

        self._node_dict.register(self)

        for child in children:
            self.add_child(child)

    def max_ancestor_content(self) -> ContentBase | None:
        """
        Get the maximum of this Node's content and its ancestors.
        """
        candidates = self.content_list.copy()
        if isinstance(self.parent, Node):
            parent_max = self.parent.max_ancestor_content()
            if parent_max:
                candidates.append(parent_max)
        return max(candidates) if candidates else None

    def is_after(self, other: Node) -> bool:
        """
        Return True iff this Node's content is all strictly after the other's.
        """
        self_min = self._content_extrema_min()
        other_max = other._content_extrema_max()
        if self_min and other_max:
            return self_min > other_max
        return False

    def is_before_content(self, bound: ContentBase) -> bool:
        """
        Return True iff this Node's full subtree content is all strictly before bound.
        """
        self_max = self._content_extrema_max()
        if self_max:
            return self_max < bound
        return False

    def is_after_content(self, bound: ContentBase) -> bool:
        """
        Return True iff this Node's full subtree content starts strictly after bound.
        """
        self_min = self._content_extrema_min()
        if self_min:
            return self_min > bound
        return False

    @property
    def dependencies(self) -> list[Node]:
        resolved = []
        for dep_id in self._dependencies:
            try:
                resolved.append(self._node_dict[dep_id])
            except KeyError:
                raise KeyError(
                    f"Dependency '{dep_id}' for node '{self.id}' not found in NodeDict."
                )
        return resolved

    def _content_extrema_max(self) -> ContentBase | None:
        """Get the max Content of this Node's and all of its descendant's content."""
        candidates = self.content_list + [
            child._content_extrema_max() for child in self.children
        ]
        candidates = [x for x in candidates if x]
        return max(candidates) if candidates else None

    def _content_extrema_min(self) -> ContentBase | None:
        """Get the min Content of this Node's and all of its descendants's content."""
        candidates = self.content_list + [
            child._content_extrema_min() for child in self.children
        ]
        candidates = [x for x in candidates if x]
        return min(candidates) if candidates else None

    def content_bound(self) -> ContentBound | None:
        """
        Get the upper and lower content bounds of the Node's span.
        """

        lower = self._content_extrema_min()
        upper = self._content_extrema_max()

        if lower and upper:
            return ContentBound(lower, upper)
        else:
            return None

    def add_content(self, content: ContentBase) -> None:
        """
        Add content to this node, with rule validation.
        Content must come after all ancestor content (Rule 1),
        and must not cause sibling span interleaving (Rule 2).
        """
        # Rule 1: content must be after max ancestor content
        upper_bound = self.max_ancestor_content()
        if upper_bound and not content > upper_bound:
            raise ValueError(
                f"Cannot add content to '{self.id}': content does not follow "
                f"ancestor content."
            )

        # Rule 2: check span growth doesn't cause sibling interleaving
        new_bound = ContentBound(content, content)
        old_bound = self.content_bound()
        merged = new_bound.union(old_bound)
        if merged != old_bound and self.parent is not None:
            for sibling in self.parent.children:
                if sibling is self:
                    continue
                sib_bound = sibling.content_bound()
                if sib_bound and sib_bound.intersect(merged):
                    raise ValueError(
                        f"Cannot add content to '{self.id}': would cause "
                        f"interleaving with sibling '{sibling.id}'."
                    )
            Node._propagate_span_check(merged, self.parent, self.id)

        self.content_list.append(content)

    def add_child(self, child: Node) -> None:
        """
        Add a child to an existing tree node, with local ordering validation.
        """
        self._validate_child(child)
        self.children.append(child)
        child._assign_parent(self)

    def _validate_child(self, child: Node) -> None:
        """
        Validate rules 1. and 2.
        Rule 1: A Node's content must be greater than all it's ancestors.
        """
        # Rule 1
        upper_bound = self.max_ancestor_content()
        if upper_bound and child.content_bound() and not child.is_after_content(upper_bound):
            raise ValueError(
                f"Cannot add child '{child.id}': its content does not follow '{self.id}'."
            )

        self._validate_rule_2(child)

    def _validate_rule_2(self, child: Node) -> None:
        """
        Rule 2: All Node's content spans are disjoint to their siblings.
        Adding a child can grow the parent's span, which may cause interleaving
        at the grandparent level. Recurse upward until the span stops growing
        or we hit the root.
        """
        child_bound = child.content_bound()
        if not child_bound:
            return

        # Check child against its future siblings (child not yet in self.children)
        for sibling in self.children:
            sibling_bound = sibling.content_bound()
            if sibling_bound and sibling_bound.intersect(child_bound):
                raise ValueError(
                    f"Cannot add child '{child.id}': content interleaves "
                    f"with sibling '{sibling.id}'."
                )

        # Propagate upward if parent's span would grow
        Node._propagate_span_check(child_bound, self, child.id)

    @staticmethod
    def _propagate_span_check(
        new_bound: ContentBound, node: Node, child_id: str
    ) -> None:
        """
        Check whether adding new_bound to node's subtree would grow node's
        span and cause interleaving with node's siblings. Recurse upward.
        """
        if node.parent is None:
            return

        old_node_bound = node.content_bound()
        new_node_bound = new_bound.union(old_node_bound)
        if new_node_bound == old_node_bound:
            return

        # node's span grew — check against node's siblings (skip node itself)
        for sibling in node.parent.children:
            if sibling is node:
                continue
            sibling_bound = sibling.content_bound()
            if sibling_bound and sibling_bound.intersect(new_node_bound):
                raise ValueError(
                    f"Cannot add child '{child_id}': would cause "
                    f"'{node.id}' to interleave with '{sibling.id}'."
                )

        # Recurse: node.parent's span may also have grown
        Node._propagate_span_check(new_node_bound, node.parent, child_id)

    def _assign_parent(self, parent: Node) -> None:
        if self.parent is not None:
            raise ValueError(f"Parent is already assigned to node '{self.id}'.")
        self.parent = parent
