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
        content: list[Content],
        node_type: NodeType,
        theory: bool,
        rank_increment: int,
        node_dict: TreeDict,
        dependency_ids: list[str] | None = None,
        parent: RootNode | Node | None = None,  # None until assigned to a tree
    ):
        self.id = id
        self.title = title
        self.children = children
        self.content = content
        self.node_type = node_type
        self.theory = theory
        self.rank_increment = rank_increment
        self._node_dict = node_dict
        self._dependencies = dependency_ids or []
        self.parent = parent

        self._node_dict.register(self)

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

    @property
    def rank(self) -> int:
        if self.parent is None:
            raise ValueError("Node has no parent assigned and therefore no rank.")
        return self.parent.rank + self.rank_increment

    def _child_content_extrema(self, max_min) -> Content | None:
        """
        Get the max/min of a Node's and all of it's children's content.
        """
        if max_min == "max":
            f = max
        else:
            f = min

        return f(f(self.content), *[f(child.content) for child in self.children])

    def content_bounds(self) -> tuple[Content | None, Content | None]:
        """
        Get the upper and lower content bounds of the Node's span.
        """
        greatest_content = self._child_content_extrema("max")
        least_content = self._child_content_extrema("min")
        return least_content, greatest_content
