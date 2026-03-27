from __future__ import annotations
import propcache
from collections.abc import Mapping
from enum import Enum
from content import ContentPartition, Content


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
        self.root_node = None

    def register(self, node: Node | RootNode) -> None:
        if isinstance(node, Node):
            if node.id in self._data:
                raise ValueError(f"Node with id '{node.id}' is already registered.")
            self._data[node.id] = node
        elif isinstance(node, RootNode):
            if self.root_node:
                raise ValueError("RootNode has already been registered.")
            self.root_node = node
        else:
            raise ValueError("Can only register Node or RootNode.")

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
        for node in sorted(self._data.values(), key=lambda n: n.rank):
            yield node.id


class RootNode:
    def __init__(self, title: str, node_dict: TreeDict, children: list[Node]):
        """
        Once the Root Node has been defined the full tree has been defined.
        """
        self.title = title
        self.rank = 0
        self.id = "root"
        self.children = children


class Node:
    def __init__(
        self,
        id: str,
        title: str,
        children: list[Node],
        content_list: list[Content],
        node_type: NodeType,
        theory: bool,
        node_dict: TreeDict,
        dependency_ids: list[str] | None = None,
        parent: RootNode | Node | None = None,  # None until assigned to a tree
    ):
        self.id = id
        self.title = title
        self.children = children
        self.content_list = content_list
        self.node_type = node_type
        self.theory = theory
        self._node_dict = node_dict
        self._dependencies = dependency_ids or []
        self.parent = parent

        self._node_dict.register(self)

        # child content must be after node content
        if self.content_list:
            if any(self.is_after(child) for child in self.children):
                raise ValueError("Nodes's content must be before it's child content.")

    def is_after(self, other: Node) -> bool:
        return min(self.content_list) > max(other.content_list)

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

    def _child_content_extrema(self, min_max) -> Content | None:
        """
        Get the max/min of a Node's and all of it's children's content.
        """
        if min_max == "max":
            f = max
        else:
            f = min

        extrema_candidates = self.content_list + [
            child._child_content_extrema(min_max) for child in self.children
        ]

        extrema_candidates = [x for x in extrema_candidates if x]

        extrema = f(extrema_candidates) if extrema_candidates else None

        return extrema

    def content_bounds(self) -> tuple[Content | None, Content | None]:
        """
        Get the upper and lower content bounds of the Node's span.
        """
        greatest_content = self._child_content_extrema("max")
        least_content = self._child_content_extrema("min")
        return least_content, greatest_content
