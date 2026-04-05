# Claude Code Guidelines

## Architecture

Hexagonal architecture — see `architecture.md` for full details. The critical rule:

**Dependencies point inward: `cli → adapters → application → ports → domain`**

- `domain/` has ZERO imports from other layers
- `application/` depends on domain + ports only — never import adapters here
- `adapters/` implement port protocols — may import `application/serialization`
- `cli.py` is the composition root — the only place concrete adapters are wired into ports

**State owns progression.** `StatePort` manages batch computation, line tracking, tree persistence, and version control. `ParsingService` is pure orchestration — it calls `state.prepare_next()`, runs domain logic, then calls `state.advance(fragment)`. It never touches line numbers, cutoff values, or batch presentation data.

**No intermediate data objects.** State and batch_tools share a reference (`FilesystemStateStore`). The MCP server reads batch data directly from state's adapter-specific properties and writes progress back via `set_cutoff()`. No `Batch` or result objects flow through the service.

When adding a new feature:
- New business rules → `domain/`
- New infrastructure (API, DB, etc.) → create a port in `ports/`, implement in `adapters/`
- New orchestration logic → `application/`
- Never have `ParsingService` import from `adapters/`

## MCP Tools

Haiku uses 3 MCP tools (no built-in Read/Write/Bash):
- `read_batch` — raw content + batch metadata (unclosed_nodes, known_ids, context, memory). Uses `maxResultSizeChars: 500000` to avoid truncation.
- `submit_clean` — cleaned text → server validates annotations and infers the raw cutoff line via token-sequence alignment (`difflib.SequenceMatcher`). Returns `inferred_cutoff_batch_line`, `match_confidence`, `unclosed_nodes`, `raw_context_around_cutoff`.
- `commit_batch` — `chunk_id` + `cutoff_batch_line` → server writes cutoff to state via `set_cutoff()` and marks batch complete.

Open nodes across batches are supported — Haiku can leave nodes unclosed at cutoff. The server warns if all nodes are closed but the cutoff is mid-batch.

The MCP server (`adapters/batch_mcp_server.py`) runs as SSE on localhost. It holds a concrete `FilesystemStateStore` reference (not the protocol) so it can access adapter-specific properties directly. Version control is internal to `FilesystemStateStore` (no separate VCS port).

## Annotation Schema

The canonical spec lives in `annotation_schema.md` (project root). The prompt template in `src/claude_parser/application/prompt_templates.py` embeds a condensed version Haiku needs at runtime.

## Commands

```bash
uv run pytest tests/                  # tests
uv run ruff check src/ tests/         # lint
uv run ruff check --fix src/ tests/   # lint with auto-fix
uv run ty check src/ tests/           # type checking
```
