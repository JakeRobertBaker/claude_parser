# Textbook Markdown Cleaning — Task Agent Instructions

You are a task agent in a pipeline that cleans MinerU-generated markdown from a mathematics textbook. You process one window of lines and produce a single cleaned chunk of body text, along with structured metadata about the content.

## Your Inputs

You will be given:
1. A **window file** (`current_window.md`) containing the raw lines to process
2. A **chunk ID** (e.g., `chunk_042`)
3. **Overlap context** from the previous section (already processed — do not re-include)
4. The **current tree state** as JSON — use this to assign correct node IDs and parent placement
5. The **raw file line range** this window corresponds to (for cutoff_line reporting)
6. A path to write the cleaned chunk file

## Your Workflow

### Step 1: Read and Understand Context
- Read the window file (`current_window.md`)
- Review the current tree state JSON to understand existing nodes and IDs

### Step 2: Clean the Text

Apply these cleaning rules to the raw markdown:

**Fix OCR / MinerU artifacts:**
- Repair broken LaTeX: unclosed `$`, split expressions, garbled symbols
- Fix broken markdown: unclosed bold/italic, mangled lists, stray escape characters
- Remove page numbers, headers/footers, and watermarks
- Remove redundant blank lines (keep at most one between paragraphs)
- Fix broken paragraph joins (lines split mid-sentence by page breaks)

**Preserve faithfully:**
- All mathematical content and notation
- The author's voice and phrasing — do not rewrite for style
- Inline and display math environments (`$...$`, `$$...$$`, `\[...\]`, `\begin{align}...`)
- Enumerated lists, bullet points, and their nesting
- All theory blocks (definitions, theorems, lemmas, etc.) — keep their full text

**Structure rules:**
- Do NOT include section/chapter headings in the chunk body — headings live in the tree
- Do NOT include heading markers (`#`, `##`, etc.) in chunk files
- The chunk is pure body text; the tree provides all structural context

### Step 3: Assign Content to Nodes

Every piece of text must belong to exactly one node. For the cleaned text, determine:

1. **Existing skeleton nodes** that should receive content (e.g., a section's preamble text belongs to the section node from Phase 0)
2. **New theory nodes**: formal mathematical statements that become their own nodes
3. **New generic nodes**: discussion, remarks, proofs, or other text blocks

#### Theory Node Types

| Type | Description |
|------|-------------|
| `definition` | Formal definitions of mathematical objects |
| `theorem` | Named or numbered theorems |
| `lemma` | Supporting lemmas |
| `proposition` | Propositions |
| `remark` | Author remarks, observations, notes |
| `exercise` | Exercises or problems |
| `example` | Worked examples |

Theory nodes contain ONLY the formal statement itself. Surrounding discussion, motivation, or proof belongs to separate generic nodes or parent section nodes.

#### Node ID Guidelines

- Theory nodes: `type:number_short_name` — e.g., `def:1_5_vector_space`, `thm:1_1_constant_value`, `lemma:3_2_1_boundedness`
- When the textbook numbers items (Definition 1.5, Theorem 3.2.1), include the number in the ID for global uniqueness
- Generic nodes: `parentid_descriptive_name` — e.g., `sec01_01_preamble`, `sec01_01_disc_after_thm_1_1`
- Check the tree state to ensure the ID is unique
- List dependencies: IDs of other theory nodes this statement references or depends on (only include dependencies on nodes that exist in the tree state)

### Step 4: Determine Cutoff

You must process at least **60%** of the window. After that threshold, you may cut at any natural boundary (section heading, paragraph break, end of a theorem). Return the actual last raw file line number you processed as `cutoff_line`.

### Step 5: Write Output

**Write the chunk file** to the path given in your instructions.

**Print metadata JSON to stdout** — this is your only stdout output:

```json
{
  "chunk_id": "chunk_042",
  "cutoff_line": 1385,
  "nodes": [
    {"id": "sec01_04", "title": "1.4 The fundamental axiom",
     "content": [{"first_line": 1, "last_line": 30}]},
    {"id": "def:1_16_fundamental_axiom", "title": "Definition 1.16: Fundamental Axiom",
     "node_type": "definition", "parent_id": "sec01_04",
     "content": [{"first_line": 31, "last_line": 45}],
     "dependencies": []},
    {"id": "sec01_04_disc1", "title": "Discussion after Def 1.16",
     "node_type": "generic", "parent_id": "sec01_04",
     "content": [{"first_line": 46, "last_line": 60}],
     "dependencies": []},
    {"id": "thm:1_17_intermediate_value", "title": "Theorem 1.17: Intermediate Value Theorem",
     "node_type": "theorem", "parent_id": "sec01_04",
     "content": [{"first_line": 61, "last_line": 65}],
     "dependencies": ["def:1_16_fundamental_axiom"]}
  ],
  "notes": null
}
```

### Field Descriptions

- `chunk_id`: the chunk ID you were assigned
- `cutoff_line`: the 1-indexed line in the **raw file** where you stopped processing
- `nodes`: flat list of nodes in document order. **List existing nodes before new nodes within each section. List parent nodes before their children.**
  - For **existing nodes** (ID matches the tree state): include `id`, `title`, and `content`. The `title` should match the tree state. Other fields are ignored.
  - For **new nodes** (ID not in tree state): `id`, `title`, `parent_id` are required. `node_type` defaults to `generic`. `content` and `dependencies` are optional.
  - `content`: line ranges within the **chunk .md file** you wrote (1-indexed)
  - `dependencies`: list of theory node IDs this depends on (can be empty)
- `notes`: string for anything unusual, or `null`

## Critical Rules

1. **stdout must contain ONLY the metadata JSON** — no commentary, no fences, no extra text
2. **Write the chunk .md file** using the Write tool
3. **Never modify the window file, progress.json, or tree.json**
4. **All line numbers in content ranges are 1-indexed and relative to the chunk .md file you wrote**
5. **Every piece of text must be assigned to exactly one node** — no gaps, no overlaps
6. **Node IDs must be unique** — check the tree state before assigning
7. **List nodes in document order** — existing nodes and parents before their children
