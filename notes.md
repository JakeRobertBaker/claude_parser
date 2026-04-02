# Domain

## Node

A textbook or paper is a tree.

Each node on the tree has attributes

- id: unique_id, want to make snake_case
- title: Sensible Title, json safe string.
- children: list of nodes
- content: Point to the chunk content. Can be empty.
- type: One of, generic, definition, theorem, lemma, ... (see NodeType(StrEnum) class in node.py).
- dependencies: This attribute is only true if we are a theory node, a list of the dependant theory nodes.

Theory nodes are when type is one of: definition, theorem, lemma, proposition, proof, ... (see TheoryTypes in nodes.py)

We will implement content as pointing to a .md file.

## Example Thoughts

We strive for this to be a simple design and therefore robust.

### Example 1

Let's suppose a text has

- theorem A statement
- some other content
- theorem A proof

There is a theory node for theorem A statement, some nodes the other content, and a theory node for theorem A proof. Note the later theorem A node may or may not restate the theorem. We just do what the original text does.

### Example 2

Let's suppose Theorem A is stated and proved in two different parts of the text. Those are two different nodes with appropraite titles. The titles could be the same or they could be "Theorem A" and "Theorem A alternate proof", our design is generic and we follow whatever the text does.

## Content

Content points towards the processed and parsed text.
In our instance, Content points to lines in the chunk .md files.

- Content is assigned to a Node on Node creation.
- Content partitions the chunks. This has been implemented in content partition.

Since content partitions the chunks we have a well defined ordering:

$$
\text{content}_A \geq \text{content}_B \iff \text{A occurs at or after B in the text.}
$$

When a node is added to the tree:

- The content of that node is newer than content of all other nodes.
- The node is either a child of the most recently added node or the recent nodes parent

## Rules

The content span of Node is a pair $(c_0, c_1)$ where $c_0, c_1$ are the min and max of the Node + it's descendent's content.

1. A node's content must be greater than all of it's ancestors (parent, grandparent, etc...)
1. A node's content span cannot interleave with it's siblings

### Example Violations

#### Rule 1 Violation

A node with chapter 3.2 content cannot have chapter 3.1 content in any of it's descendants (children, grandchildren etc...)

#### Rule 2 Violation

A node cannot have content span [sec 1.1, sec 1.5] interval with neighbour node content span [sec 1.4, sec 1.6].

Note that Nodes with disjoint content can violate this rule two violation. If one node has content [1.1, 1.2, 1.3, 1.5] and the neighbour has content [1.4, 1.6] they are disjoint and have the same content spans as in the example.

In order to check rule 1 upon adding a Node we just need to  make sure the node content is after the max of the parent node content and all ancestores.

### Enforcement

Suppose that we have a compliant tree.

Adding `node` as a child of `parent` does not change `parent` ancestor max. Therefore adding nodes does not violate 1.

Let's supose we have a tree Root -> Chapter -> Section nodes for chapters 1-3 and sections [1.1, 1.2, 2.1, 3.1, 3.1]. If we add a node with content for section 3.6 to chapter 1 node then we violate rule 2. The spans of the chapter 1 children look nice:

(1.1, 1.1), (1.2, 1.2),  [and now including] (3.5, 3.5)

However if we look one level up, this clearly breaks the non interleaving of spans between the chapter nodes:
(1.1, 3.5) (2.1, 2.1), (3.1, 3.2).

So adding a node can change a node's content span and the content span of all it's parents.

Therefore whenever we add a node we need to check the non interleaving of the new node and it's siblings and then check if the parent's content span has updated, if it has updated we repeat.
