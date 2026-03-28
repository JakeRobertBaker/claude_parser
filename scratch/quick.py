from claude_parser.adapters.chunk_lines.content import Content
from claude_parser.domain.node import Node, NodeType, TreeDict

td = TreeDict()


def c(chunk, first, last) -> Content:
    return Content(chunk_number=chunk, first_line=first, last_line=last)


def n(id, children=None, content=None, **kw) -> Node:
    return Node(
        id=id,
        title=id,
        children=children or [],
        content_list=content,
        node_type=kw.get("node_type", NodeType.GENERIC),
        theory=kw.get("theory", False),
        node_dict=td,
    )


# Example: build a small tree
sec1 = n("sec1", content=[c(0, 1, 10)])
sec2 = n("sec2", content=[c(0, 11, 20)])
ch1 = n("ch1", children=[sec1, sec2])

sec3 = n("sec3", content=[c(0, 21, 30)])
ch2 = n("ch2", children=[sec3])

root = n("root", children=[ch1, ch2])
td.set_root(root)

print("Tree built successfully")
print(f"Root: {root.id}, children: {[c.id for c in root.children]}")
print(f"ch1 span: {ch1.content_bound()}")
print(f"ch2 span: {ch2.content_bound()}")
