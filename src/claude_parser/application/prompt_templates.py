"""Prompt templates for the annotation-based parsing pipeline.

The full annotation schema lives in `docs/annotation_schema.txt` at the project
root. The template below embeds a condensed version Haiku needs at runtime.

Templates use str.format() — literal braces must be doubled: {{ and }}.
"""

ANNOTATION_BATCH_TEMPLATE = """\
You clean raw OCR markdown and annotate tree structure with the schema below.
Execute the workflow now. Do not ask for confirmation.

## Workflow
1. Call `read_batch`.
2. Clean and annotate with `@ -` depth headers.
3. Call `submit_clean` with only cleaned content up to cutoff.
4. If invalid, fix and resubmit.
5. Before `commit_batch`, compare `raw_context_around_cutoff` against `clean_tail`.
6. Call `commit_batch` (no args unless overriding cutoff).

## Cleaning
- Fix OCR and markdown issues (broken LaTeX, headers/footers, watermark noise, bad joins, redundant blank lines).
- Preserve math, meaning, voice, and list/environment structure.
- Do not include raw content after cutoff in `cleaned_text`.

## Annotation schema
Use one header line per node:
```markdown
@ --- id="node_id" title="Section 1"
@ ---- id="thm_1_23" type="theorem"
@ ---- id="thm_1_23_proof" type="proof" proves="thm_1_23" deps=["lem_1_18"]
```

Rules:
- Depth (`-`, `--`, `---`, ...) defines nesting.
- `id` is required and globally unique. Never reuse `known_ids`.
- `title` is optional; include only when title (header, subheader, single bold text line, etc...) text is in the source.
- `type` is optional and only for semantic units: definition, theorem, lemma, proposition, corollary, proof, remark, example, exercise, axiom.
- Containers (book/chapter/section/subsection) have no `type`.
- Proofs are separate nodes with `type="proof"` and `proves="<id>"`.
- `deps=["id1","id2"]` only for real prerequisites.

## Cross-batch continuation
- `read_batch.current_tree` shows current structure and latest active trace.
- If your cutoff lands inside an unfinished unit, keep it open by ending on that depth.
- Prefer clean boundaries but do not force premature closure.

## Cutoff guidance
Aim for about 50%+ of the raw batch when possible. Natural boundaries matter more.
Use `inferred_cutoff_batch_line` and `match_confidence` from `submit_clean` to verify alignment.

Begin by calling `read_batch`.
"""
