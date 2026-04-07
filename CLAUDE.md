# Claude Code Guidelines

## Architecture

Hexagonal architecture — see `architecture.md` for full details. The critical rule:

**Dependencies point inward: `cli → adapters → application → ports → domain`**

- `domain/` has ZERO imports from other layers
- `application/` depends on domain + ports only — never import adapters here
- `adapters/` implement port protocols — may import `application/serialization`
- `cli.py` is the composition root — the only place concrete adapters are wired into ports

**State owns progression.** `StatePort` manages batch computation, line tracking, tree persistence, and version control. `ParsingService` is pure orchestration — it calls `state.prepare_next()`, runs domain logic, then calls `state.advance()`. It never touches line numbers, cutoff values, or batch presentation data.

**Batch tools use the same state port.** The MCP adapter delegates all validation/alignment to `BatchToolsService`, which talks to `StatePort` via `get_batch_context()` and `set_cutoff()`. No extra repositories or DTO layers are used between the application service and adapters.

When adding a new feature:
- New business rules → `domain/`
- New infrastructure (API, DB, etc.) → create a port in `ports/`, implement in `adapters/`
- New orchestration logic → `application/`
- Never have `ParsingService` import from `adapters/`

## MCP Tools

Haiku uses 3 MCP tools (no built-in Read/Write/Bash):
- `read_batch` — no args. Returns `raw_content`, `batch_line_count`, `current_tree`, `prior_clean_tail`, `known_ids`, `memory_text`. Uses `maxResultSizeChars: 500000` to avoid truncation.
- `submit_clean` — `cleaned_text` → server validates annotations and infers the raw cutoff line via token-sequence alignment. Returns `inferred_cutoff_batch_line`, `match_confidence`, `raw_context_around_cutoff`, `clean_tail`, and `proposed_tree`.
- `commit_batch` — no args by default (server uses its stored inferred cutoff). Optional `cutoff_batch_line` to override. Writes cutoff to state via `set_cutoff()` and marks batch complete.

Open nodes across batches are supported — Haiku can leave nodes unclosed at cutoff. The server emits a soft warning (not an error) if all nodes are closed but the cutoff is mid-batch.

The MCP server (`adapters/mcp/server.py`) runs as SSE on localhost. It wraps `BatchToolsService`, so all validation and cutoff alignment live in the application layer while the adapter handles transport. Version control is still internal to `FilesystemStateStore` (no separate VCS port).

## Annotation Schema

The canonical spec lives in `annotation_schema.txt` (project root). The prompt template in `src/claude_parser/application/prompt_templates.py` embeds a condensed version Haiku needs at runtime.

## Commands

```bash
uv run pytest tests/                  # tests
uv run ruff check src/ tests/         # lint
uv run ruff check --fix src/ tests/   # lint with auto-fix
uv run ty check src/ tests/           # type checking
```
