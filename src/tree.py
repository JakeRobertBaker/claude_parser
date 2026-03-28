from __future__ import annotations
from collections.abc import Mapping
from enum import Enum
from content import Content, ContentBound


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

    def validate(self) -> None:
        """
        Validate content ordering across the full tree.
        Checks rule 1 (ancestor content before child content) and
        rule 2 (siblings have strict non-interleaving ordering).
        """
        for node in self._data.values():
            # Rule 1
            upper_bound = node.max_ancestor_content()
            if upper_bound:
                for child in node.children:
                    if not child.is_after_content(upper_bound):
                        raise ValueError(
                            f"Node '{node.id}' has content after child '{child.id}'."
                        )
            # Rule 2
            children_with_content = [
                c for c in node.children if c._content_extrema_min()
            ]
            sorted_siblings = sorted(
                children_with_content, key=lambda c: c._content_extrema_min()
            )
            for i in range(len(sorted_siblings) - 1):
                if not sorted_siblings[i + 1].is_after(sorted_siblings[i]):
                    raise ValueError(
                        f"Sibling nodes '{sorted_siblings[i].id}' and "
                        f"'{sorted_siblings[i + 1].id}' have interleaving content."
                    )

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
    content_list: list[Content]
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
        content_list: list[Content] | None,
        node_type: NodeType,
        theory: bool,
        node_dict: TreeDict,
        dependency_ids: list[str] | None = None,
        parent: Node | None = None,
    ):
        self.id = id
        self.title = title
        self.children = []
        self.content_list = content_list or []
        self.node_type = node_type
        self.theory = theory
        self._node_dict = node_dict
        self._dependencies = dependency_ids or []
        self.parent = None

        if parent:
            self._assign_parent(parent)

        self._node_dict.register(self)

        for child in children:
            self._validate_child(child)
            self.children.append(child)
            child._assign_parent(self)

    def max_ancestor_content(self) -> Content | None:
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

    def is_before_content(self, bound: Content) -> bool:
        """
        Return True iff this Node's full subtree content is all strictly before bound.
        """
        self_max = self._content_extrema_max()
        if self_max:
            return self_max < bound
        return False

    def is_after_content(self, bound: Content) -> bool:
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

    def _content_extrema_max(self) -> Content | None:
        """Get the max Content of this Node's and all of its descendant's content."""
        candidates = self.content_list + [
            child._content_extrema_max() for child in self.children
        ]
        candidates = [x for x in candidates if x]
        return max(candidates) if candidates else None

    def _content_extrema_min(self) -> Content | None:
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

    def add_child(self, child: Node) -> None:
        """
        Add a child to an existing tree node, with local ordering validation.
        """
        self._validate_child(child)
        self.children.append(child)
        child._assign_parent(self)

    def _validate_child(self, child: Node) -> None:
        """
        Check rule 1 (child content after ancestor content) and
        rule 2 (child does not interleave with existing siblings).
        """
        # Rule 1
        upper_bound = self.max_ancestor_content()
        if upper_bound and not child.is_after_content(upper_bound):
            raise ValueError(
                f"Cannot add child '{child.id}': its content does not follow '{self.id}'."
            )
        # Rule 2

        self._validate_rule_2(child)

    def _validate_rule_2(self, child: Node):
        """
        Rule 2: All Node's content span are disjoint to their siblings.
        """

        content_bound = child.content_bound()
        if not content_bound:
            return

        content_bound_changed = True
        parent = self

        for sibling in parent.children:
            sibling_content_bound = sibling.content_bound()
            if sibling_content_bound and sibling_content_bound.intersect(
                content_bound
            ):
                raise ValueError(
                    f"Cannot add child '{child.id}': content interleaves with sibling '{sibling.id}'."
                )

        # passed all the siblings and have not found intersection
        # with the addition of this new Node the parent's content span may have grown. 
        # If that has grown we need to validate.
        new_content_bound = content_bound.union(parent.content_bound())
        # if parent content bound grown
        if new_contnet_bound != content_bound:
        # can we make this reccursive validate(parent's new content bound, parent's sibling content bounds)


    def _assign_parent(self, parent: Node) -> None:
        if self.parent is not None:
            raise ValueError(f"Parent is already assigned to node '{self.id}'.")
        self.parent = parent
