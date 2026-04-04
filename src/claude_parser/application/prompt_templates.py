"""Prompt templates for the annotation-based parsing pipeline.

Templates use str.format() — literal braces must be doubled: {{ and }}.
"""

ANNOTATION_BATCH_TEMPLATE = """\
You are a task agent cleaning raw OCR markdown and annotating document structure.

## Workflow

1. Call `read_batch` to get batch metadata (open nodes, known IDs, context) \
and the raw text to clean.
2. Clean and annotate the raw text (see rules).
3. Choose a cutoff point at a natural boundary (between sections, after a proof).
4. Call `submit_clean` with your cleaned text and the cutoff line number.
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

## Open Nodes Across Batches

You do NOT need to close every node before the cutoff. If the content continues \
past your cutoff (e.g., a proof or chapter spans multiple batches), leave those \
nodes open — they will carry to the next batch via the open_stack. The next \
batch will see them in its `read_batch` response and can continue or close them.

Prefer leaving nodes open over prematurely closing them. A proof that is still \
in progress should NOT be closed just because you reached the cutoff. The \
`submit_clean` response will confirm which nodes are unclosed.

## Cutoff

Aim to process at least 50% of the raw text, but stop at a natural boundary. \
If the best natural boundary is before 50%, that is acceptable — a clean break \
is more important than hitting a percentage target.

The `cutoff_batch_line` in `submit_clean` is the 1-indexed line number within \
the raw text where you stopped. For example, if the raw text has 400 \
lines and you cleaned through line 300, use cutoff_batch_line=300.

The server performs an alignment check: the final words of your cleaned_text \
must appear in the raw lines near cutoff_batch_line. If they don't, submit_clean \
returns an error and you must find the correct line number in the raw text and \
resubmit. Locate the exact raw line where your cleaned content ends before \
submitting.

Do NOT include any raw content after the cutoff in your cleaned text.

## Output

After `submit_clean` returns valid, call `submit_result` with:
- chunk_id: from the read_batch response
- cutoff_batch_line: same value you used in submit_clean
- n_lines_cleaned: number of lines in your cleaned text
- notes: null (or a brief note if something unusual happened)
"""
