# Claude Code Guidelines

## Architecture

We follow strict hexagonal architecture.

**Dependencies must point inward:** `cli -> adapters -> application -> ports -> domain`

- `domain/` contains only math/tree business rules.
- `ports/` define protocols (`LLMPort`, `StatePort`, `BatchToolsPort`).
- `application/` owns orchestration and policies.
- `adapters/` implement ports and infrastructure.
- `cli.py` is the composition root.

## Progression Ownership

Run progression is application-owned:

- `ParsingService` computes plans, builds batch context, clamps cutoff, advances snapshot.
- `run_engine.py` provides pure functions (`plan_next`, `clamp_cutoff`, `advance`) plus run dataclasses.
- `StatePort` implementations persist artifacts/state and do not own progression decisions.

## Batch Tools Contract

`BatchToolsService` runs with explicit batch sessions:

- `begin_batch(context, known_ids, tree_dict, current_ordinal)`
- tools: `read_batch`, `submit_clean`, `commit_batch`
- `commit_batch` records committed source line; `ParsingService` persists progression.

MCP transport (`adapters/mcp/server.py`) stays transport-only and delegates semantics to `BatchToolsService`.

## Placement Rules

- New domain rules -> `domain/`
- New orchestration/policies -> `application/`
- New infrastructure implementation -> `adapters/`
- Do not import adapters from `application/`.

## Annotation Schema

`annotation_schema.txt` is authoritative. Runtime condensed schema is in
`src/claude_parser/application/prompt_templates.py`.

`<!-- cutoff -->` marks the end of each cleaned batch file.

## Commands

```bash
uv run pytest tests/                  # unit tests
uv run ruff check src/ tests/         # lint
uv run ruff check --fix src/ tests/   # lint w/ auto-fix
uv run ty check src/ tests/           # type checking
```
