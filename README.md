# Claude Parser

Parses raw markdown into a validated annotation tree using a batch MCP workflow.

## Architecture Snapshot

- Hexagonal layering: `cli -> adapters -> application -> ports -> domain`
- `ParsingService` owns run progression orchestration.
- `run_engine.py` exposes pure planning/advancement functions.
- `FilesystemStateStore` is persistence-focused (raw/clean/state/tree/log artifacts).
- `BatchToolsService` owns tool semantics (`read_batch`, `submit_clean`, `commit_batch`) with explicit batch sessions.
- Authoritative annotation schema lives in `@docs/annotation_schema.txt` (runtime condensed copy: `src/claude_parser/application/prompt_templates.py`).
- Detailed architecture and end-to-end run flow: `@docs/architecture.md`.

## Commands

```bash
# Unit Tests
uv run python -m pytest tests/

# Ruff - linting
uv run ruff check src/ tests/

# ty - type checking
uv run ty check src/ tests/
```

## Pi SDK adapter

The default remains the existing Claude CLI adapter. To use the restricted Pi SDK
agent through your existing Pi/OpenRouter configuration:

```bash
npm install
uv run python -m claude_parser.cli \
  --raw path/to/raw.md \
  --state path/to/state \
  --llm-adapter pi-sdk \
  --task-model openrouter/anthropic/your-model
```

Omit `--task-model` to use Pi's configured default. The Pi agent is intentionally
given only `read_batch`, `submit_clean`, and `commit_batch`; built-in filesystem and
shell tools, extensions, skills, prompt templates, and ambient context files are not
loaded. See `docs/pi_adapter.md` for the design and operational details.

Pi persists its native session and a content-safe live event timeline below the
state directory's `logs/pi/` tree. `--pi-debug-stream-log` additionally records
the full sensitive stream when needed. Each batch includes 2,000-token read-only
contexts on both sides by default; tune them with
`--prior-clean-context-tokens` and `--next-raw-context-tokens`.
