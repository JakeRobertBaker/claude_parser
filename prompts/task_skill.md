# Textbook Markdown Cleaning — Task Agent

You clean MinerU-generated markdown and produce structured metadata.

## Inputs

1. **Window file** (`current_window.md`) — raw lines to process
2. **Chunk ID** (e.g., `chunk_042`)
3. **Overlap context** — already processed, do not re-include
4. **Current tree state** JSON — existing node IDs and structure
5. **Raw file line range** — for cutoff_line reporting
6. **Chunk output path** — where to write cleaned text

## Step 1: Clean the Text

Read the window file. Apply these rules:

**Fix:** broken LaTeX (unclosed `$`, split expressions), broken markdown, page numbers, headers/footers, watermarks, redundant blank lines, broken paragraph joins.

**Preserve:** all math content/notation, author's voice, inline/display math environments, lists, theory blocks.

**Do NOT include** section/chapter headings or heading markers (`#`, `##`) in the chunk file — headings live in the tree.

## Step 2: Assign Content to Nodes

Partition the cleaned text so every line belongs to exactly one node. **No line may appear in two nodes. No gaps.**

Each node gets a contiguous range of lines. A parent node's content must come **before** all its children's content in line order.

### How to partition

Walk through the cleaned text top to bottom. For each block of text:

- **Section preamble/discussion** → assign to the existing section node (from tree state), or create a new generic child node
- **Formal statement** (definition, theorem, lemma, etc.) → create a new theory node
- **Proof, discussion between statements, exercises** → create new generic/exercise nodes

Example for a section that starts with discussion, then has a definition, then more discussion:

```
Lines 1-20:  sec01_02 (existing section node — preamble)
Lines 21-30: def:1_5_limit (new definition node, parent: sec01_02)
Lines 31-50: sec01_02_disc1 (new generic node, parent: sec01_02 — discussion after def)
Lines 51-55: thm:1_6_properties (new theorem node, parent: sec01_02)
```

Note: sec01_02 gets lines 1-20 only. The definition at lines 21-30 is a **separate child node**, not part of sec01_02's content. Lines 31-50 are a new generic node, not added to sec01_02.

### Node types

| Type | Use for |
|------|---------|
| `definition` | Formal definitions |
| `theorem` | Theorems |
| `lemma` | Lemmas |
| `proposition` | Propositions |
| `remark` | Author remarks/observations |
| `exercise` | Exercises/problems |
| `example` | Worked examples |
| `generic` | Discussion, proofs, preamble, transitions |

### Node IDs

- Theory: `type:number_name` — `def:1_5_limit`, `thm:1_1_constant_value`, `lemma:3_2_1_bound`
- Generic: `parent_desc` — `sec01_02_preamble`, `sec01_02_disc_after_def_1_5`
- Include textbook numbering for global uniqueness
- Check tree state for conflicts

### Dependencies

List IDs of theory nodes this statement references (only nodes in the tree state or created earlier in this chunk).

## Step 3: Determine Cutoff

Process at least **60%** of the window. Cut at a natural boundary (section heading, paragraph break, end of a theorem). Report `cutoff_line` as the 1-indexed **raw file** line number.

## Step 4: Write Output

1. **Write the chunk .md file** using the Write tool
2. **Print ONLY this JSON to stdout:**

```json
{
  "chunk_id": "chunk_042",
  "cutoff_line": 1385,
  "nodes": [
    {"id": "sec01_04", "title": "1.4 The fundamental axiom",
     "content": [{"first_line": 1, "last_line": 20}]},
    {"id": "def:1_16_axiom", "title": "Definition 1.16: Fundamental Axiom",
     "node_type": "definition", "parent_id": "sec01_04",
     "content": [{"first_line": 21, "last_line": 35}], "dependencies": []},
    {"id": "sec01_04_disc1", "title": "Discussion after Def 1.16",
     "node_type": "generic", "parent_id": "sec01_04",
     "content": [{"first_line": 36, "last_line": 50}], "dependencies": []},
    {"id": "thm:1_17_ivt", "title": "Theorem 1.17: IVT",
     "node_type": "theorem", "parent_id": "sec01_04",
     "content": [{"first_line": 51, "last_line": 55}],
     "dependencies": ["def:1_16_axiom"]}
  ],
  "notes": null
}
```

### Fields

- `chunk_id`: assigned chunk ID
- `cutoff_line`: 1-indexed raw file line where you stopped
- `nodes`: flat list in document order
  - **Existing nodes** (ID in tree state): `id`, `title`, `content`
  - **New nodes** (ID not in tree state): `id`, `title`, `parent_id` required; `node_type` (default `generic`), `content`, `dependencies` optional
  - `content`: line ranges in the **chunk .md file** (1-indexed). Each node's content must be **after** its parent's content.
  - Parents before children in the list

## Rules

1. stdout = ONLY the metadata JSON. No commentary, no fences.
2. Write the chunk .md file with the Write tool.
3. Never modify window file, progress.json, or tree.json.
4. Content line numbers are 1-indexed, relative to the chunk .md file.
5. Every line assigned to exactly one node. No overlaps, no gaps.
6. Each node's content lines must come strictly after its parent node's content lines.
7. Node IDs must be unique.
