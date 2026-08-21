# Math Parser

Turns messy OCR-derived mathematics Markdown into cleaned Markdown plus a validated
annotation tree. Agents work through a restricted batch-tool protocol; the Claude
CLI uses MCP/SSE and the Pi SDK adapter uses the same application semantics over a
localhost JSON bridge.

## Architecture Snapshot

- Hexagonal layering: `cli -> adapters -> application -> ports -> domain`
- `ParsingService` owns run progression orchestration.
- `run_engine.py` exposes pure planning/advancement functions.
- `FilesystemStateStore` is persistence-focused (raw/clean/state/tree/log artifacts).
- `BatchToolsService` owns batch reading, validation, tree review/depth edits, and commit semantics.
- The authoritative annotation schema is
  [`docs/annotation_schema.txt`](docs/annotation_schema.txt); its condensed runtime
  form is in
  [`prompt_templates.py`](src/math_parser/application/prompt_templates.py).
- See [`docs/architecture.md`](docs/architecture.md) for the detailed architecture
  and end-to-end run flow.

## Requirements and verification

- Python 3.14 or newer
- Node.js 22.19 or newer
- [`uv`](https://docs.astral.sh/uv/)

```bash
# Install Python and JavaScript dependencies
uv sync
npm install

# Python tests
uv run python -m pytest tests/

# Pi runner tests
npm run test:pi

# Lint and type checking
uv run ruff check src/ tests/
uv run ty check src/ tests/
```

## Running the parser

Always use a new state directory for a new run. A successful run writes raw and
clean batch artifacts, logs, `state.json`, `tree.json`, and the merged `final.md`
inside that directory. Resume an interrupted run by supplying the same directory
with `--resume`.

```bash
uv run python -m math_parser.cli \
  --raw path/to/raw.md \
  --state path/to/new_state_directory
```

## Pi SDK adapter

The default remains the existing Claude CLI adapter. To use the restricted Pi SDK
agent through your existing Pi/OpenRouter configuration:

```bash
npm install
uv run python -m math_parser.cli \
  --raw path/to/raw.md \
  --state path/to/state \
  --llm-adapter pi-sdk \
  --task-model openrouter/anthropic/your-model
```

Model selectors accept Pi thinking suffixes, for example
`openrouter/deepseek/deepseek-v4-flash:high`. Omit `--task-model` to use Pi's
configured default. The Pi agent is intentionally
given only the batch read, tree inspection, clean submission, depth adjustment,
and commit tools; built-in filesystem and shell tools, extensions, skills, prompt
templates, and ambient context files are not loaded. See
[`docs/pi_adapter.md`](docs/pi_adapter.md) for design and operational details.

Every adapter validates submitted math with KaTeX. The validator automatically
repairs doubled alphabetic command escapes inside math, reports those corrections,
and rejects remaining parse errors before a batch can be committed.

Pi persists its native session and a content-safe live event timeline below the
state directory's `logs/pi/` tree. `--pi-debug-stream-log` additionally records
the full sensitive stream when needed. Each batch includes 2,000-token read-only
contexts on both sides by default; tune them with
`--prior-clean-context-tokens` and `--next-raw-context-tokens`.

## Moving to another machine

The tracked repository is self-contained, with Python dependencies locked in
`uv.lock` and JavaScript dependencies locked in `package-lock.json`. After cloning:

```bash
uv sync
npm ci
uv run python -m pytest tests/
npm run test:pi
```

Machine-local items are intentionally not stored in Git:

- Pi/OpenRouter credentials. Configure Pi normally or set `OPENROUTER_API_KEY` on
  the new machine.
- The Python virtual environment, Node modules, caches, and built distributions;
  `uv sync` and `npm ci` recreate them.
- Raw source documents and parser state directories, which are commonly outside
  this repository. Copy them separately if they are needed. A copied state
  directory remains resumable, although old manifests and reports can contain
  absolute paths from the original machine.
- Claude CLI installation and authentication, if the `claude-cli` adapter will be
  used.

Use `git status -sb` after cloning to confirm the intended branch. This repository
has no submodules, Git LFS objects, or checked-in CI workflow to restore.

## Documentation status

`README.md`, `AGENTS.md`, and files under `docs/` are the maintained operational
documentation. Files under `plan/`, `rough_notes/`, and `scratch/` are historical
design notes or captured examples and are not normative descriptions of the
current implementation.
