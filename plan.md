<!-- snippets: latex_math -->

# Plan

A textbook or paper is a tree.

Each node on the tree has attributes

- id
- title
- children
- content
- kind: generic, definition, theorem, lemma, proposition, remarks, exercise etc
- proof: only not null for definitions theorems lemmas and propositions.

we will implement content as pointing to a .md file.

Content is assigned to a node on creation.

Rules
content is ordered in the original raw text
parsed content maintains that ordering

$$
\text{content}_A \geq \text{content}_B \iff \text{A occurs at or after B in the text.}
$$

When a node is added to the tree:

- The content of that node is newer than content of all other nodes.
- The node is either a child of the most recently added node or the recent nodes parent
