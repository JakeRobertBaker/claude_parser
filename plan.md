# Plan

## Domain

A textbook or paper is a tree.

Each node on the tree has attributes

- id: unique_id
- title: Sensible Title, json safe string.
- children:
- content: Point to the chunk content. Can be empty.
- type: One of, generic, definition, theorem, lemma, proposition, remarks, exercise.
- theory: True if type is any of definition, theorem, lemma, proposition
- dependencies: This attribute is only true if we are a theory node, a list of the dependant theory nodes.

We will implement content as pointing to a .md file.

We strive for this to be a simple design and therefore robust.

### Example 1

Let's suppose a text has

- theorem A statement
- some other content
- theorem A proof

There is a theory node for theorem A statement, some nodes the other content, and a theory node for theorem A proof. Note the later theorem A node may or may not restate the theorem. We just do what the original text does.

### Example 2

Let's suppose Theorem A is stated and proved in two different parts of the text. Those are two different nodes with appropraite titles. The titles could be the same or they could be "Theorem A" and "Theorem A alternate proof", our design is generic and we follow whatever the text does.

## Node

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

## Content

content is a class

content points to chunk line numbers
content has a geq method based upon line numbers

content must partition the chunks
