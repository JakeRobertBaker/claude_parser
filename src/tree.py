from __future__ import annotations
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


class RootNode:
    rank = 0


class NodeDict(Mapping):
    """
    Registry of Nodes keyed by Node.id.
    """

    def __init__(self):
        self._data: dict[str, Node] = {}

    def register(self, node: Node) -> None:
        if node.id in self._data:
            raise ValueError(f"Node with id '{node.id}' is already registered.")
        self._data[node.id] = node

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
        raise NotImplementedError("Iteration is not supported.")


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
        node_dict: NodeDict,
        dependency_ids: list[str] = [],
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
        self._dependencies = dependency_ids
        self.parent = parent

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
