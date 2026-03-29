"""Prompt templates for the textbook parsing pipeline.

Edit these templates to change what Haiku sees. All inputs (skill instructions,
window content, tree state) are inlined — Haiku's only tool call is Write for
the chunk file.

Templates use str.format() — literal braces must be doubled: {{ and }}.
"""

PHASE0_TEMPLATE = """\
You are a task agent analyzing the front matter of a mathematics textbook.

## Instructions

Below are the first {line_count} lines of a raw markdown file produced by MinerU.
Identify the Table of Contents (if present) and parse it into a hierarchy tree \
of skeleton nodes. If no ToC is found, return an empty hierarchy.

Print ONLY the JSON below to stdout — no other text, no markdown fences.

## Output format

{{
  "hierarchy": {{
    "id": "root",
    "title": "Root",
    "children": [
      {{
        "id": "ch01",
        "title": "Chapter Title",
        "children": [
          {{"id": "sec01_01", "title": "Section Title", "children": []}}
        ]
      }}
    ]
  }}
}}

## Rules
- Use chapter/section numbering from the textbook (ch01, sec01_01, etc.)
- Do NOT include any content fields — these are skeleton nodes only.
- stdout must contain ONLY the JSON.

## Raw file (first {line_count} lines)
{raw_content}
"""

SECTION_TEMPLATE = """\
You are a task agent cleaning textbook markdown and producing structured metadata.

## Task
Clean the raw text in the window below and assign every piece of content to a \
node in the tree.

## Cleaning Rules
- Fix: broken LaTeX (unclosed $, split expressions), broken markdown, page \
numbers, headers/footers, watermarks, redundant blank lines, broken paragraph \
joins.
- Preserve: all math content and notation, the author's voice, math \
environments, lists, theory blocks.
- Omit: section/chapter heading lines (# and ##) — these are already captured \
as node titles in the tree.

## Content Assignment
Partition the cleaned text so every line belongs to exactly one node. Walk the \
window top to bottom:
- Section preamble or discussion -> assign to the existing section node, or \
create a new generic child.
- Formal statement (definition, theorem, lemma, etc.) -> create a new theory \
node.
- Proof, remark, exercise -> create a new child node of the appropriate type.

Multiple valid tree structures exist for the same text. The only hard constraint \
is that you cannot reorder text. Choose whichever structure best reflects the \
textbook's logical organisation.

IMPORTANT: You MUST process the window content sequentially from the FIRST line \
forward. Do not skip or omit any content. Every piece of raw text before your \
cutoff point must appear (cleaned) in the chunk file and be assigned to a node.

## Node Rules
- Valid node_type values: definition, theorem, lemma, proposition, remark, \
exercise, example, generic (default).
- Node IDs must be unique. Use the textbook's own numbering to help ensure \
uniqueness. Check the tree state below for conflicts.
- dependencies: list IDs of theory nodes whose statements are used in this \
node's formulation or proof. Only reference nodes already in the tree state or \
created earlier in this chunk.

## Parameters
- Chunk ID: {chunk_id}
- Raw file line range: {raw_start} to {raw_end} (1-indexed)
- Write the cleaned chunk to: {chunk_path}

## Cutoff
You do not have to process the entire window. You must clean and write ALL \
content from the start of the window up to your chosen cutoff point — the \
cutoff is where you STOP, not what you skip. Everything before the cutoff must \
be in the chunk file.

Choose your cutoff after processing at least 60% of the window ({min_lines} \
raw lines). Stop at a natural boundary — between sections, after a proof ends, \
or after an exercise block. Report the 1-indexed raw file line number where you \
stopped as cutoff_line (between {raw_start} and {raw_end}). The next chunk will \
pick up from that line.

The chunk .md file you write must contain cleaned text for ALL raw lines from \
{raw_start} up to your cutoff_line. Your metadata content line ranges must \
match the actual lines in the file you wrote.

## Output
1. Write the cleaned chunk .md file using the Write tool.
2. Print ONLY the metadata JSON to stdout — no commentary, no fences.

Metadata format:
{{
  "chunk_id": "...",
  "cutoff_line": <1-indexed raw file line where you stopped>,
  "nodes": [
    {{"id": "...", "title": "...", "content": [{{"first_line": N, "last_line": M}}]}},
    ...
  ],
  "notes": null
}}

Node fields:
- Existing nodes (ID already in tree state): id, title, content.
- New nodes: id, title, parent_id (required); node_type, content, dependencies \
(optional).
- content line numbers are 1-indexed relative to the chunk .md file you write.
- No overlaps, no gaps — every cleaned line assigned to exactly one node.
- Parents before children in the node list; each child's content must come \
after its parent's content.

## Current Tree State
```json
{tree_state_json}
```

{overlap_section}\
## Window Content (raw lines {raw_start}–{raw_end})
{window_content}
"""
