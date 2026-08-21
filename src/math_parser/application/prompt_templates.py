"""Prompt templates for the annotation-based parsing pipeline.

The full annotation schema lives in `docs/annotation_schema.txt` at the project
root. The template below embeds a condensed version Haiku needs at runtime.

Templates use str.format() — literal braces must be doubled: {{ and }}.
"""

ANNOTATION_BATCH_TEMPLATE = """\
You clean raw OCR markdown and annotate tree structure with the schema below.
Execute the workflow now. Do not ask for confirmation.

## Workflow
1. Call `read_batch` exactly once. Its complete result remains in this conversation;
   never call it again during this batch.
2. Clean and annotate with `@ -` depth headers.
3. Call `submit_clean` with cleaned content up to cutoff and declare `cutoff_kind`.
4. If invalid, fix and resubmit.
5. Compare `committable_raw_context_around_cutoff`, `committable_raw_tail`,
   `read_only_next_raw_head`, and `submitted_clean_tail`.
6. Inspect every `proposed_tree.batch_nodes` entry, especially `parent_id`.
7. If only tree depths are wrong, call `adjust_depths`; inspect its updated tree.
8. Proceed only when `commit_ready=true`, then call `commit_batch` with no arguments
   to approve and persist the proposal.

## Cleaning
- Fix OCR and markdown issues (broken LaTeX, headers/footers, watermark noise, bad joins, redundant blank lines).
- Preserve math, meaning, voice, and list/environment structure.
- Preserve substantive front matter, explanatory prose, and captions. Do not summarize or silently omit them as cleanup.
- Do not include raw content after cutoff in `cleaned_text`.
- Submitted math is parsed by KaTeX. Safe doubled command escapes such as
  `\\\\mathbf` are corrected to `\\mathbf` and reported; other parse errors must be fixed.

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
- Proofs are separate sibling nodes at the same annotation depth as the statement,
  with `type="proof"` and `proves="<id>"`. Do not nest a proof under its statement.
- This includes proofs whose source begins inline with `Proof` rather than with a Markdown heading.
- A statement that has a proof must use a proveable semantic type (`theorem`,
  `lemma`, `proposition`, or `corollary`), never the generic container type.
- `deps=["id1","id2"]` only for real prerequisites.

## Cross-batch continuation
- `read_batch.tree_context` shows the major outline, complete active trace, and
  local append neighborhoods. Omission counts are explicit.
- Use `inspect_tree` only when an older omitted branch is relevant.
- `read_batch.read_only_context.prior_continuation` is non-null only when the preceding batch explicitly ended inside that node.
- When it is non-null, continue its prose without repeating its annotation header or ID.
- When it is null, do not treat the rightmost tree leaf as unfinished and do not emit leading unannotated continuation prose.
- A continuation is allowed only for `prior_continuation` or for a genuinely oversized unit introduced in the opening annotation block of this batch.
- If a later-starting unit crosses the end of `committable_raw.content`, roll back before it. Do not declare it as a continuation.
- For an allowed oversized unit, submit with `cutoff_kind="continuation"` and set `continuation_node_id` to the proposed tree's active leaf.
- At a complete semantic boundary, submit with `cutoff_kind="clean_boundary"` and omit `continuation_node_id`.

## Cutoff guidance
- `committable_raw.content` is the only committable source. Its enclosing object is
  explicitly labelled `COMMITTABLE SOURCE`.
- The separately nested `read_only_context` object is explicitly labelled
  `READ-ONLY CONTEXT`. Never reproduce `prior_clean_content`, `next_raw_content`,
  or `memory_text` from that object in `cleaned_text`.
- Use `read_only_context.next_raw_content` only to determine whether a definition,
  theorem, proof, list item, exercise, or comparable unit at the end of the
  committable content continues beyond the batch.
- If it continues, roll back and stop before that unit begins. A later batch will
  receive the complete unit as committable content.
- Prefer the latest complete semantic boundary within `committable_raw.content`.
Use `inferred_cutoff_batch_line` and `match_confidence` from `submit_clean` to verify alignment.

## Tree review
- `proposed_tree.batch_nodes` contains every node created by this submission and
  shows both its annotation depth and resolved parent.
- Check section/subsection relationships as well as theorem/definition placement.
- Treat `tree_advisories` as required review work. In particular, make each proof
  a sibling of the statement it proves using the suggested depth.
- `commit_ready=false` on an otherwise valid submission means a required tree edit
  remains; `commit_batch` will reject it until the advisory is resolved.
- Review every `source_heading_advisories` item. Add a generic container node when
  the source heading is structurally meaningful; leave it unresolved only when the
  heading is intentionally represented another way.
- `adjust_depths` can change only the number of annotation hyphens for nodes in
  this pending batch. It cannot rewrite prose or prior batches.
- A failed depth edit must be corrected before commit.

Begin by calling `read_batch` once.
"""
