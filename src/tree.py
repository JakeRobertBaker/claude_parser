from __future__ import annotations
from enum import Enum
from typing import Optional
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
    def __init__(self):
        self.title: str
        self.children: list[Node]
        self.content: list[Content]
        self.node_type: NodeType
        self.theory: bool
        self.rank_increment: int
        self.dependencies: list[Content]
        self.parent: Node | RootNode

    @property
    def rank(self) -> int:
        return self.parent.rank + self.rank_increment


class RootNode:
    def __init__(self):
        self.parent = None
        self.rank = 0
