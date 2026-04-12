# Claude Parser

Parses raw markdown into a validated annotation tree using a batch MCP workflow.

## Architecture Snapshot

- Hexagonal layering: `cli -> adapters -> application -> ports -> domain`
- `ParsingService` owns run progression orchestration.
- `run_engine.py` exposes pure planning/advancement functions.
- `FilesystemStateStore` is persistence-focused (raw/clean/state/tree/log artifacts).
- `BatchToolsService` owns tool semantics (`read_batch`, `submit_clean`, `commit_batch`) with explicit batch sessions.
- Authoritative annotation schema lives in `annotation_schema.txt` (runtime condensed copy: `src/claude_parser/application/prompt_templates.py`).
- Detailed architecture and end-to-end run flow: `architecture.md`.

## Commands

```bash
# Unit Tests
uv run python -m pytest tests/

# Ruff - linting
uv run ruff check src/ tests/

# ty - type checking
uv run ty check src/ tests/
```
