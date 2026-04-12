# Architecture

This project follows **hexagonal architecture** (ports & adapters) with an explicit
application layer for orchestration.

## Layers at a Glance

```
Domain       — entities, value objects, validation rules (depends on nothing)
Ports        — Protocols declaring how the app talks to infrastructure
Application  — orchestrates use cases, holds shared policies
Adapters     — concrete implementations of ports (CLI, files, MCP transport, etc.)
```

- **Domain** (`src/claude_parser/domain/`): annotation parsing, tree building, node rules.
- **Ports** (`src/claude_parser/ports/`): `LLMPort`, `StatePort`, `BatchToolsPort`.
- **Application** (`src/claude_parser/application/`):
  - `run_engine.py` contains pure run-flow functions (`plan_next`, `clamp_cutoff`, `advance`) and run dataclasses.
  - `parsing/service.py` owns the full run loop orchestration.
  - `batch_tools/` hosts `BatchToolsService` + alignment/tree preview helpers.
  - `serialization.py`, `prompt_builder.py`, and prompt templates are shared policies.
- **Adapters** (`src/claude_parser/adapters/`): concrete infrastructure.
- **CLI** (`src/claude_parser/cli.py`): composition root.

Dependency arrows point inward:

```
cli -> adapters -> application -> ports -> domain
```

## Key Design Decisions

## 1) Progression ownership

`ParsingService` owns progression decisions:

- computes batch plans
- builds `BatchContext`
- applies cutoff clamp and snapshot advancement
- persists snapshot/tree through `StatePort`

`StatePort` adapters persist artifacts and state; they do not own run progression math.

## 2) Batch tools session

`BatchToolsService` is explicit-session based:

- `begin_batch(context, known_ids, tree_dict, current_ordinal)`
- MCP tools: `read_batch`, `submit_clean`, `commit_batch`
- `commit_batch` records committed source line for the caller

`ParsingService` reads `batch_tools.committed_source_line()` and persists progression.

## 3) Thin transport adapters

`BatchMCPServer` is transport glue only:

- exposes service tool specs/calls over SSE
- starts/stops server and writes `mcp_config.json`
- delegates business semantics to `BatchToolsService`

## Typical Flow

```
CLI bootstraps adapters -> state.init() loads raw lines + saved snapshot/tree
                        -> BatchMCPServer starts SSE transport
                        -> ParsingService enters run loop

Loop per batch:
1. ParsingService plans batch via run_engine.plan_next(...)
2. state.write_raw_batch(ordinal, raw_content)
3. ParsingService builds BatchContext from plan + state helpers
4. batch_tools.begin_batch(...)
5. Claude CLI runs with MCP config; Haiku calls read_batch/submit_clean/commit_batch
6. ParsingService reads clean file, parses + validates annotations
7. process_batch_annotations(...) mutates tree
8. ParsingService clamps cutoff, advances snapshot, calls state.save_snapshot/state.save_tree/state.commit_all

After loop: state.read_all_clean_before_cutoff() -> state.write_final()
```

## Filesystem Artifacts

`FilesystemStateStore` keeps everything inside `state_dir/`:

- `raw/raw_{ordinal}.md` — raw slices sent to Haiku
- `clean/clean_{ordinal}.md` — cleaned batches ending with `<!-- cutoff -->`
- `logs/{chunk_id}.json` and `failures/{chunk_id}_raw_response.txt` — invocation outputs
- `tree.json` / `state.json` — serialized annotation tree + `RunSnapshot`
- `memory.md` — optional memory context
- `final.md` — concatenated clean output

## MCP Contract

`BatchToolsService` defines three tools:

1. `read_batch()`
2. `submit_clean(cleaned_text)`
3. `commit_batch(cutoff_batch_line?)`

The SSE adapter returns JSON payloads in MCP `TextContent`.
