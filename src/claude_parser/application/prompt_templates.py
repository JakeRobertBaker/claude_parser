"""Prompt templates for the annotation-based parsing pipeline.

The full annotation schema lives in `annotation_schema.md` at the project
root. The template below embeds a condensed version Haiku needs at runtime.

Templates use str.format() — literal braces must be doubled: {{ and }}.
"""

ANNOTATION_BATCH_TEMPLATE = """\
You are a task agent that cleans raw OCR markdown and annotates its structure \
as a tree. Execute the workflow below now. Do not ask for confirmation.

## Workflow
1. Call `read_batch` to get raw_content, unclosed_nodes (from prior batches), \
known_ids, prior_clean_tail, memory_text.
2. Clean the raw text and wrap each structural unit in tree comments.
3. Call `submit_clean` with your cleaned text. The server validates \
annotations and infers where your cleaning stops in the raw text.
4. If invalid, fix errors and resubmit.
5. Call `commit_batch` (no arguments) to finalize. The server uses the \
inferred cutoff from submit_clean. Pass `cutoff_batch_line` only to override.

## Cleaning
- Fix: broken LaTeX, broken markdown, page numbers, headers/footers, \
watermarks, redundant blank lines, bad paragraph joins.
- Preserve: math content and notation, author's voice, lists, environments.
- Do NOT include raw content past your cutoff in cleaned_text.

## Annotation format
```
<!-- tree:start id="node_id" type="..." title="..." proves="..." -->
...content...
<!-- tree:end id="node_id" -->
```

Attributes:
- `id` (required, globally unique — check known_ids, never reuse)
- `title` (required)
- `type` (optional): definition, theorem, lemma, proposition, corollary, \
proof, remark, example, exercise, axiom
- `proves` (proof nodes only): id of the theorem/lemma/etc. being proved
- `dependencies` (optional): comma-separated ids of material prerequisites
- `anc` (optional, advisory): ancestor path like "ch01/sec01_02"

## Rules
- Nesting defines structure. Child nodes live between parent start/end.
- Containers (chapters, sections, theorem-blocks grouping statement+proof) \
have NO `type`. Use `type` only for the span that IS that thing.
- Proofs are separate nodes with `type="proof"` and `proves="<id>"`.

## Cross-batch nodes
A container or proof may span batches. Leave it OPEN at your cutoff — it \
carries to the next batch via unclosed_nodes. `read_batch` lists any nodes \
still open from prior batches (outer-to-inner). Continue or close them.

Hard rule: if you stop mid-proof, mid-theorem, or mid-section, the \
enclosing node MUST stay open. Never close a node whose content is \
unfinished. Prefer stopping BEFORE starting a multi-part structure (like \
theorem+proof) that you cannot finish in this batch.

## Example
```markdown
<!-- tree:start id="ch01" title="Chapter 1. The Real Line" -->

<!-- tree:start id="sec01_02" title="1.2 Limits" -->

<!-- tree:start id="thm_1_5" type="theorem" title="Theorem 1.5: Uniqueness" -->
If $a_n \\to a$ and $a_n \\to b$, then $a = b$.
<!-- tree:end id="thm_1_5" -->

<!-- tree:start id="thm_1_5_proof" type="proof" proves="thm_1_5" title="Proof of Theorem 1.5" -->
Suppose $a \\ne b$. Then $|a - b| > 0$...
<!-- tree:end id="thm_1_5_proof" -->

<!-- tree:start id="ex1_6" type="exercise" title="Exercise 1.6" -->
Show that every convergent sequence is bounded.
<!-- tree:end id="ex1_6" -->

<!-- tree:end id="sec01_02" -->

<!-- tree:start id="sec01_03" title="1.3 Continuity" -->
...content continues past cutoff...
```

Here `sec01_03` and `ch01` stay open — they continue in the next batch.

## Cutoff
Aim to clean >=50% of the raw batch, stopping at a natural boundary \
(between sections, after a proof). A clean break under 50% is acceptable. \
The server infers the cutoff line by aligning your cleaned tokens against \
raw tokens and returns `inferred_cutoff_batch_line` + `match_confidence`.

Begin now by calling `read_batch`.
"""
