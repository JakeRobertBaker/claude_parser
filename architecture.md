# Architecture

This project follows **hexagonal architecture** (ports & adapters). If you have Cosmic Python in mind, the extra emphasis here is on the explicit **application layer** (chapter 4): a thin orchestration layer that coordinates use cases without containing business rules itself.

## Layers at a Glance

```
Domain       — entities, value objects, validation rules (depends on nothing)
Ports        — Protocols declaring how the app talks to infrastructure
Application  — orchestrates use cases, holds shared policies (RunEngine, services)
Adapters     — concrete implementations of ports (CLI, files, MCP transport, etc.)
```

- **Domain** (`src/claude_parser/domain/`): annotation parsing, tree building, node rules. It never imports outside helpers.
- **Ports** (`src/claude_parser/ports/`): `LLMPort`, `StatePort`, `BatchToolsPort`. They mention domain types but zero implementation details.
- **Application** (`src/claude_parser/application/`):
  - `run_engine.py` contains `RunEngine`, `RunSnapshot`, and `BatchPlan`, i.e., all batch-planning math.
  - `parsing/service.py` orchestrates the main loop (prepare → LLM → domain validation → advance state).
  - `batch_tools/` hosts `BatchToolsService` + helpers (cutoff alignment, tree previews, DTOs) used by MCP transports.
  - `serialization.py`, `prompt_builder.py`, and prompt templates live here as reusable policies.
- **Adapters** (`src/claude_parser/adapters/`): concrete infrastructure. Today we have `llm/claude_cli.py`, `state/filesystem.py`, and `mcp/server.py`. They can import application helpers (serialization, run engine models) but nothing from other adapters.
- **CLI** (`src/claude_parser/cli.py`): the composition root. It wires adapters into ports, starts/stops the MCP server, and kicks off `ParsingService`.

Dependency arrows always point inward:

```
cli → adapters → application → ports → domain
```

## Project Layout

```
src/claude_parser/
├── cli.py                              # Composition root
├── config.py                           # ParserConfig dataclass
├── domain/
│   ├── node.py                         # Node, TreeDict, NodeType
│   ├── content.py / content_bound.py   # Content VO + span math
│   ├── partition.py / protocols.py     # Supporting structs
│   ├── annotation_parser.py            # Parses @ annotations + cutoff token
│   ├── annotation_tree_builder.py      # Cross-batch tree assembly
│   └── validator.py                    # Structural + semantic validation
├── ports/
│   ├── llm.py
│   ├── state.py                        # Includes BatchContext dataclass
│   └── batch_tools.py
├── application/
│   ├── run_engine.py                   # RunSnapshot, BatchPlan, RunEngine
│   ├── parsing/service.py
│   ├── batch_tools/
│   │   ├── service.py
│   │   ├── cutoff_alignment.py
│   │   ├── tree_preview.py
│   │   └── models.py
│   ├── serialization.py
│   ├── prompt_builder.py
│   └── prompt_templates.py
├── adapters/
│   ├── llm/claude_cli.py
│   ├── state/filesystem.py             # Filesystem + git + RunEngine integration
│   └── mcp/server.py                   # SSE transport over BatchToolsService
└── tests/                              # Domain + serialization coverage
```

## Wiring

`cli.py` is the only file that knows which adapter satisfies which port. Typical startup:

```python
state_store = FilesystemStateStore(config.state_dir, config.raw_path, config.resume)
state_store.init()

llm = ClaudeCLIAdapter()
batch_tools = BatchMCPServer(state_store, config.state_dir)
batch_tools.start()

ParsingService(
    config=config,
    llm=llm,
    state=state_store,
    batch_tools=batch_tools,
).run()
```

Both `ParsingService` and `BatchToolsService` see only the `StatePort` abstraction. Shared logic (token budget calculation, cutoff clamping, snapshot advancement) sits inside `RunEngine`, so every state adapter, regardless of backend, stays thin. MCP transport is similarly thin: the adapter exposes `BatchToolsService.tool_specs()` and `BatchToolsService.call_tool()` over SSE.

## Typical Flow

```
CLI bootstraps adapters → state.init() loads raw lines + saved snapshot
                        → BatchMCPServer starts SSE transport
                        → ParsingService enters run loop

Loop per batch:
1. state.prepare_next(batch_tokens, context_lines) → RunEngine produces BatchPlan, filesystem writes raw mirror
2. batch_tools.prepare() resets submit state
3. Claude CLI runs with MCP config; Haiku calls read_batch/submit_clean/commit_batch
4. submit_clean stores cleaned text + inferred cutoff via state.set_cutoff()
5. commit_batch finalizes the plan
6. ParsingService reads clean file, parses annotations, validates, calls process_batch_annotations
7. state.advance() persists new snapshot/tree and commits git (filesystem adapter detail)

After loop: state.read_all_clean_before_cutoff() concatenates cleaned batches → state.write_final()
```

## MCP Overview

`BatchToolsService` defines the canonical MCP contract:

| Tool | Purpose | Notes |
|------|---------|-------|
| `read_batch` | Send raw slice + context (`batch_line_count`, `current_tree`, `prior_clean_tail`, `known_ids`, `memory_text`). | `_meta.anthropic.maxResultSizeChars = 500000` |
| `submit_clean(cleaned_text)` | Validate annotations, infer cutoff via token alignment, append `<!-- cutoff -->`, write clean file, emit tree preview + alignment diagnostics. | Enforces soft ≥50% token target |
| `commit_batch(cutoff_batch_line?)` | Lock in cutoff (defaults to last submit), mark batch success. | Optional override for manual adjustments |

The SSE adapter simply serializes these responses as JSON `TextContent`. Claude CLI loads the server via `--mcp-config`, disables built-in tools (`--tools ""`), and pre-approves the three MCP tools with `--allowedTools`.

## Annotation Format (Quick Reference)

See `annotation_schema.txt` for the exhaustive spec. Highlights:

- `@ -` depth marks nesting; ids must be unique across the entire document.
- `type="proof"` nodes require `proves="target_id"` pointing at a semantic node (theorem, lemma, etc.).
- `deps=[...]` lists prerequisites; warnings fire if dependencies are unknown.
- `<!-- cutoff -->` belongs at the very end of every cleaned batch file.

Tests under `tests/` cover domain behavior (tree building, validator warnings, serialization round-trips) so adapters can stay thin and infrastructure changes remain safe.
