# Claude Code Guidelines

## Architecture

We follow strict hexagonal architecture. Full details live in `architecture.md`, but remember the single golden rule:

**Dependencies must point inward:** `cli → adapters → application → ports → domain`

- `domain/` contains only math/tree business rules — it imports nothing else.
- `ports/` define Protocols (LLM, State, BatchTools) that mention domain types but nothing concrete.
- `application/` implements orchestration and shared policies (parsing loop, batch tools service, run engine, serialization, prompt building). It never imports adapters.
- `adapters/` implement ports (Claude CLI, filesystem state store, MCP transport). They may import application helpers such as serialization or the run engine models.
- `cli.py` is the composition root — the one place concrete adapters are chosen.

**State progression stays in StatePort + RunEngine.** `RunEngine` (application layer) computes batch plans, clamps cutoffs, and advances `RunSnapshot`. Each `StatePort` implementation (filesystem today) delegates those rules while handling persistence (raw/clean files, tree snapshot, git). `ParsingService` only calls `prepare_next`, checks `clean_batch_exists`, reads the clean text, and calls `advance` after domain validation succeeds.

**Batch tools share the same state.** `BatchToolsService` obtains batch context via `state.get_batch_context()`, writes clean files via `state.write_clean_batch()`, and records the cutoff with `state.set_cutoff()`. The MCP adapter itself is just transport glue that exposes `BatchToolsService.tool_specs()` and `BatchToolsService.call_tool()` over SSE.

When adding functionality:
- New domain rules → `domain/`
- New orchestration / policies → `application/`
- New infrastructure (alternate state store, MCP transport, different LLM) → add a port implementation inside `adapters/`
- Never let `ParsingService` or `BatchToolsService` import adapter modules.

## MCP Tools

Haiku uses three MCP tools (no built-in Read/Write/Bash). The payloads are JSON blobs encoded inside a `TextContent` response.

1. `read_batch()` — returns `raw_content`, `batch_line_count`, `current_tree` (ASCII preview), `prior_clean_tail`, `known_ids`, and `memory_text`. `_meta.anthropic.maxResultSizeChars` is set to 500000 so Claude does not truncate large batches.
2. `submit_clean(cleaned_text)` — validates annotations, enforces a soft ≥50% token target, infers the cutoff line via token alignment, appends `<!-- cutoff -->`, writes the clean file, and returns `inferred_cutoff_batch_line`, `match_confidence`, `raw_context_around_cutoff`, `clean_tail`, and `proposed_tree`.
3. `commit_batch(cutoff_batch_line?)` — finalizes the batch. If no override is provided it uses the inferred cutoff stored during the last successful `submit_clean`.

Open nodes across batches are supported: Haiku simply leaves them unclosed and they reappear in the `current_tree` preview. Warnings (e.g., proofs without `proves`) do not block commit — but errors (duplicate IDs, alignment failures) do.

The MCA transport lives in `adapters/mcp/server.py`. It runs an SSE server on localhost, writes a per-run `mcp_config.json`, and defers all tool semantics to `BatchToolsService`.

## Annotation Schema

`annotation_schema.txt` (project root) contains the authoritative spec. The condensed runtime version is embedded in `src/claude_parser/application/prompt_templates.py`. Haiku emits annotation headers of the form:

```markdown
@ -- id="sec01" title="1.2 Limits"
@ --- id="thm_1_5" type="theorem"
Statement...
@ --- id="thm_1_5_proof" type="proof" proves="thm_1_5"
Proof...
```

`<!-- cutoff -->` marks where each clean batch ends. Root nodes without types act as structural containers (chapters, sections, etc.). Proof spans must always have `type="proof"` plus a `proves` attribute.

## Commands

```bash
uv run pytest tests/                  # unit tests
uv run ruff check src/ tests/         # lint
uv run ruff check --fix src/ tests/   # lint w/ auto-fix
uv run ty check src/ tests/           # type checking
```
