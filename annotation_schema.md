# Annotation Schema

Haiku annotates cleaned markdown with HTML comments that define a tree
structure. Nesting is the source of truth; every structural unit is wrapped
in `<!-- tree:start ... -->` / `<!-- tree:end ... -->` comments.

## Basic form

```
<!-- tree:start id="thm_1_2" type="theorem" title="Theorem 1.2" -->
Statement of the theorem...
<!-- tree:end id="thm_1_2" -->
```

## Attributes

| Attribute      | Required | Where                          | Meaning                                                      |
|----------------|----------|--------------------------------|--------------------------------------------------------------|
| `id`           | yes      | every node                     | Globally unique identifier (use textbook numbering)          |
| `title`        | yes      | every node                     | Human-readable title                                         |
| `type`         | no       | semantic math units only       | One of the valid types below                                 |
| `anc`          | no       | advisory                       | Ancestor path hint, e.g. `"ch01/sec01_02"`                   |
| `proves`       | no       | `type="proof"` only            | The `id` of the statement being proved                       |
| `dependencies` | no       | any node                       | Comma-separated list of prerequisite node ids                |

### Valid `type` values

`definition`, `theorem`, `lemma`, `proposition`, `corollary`, `proof`,
`remark`, `example`, `exercise`, `axiom`.

## Rules

- **Nesting is structure.** A child node lives strictly between its parent's
  start and end comments. No crossing spans.
- **IDs are globally unique** across all batches. The `read_batch` response
  lists `known_ids` from previous batches — never reuse them.
- **Containers have no `type`.** Chapters, sections, subsections, and
  "container" wrappers (e.g. a theorem-block that groups a statement + its
  proof) must omit `type`.
- **`type` is for the span that IS that thing.** A theorem statement gets
  `type="theorem"`; the section that contains it does not.
- **Proofs are separate nodes** with `type="proof"` and `proves="<id>"` where
  `<id>` names the theorem/lemma/proposition/corollary being proved.
- **`dependencies` references earlier nodes** required for material
  understanding. Use sparingly — material prerequisites only, not exhaustive
  cross-links.

## Cross-batch continuation

A node may start in one batch and end in another (e.g. a proof that spans
the cutoff, a chapter that continues for many batches). Leave those nodes
open — the server's `open_stack` carries them to the next batch. The next
batch's `read_batch` response lists them in `unclosed_nodes`.

Prefer leaving a container OPEN over prematurely closing it. A chapter,
section, or in-progress proof that continues past the cutoff should not be
closed just to balance tags.

## Examples

### Single-batch: theorem with its proof

```markdown
<!-- tree:start id="sec01_02" title="1.2 Limits" -->

<!-- tree:start id="thm_1_5" type="theorem" title="Theorem 1.5" -->
If $a_n \to a$ and $a_n \to b$, then $a = b$.
<!-- tree:end id="thm_1_5" -->

<!-- tree:start id="thm_1_5_proof" type="proof" proves="thm_1_5"
     title="Proof of Theorem 1.5" -->
Suppose $a \ne b$. Then $|a - b| > 0$...
<!-- tree:end id="thm_1_5_proof" -->

<!-- tree:end id="sec01_02" -->
```

### Multi-batch: container left open at cutoff

```markdown
<!-- tree:start id="ch01" title="Chapter 1. The Real Line" -->

<!-- tree:start id="sec01_03" title="1.3 Continuity" -->
... content ...
<!-- tree:end id="sec01_03" -->

<!-- tree:start id="sec01_04" title="1.4 The Fundamental Axiom" -->
... content up to cutoff ...
```

Here `sec01_04` and `ch01` stay open. The next batch will see
`unclosed_nodes = ["ch01", "sec01_04"]` (outer-to-inner) and can either
close them or add more children.
