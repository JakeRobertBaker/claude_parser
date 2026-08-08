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
- **Ports** (`src/claude_parser/ports/`): `LLMPort`, `StatePort`, `BatchToolsPort`, `MathValidationPort`.
- **Application** (`src/claude_parser/application/`):
  - `run_engine.py` contains pure run-flow functions (`plan_next`, `clamp_cutoff`, `advance`) and run dataclasses.
  - `parsing/service.py` owns the full run loop orchestration.
  - `batch_tools/` hosts `BatchToolsService` plus alignment and structured tree-view helpers.
  - `serialization.py`, `prompt_builder.py`, and prompt templates are shared policies.
- **Adapters** (`src/claude_parser/adapters/`): concrete infrastructure, including
  interchangeable Claude CLI and Pi SDK agent adapters.
- **CLI** (`src/claude_parser/cli.py`): composition root.

Dependency arrows point inward:

```
cli -> adapters -> application -> ports -> domain
```

## Key Design Decisions

### 1) Progression ownership

`ParsingService` owns progression decisions:

- computes batch plans
- builds `BatchContext`
- applies cutoff clamp and snapshot advancement
- persists snapshot/tree through `StatePort`

`StatePort` adapters persist artifacts and state; they do not own run progression math.

### 2) Batch tools session

`BatchToolsService` is explicit-session based:

- `begin_batch(context, known_ids, tree_dict, current_ordinal)`
- tools cover batch reading, tree inspection, submission, depth adjustment, and commit
- a valid submission remains pending until tree review is commit-ready and
  `commit_batch` persists it and records its source line

`ParsingService` reads `batch_tools.committed_source_line()` and persists progression.

### 3) Thin transport adapters

`BatchMCPServer` is transport glue only:

- exposes service tool specs/calls over MCP SSE for Claude CLI
- exposes the same service over a localhost JSON endpoint for Pi custom tools
- starts/stops server and writes `mcp_config.json`
- delegates business semantics to `BatchToolsService`

## Typical Flow

```
CLI bootstraps adapters -> state.init() loads raw lines + saved snapshot/tree
                        -> BatchMCPServer starts local tool transports
                        -> ParsingService enters run loop

Loop per batch:
1. ParsingService plans committable raw plus bounded read-only following context via run_engine.plan_next(...)
2. state writes committable raw content and next raw context as separate artifacts
3. ParsingService builds BatchContext from plan + state helpers
4. batch_tools.begin_batch(...)
5. Selected agent adapter reads once, submits, reviews resolved parents and
   advisories, optionally edits depths, and commits only when `commit_ready=true`
6. ParsingService reads clean file, parses + validates annotations
7. process_batch_annotations(...) mutates tree
8. ParsingService clamps cutoff, advances snapshot, calls state.save_snapshot/state.save_tree/state.commit_all

After loop: state.read_all_clean_before_cutoff() -> state.write_final()
```

## File System Artifacts

`FilesystemStateStore` keeps everything inside `state_dir/`:

- `raw/raw_{ordinal}.md` — committable raw slices exposed to the batch agent
- `raw/next_context_{ordinal}.md` — read-only raw context following each slice
- `clean/clean_{ordinal}.md` — cleaned batches ending with `<!-- cutoff -->`
- `logs/{chunk_id}.json` and `failures/{chunk_id}_raw_response.txt` — invocation summaries/failures
- `logs/pi/{chunk_id}/{attempt}/` — persistent Pi session, safe live events, and manifests
- `tree.json` / `state.json` — serialized annotation tree + `RunSnapshot`
- `memory.md` — optional memory context
- `final.md` — concatenated clean output

## Batch Tool Contract

`BatchToolsService` defines five tools:

1. `read_batch()`
2. `inspect_tree(node_id, child_offset?, child_limit?)`
3. `submit_clean(cleaned_text, cutoff_kind, continuation_node_id?)`
4. `adjust_depths(edits)`
5. `commit_batch()`

The MCP SSE transport returns JSON payloads in MCP `TextContent`. The Pi transport
returns the same payload dictionaries as JSON over localhost HTTP; Pi wraps them as
native custom-tool results.

`read_batch` is single-use within a Pi session and separates its payload into
explicitly labelled `committable_raw` and `read_only_context` objects. Its
`tree_context` is topology-aware and includes the major container outline,
complete active trace, and bounded sibling neighborhoods whose omissions are
explicit. Submission returns every current-batch node with its resolved parent,
structured tree/source-heading advisories, and a distinct `commit_ready` flag.
Depth edits are transactional and limited to the annotation hyphens of those
nodes. A proof nested beneath the statement it proves is a blocking tree advisory:
the text can be valid while the proposal remains uncommittable. No clean artifact
is written until the agent commits the reviewed proposal.

The application depends on `MathValidationPort`; the composition root injects the
Node/KaTeX adapter. It extracts supported Markdown math delimiters outside code,
repairs doubled alphabetic command escapes, and makes remaining KaTeX parse errors
blocking for both Claude and Pi runs.

`batch_tokens` defines the committable content target. `read_batch` also supplies
prior clean and next raw content inside `read_only_context`; both are explicitly
read-only. The latter shows whether a unit at the end of the committable content continues,
so the agent can roll back before that unit rather than guessing from a modulo
batch boundary. The persistence adapter records these separately as
`raw/raw_{ordinal}.md` and `raw/next_context_{ordinal}.md`.

Progress advances only from a cutoff aligned within the committable content. Submit
validation rejects detected material copied from read-only next context. Aligned
invalid submissions return the submitted clean tail, committable raw tail, raw
cutoff neighborhood, and read-only next head so the agent can make a targeted
repair. Validation also
rejects a clean cutoff after a trailing semantic Markdown heading when the next
context begins with more content under that heading. An explicit continuation
node is persisted only for a prior continuation or an oversized unit introduced
in the batch's opening annotation block; a later-starting unit must be rolled
back. The rightmost tree trace alone is not evidence that a unit is unfinished.

Likely generic Markdown headings not represented by generic annotation nodes are
returned as nonblocking source-heading advisories for explicit agent review. This
check is deliberately limited to source headings; it cannot infer an unheaded
structural transition such as photo credits immediately following the last
exercise.
