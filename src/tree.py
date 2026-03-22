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
        parent: Node | RootNode,
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
        return self.parent.rank + self.rank_increment


class RootNode:
    def __init__(self, children: list[Node]):
        self.children = children
        self.rank = 0


# psudocode
def build_node_from_dict(node_dict: dict) -> Node:
    children = node_dict.get("children", [])
    if not isinstance(children, list):
        raise ValueError("children should always be a list.")

        children = [build_node_from_dict(child_dict) for child_dict in children]
