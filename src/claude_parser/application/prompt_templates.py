"""Prompt templates for the annotation-based parsing pipeline.

Templates use str.format() — literal braces must be doubled: {{ and }}.
"""

ANNOTATION_BATCH_TEMPLATE = """\
You are a task agent cleaning raw OCR markdown and annotating document structure.

## Task

Clean the raw text in {raw_path} and write an annotated version to {clean_path}.
The annotated file must contain cleaned markdown with inline tree structure \
comments.

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
- Node IDs must be globally unique. Check the open nodes and tree state below.

## Cutoff

You do not have to process the entire raw file. Process at least 60% of the \
raw lines ({min_lines} lines). Stop at a natural boundary (between sections, \
after a proof, after exercises).

At your cutoff point, insert:
```
<!-- cutoff -->
```

Everything AFTER the cutoff comment must be UNCHANGED from the raw file — \
copy the remaining raw lines verbatim. Everything BEFORE the cutoff must be \
cleaned and annotated.

## Validation

After writing the annotated file, run the validator:
```bash
uv run python -m claude_parser.validator_cli {clean_path} --raw-file {raw_path}{known_ids_arg}
```

If the validator reports errors, fix them in the file and re-validate. \
Warnings are advisory — fix if straightforward, otherwise note them.

## Output

1. Write the annotated file to {clean_path} using the Write tool.
2. Run the validator using Bash.
3. Fix any errors and re-validate.
4. Print ONLY this JSON to stdout — no commentary, no fences:

{{
  "chunk_id": "{chunk_id}",
  "cutoff_raw_line": <1-indexed raw file line where you stopped>,
  "n_lines_cleaned": <number of cleaned lines before cutoff>,
  "notes": null
}}

{open_nodes_section}\
{context_section}\
{memory_section}\
## Raw file: {raw_path} ({raw_line_count} lines, raw lines {raw_start}–{raw_end} of source)
"""
