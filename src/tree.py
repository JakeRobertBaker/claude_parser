from __future__ import annotations
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


class Node:
    def __init__(
        self,
        title: str,
        children: list[Node],
        content: list[Content],
        node_type: NodeType,
        theory: bool,
        rank_increment: int,
        dependencies: list[Content],
        parent: Node | None = None,
    ):
        self.title = title
        self.children = children
        self.content = content
        self.node_type = node_type
        self.theory = theory
        self.rank_increment = rank_increment
        self.dependencies = dependencies
        self.parent = parent

    @property
    def rank(self) -> int:
        if self.parent is None:
            raise ValueError("Node has no parent assigned and therefore no rank.")
        return self.parent.rank + self.rank_increment

