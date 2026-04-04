"""Prompt templates for the annotation-based parsing pipeline.

Templates use str.format() — literal braces must be doubled: {{ and }}.
"""

ANNOTATION_BATCH_TEMPLATE = """\
You are a task agent cleaning raw OCR markdown and annotating document structure.

## Workflow

1. Call the `read_batch` tool to get the raw text and batch metadata.
2. Clean and annotate the raw text (see rules below).
3. Choose a cutoff point (natural boundary: between sections, after a proof, after exercises).
4. Call `submit_clean` with your cleaned text and the cutoff raw line number.
5. If validation fails, fix the issues and call `submit_clean` again.
6. Once valid, call `submit_result` with the final metadata.

## Cleaning Rules
- Fix: broken LaTeX (unclosed $, split expressions), broken markdown, page \
numbers, headers/footers, watermarks, redundant blank lines, broken paragraph \
joins.
- Preserve: all math content and notation, the author's voice, math \
environments, lists, theory blocks.

## Annotation Format

Wrap every structural unit in HTML comments:

```
<!-- tree:start id="node_id" title="Node Title" -->
...cleaned content...
<!-- tree:end id="node_id" -->
```

### Attributes
- id (required, unique) — use textbook numbering: ch01, sec01_01, thm_1_2, etc.
- title (required) — descriptive title for the node
- type (optional) — ONLY for semantic math units. Valid values: definition, \
theorem, lemma, proposition, corollary, proof, remark, example, exercise, axiom
- anc (optional, advisory) — ancestor path hint like "ch_1/sec_1_2"
- proves (optional) — ONLY on type="proof" nodes. Value is the id of the \
statement being proved.
- dependencies (optional) — comma-separated list of prerequisite node ids

### Rules
- Nesting is the source of truth for structure. A child node must be between \
its parent's start and end comments.
- Containers (chapters, sections, subsections) should have NO type attribute.
- Use type ONLY for text spans that ARE that thing (e.g., a theorem statement \
gets type="theorem", but the section containing the theorem does not).
- Proofs must be separate nodes with type="proof" and proves="<statement_id>".
- dependencies should reference earlier nodes required for understanding. Use \
appropriately — material prerequisites only.
- Node IDs must be globally unique. The `read_batch` response includes known \
IDs from previous batches — do not reuse them.

## Cutoff

Process at least 60% of the raw lines (the `min_clean_lines` field in \
`read_batch` response). Stop at a natural boundary.

The `cutoff_raw_line` you submit to `submit_clean` is the 1-indexed source \
file line where you stopped. Do NOT include any raw content after the cutoff \
— the server handles the remainder automatically.

## Output

After `submit_clean` returns valid, call `submit_result` with:
- chunk_id: from the read_batch response
- cutoff_raw_line: same value you used in submit_clean
- n_lines_cleaned: number of lines in your cleaned text
- notes: null (or a brief note if something unusual happened)
"""
