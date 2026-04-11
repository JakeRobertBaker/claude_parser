# Refactor Plan: Application-Owned Run Flow

## Intent

Refactor the early architecture so application services own workflow logic and adapters are primarily IO. The key outcome is to remove adapter-owned run progression and simplify class/layout count without weakening domain guarantees.

This plan is based on a manual pass over all tracked files outside `notes/*`.

---

## Core Decision

### Keep run progression as pure functions, not a service class

Use pure functions for planning/clamping/advancing and remove `RunEngine` as a class.

- Why:
  - This logic is deterministic math over `raw_lines + snapshot + cutoff`.
  - It does not need object identity or mutable internals.
  - Pure functions are easiest to test and remove one class.
- Where:
  - Keep in `src/claude_parser/application/run_engine.py` (rename internals, keep file path for minimal churn), or move to `application/run_flow.py` if we want a cleaner file name.
- Keep:
  - `RunSnapshot` and `BatchPlan` as dataclasses for readability and typed boundaries.

This is the best middle ground between architecture clarity and reduced surface area.

### Locked decision

Keep `BatchToolsPort` for now, but slim it down during the refactor instead of removing it.

---

## Target Architecture

### Dependency direction (unchanged)

`cli -> adapters -> application -> ports -> domain`

### Responsibility split (changed)

- `ParsingService` owns the run loop state machine:
  - compute next batch plan
  - write raw mirror
  - start batch-tool session
  - invoke LLM
  - validate + apply tree updates
  - advance snapshot
  - persist + commit
- `FilesystemStateStore` only persists and retrieves data/artifacts.
- `BatchToolsService` owns tool semantics for a single active batch session, but does not own global run progression.
- `BatchMCPServer` remains transport glue.

---

## Major Structural Changes

## 1) Remove adapter-owned progression

Current issue:
- `FilesystemStateStore` owns `_current_plan`, `_current_cutoff`, and calls `RunEngine` methods.

Refactor:
- Move planning and cutoff advancement orchestration into `ParsingService`.
- Convert `StatePort` to explicit persistence operations with explicit IDs/ordinals instead of hidden "current batch" state.

## 2) Make BatchTools session explicit

Current issue:
- `BatchToolsService` pulls context from `StatePort` and writes cutoff back via `set_cutoff`.

Refactor:
- `ParsingService` prepares `BatchContext` and calls `batch_tools.begin_batch(...)`.
- `BatchToolsService` writes clean content via explicit state method taking `ordinal`.
- `commit_batch` stores committed cutoff as batch-local state in `BatchToolsService`.
- `ParsingService` reads committed cutoff from batch tools and advances snapshot itself.

## 3) Reduce class/file count where it does not buy value

- Remove `RunEngine` class (pure functions).
- Remove dataclass `ToolSpec` in favor of a plain constant list of dicts.
- Collapse `application/batch_tools/models.py` into `service.py` with `TypedDict` (or plain dicts with clear keys) if type clarity stays acceptable.

---

## Proposed API Shape

## StatePort (new shape)

Replace hidden current-batch behavior with explicit methods.

Keep:
- `init()`, `init_repo()`, `write_final()`, `read_all_clean_before_cutoff()`, `commit_all()`

Add/replace:
- `load_raw_lines() -> list[str]`
- `load_snapshot() -> RunSnapshot`
- `save_snapshot(snapshot: RunSnapshot) -> None`
- `load_tree() -> TreeDict`
- `save_tree(tree: TreeDict) -> None`
- `list_known_ids(tree: TreeDict) -> list[str]` (or derive in service)
- `read_memory() -> str`
- `read_prior_clean_tail(ordinal: int, n_lines: int) -> str`
- `write_raw_batch(ordinal: int, content: str) -> None`
- `clean_batch_exists(ordinal: int) -> bool`
- `read_clean_batch(ordinal: int) -> str | None`
- `write_clean_batch(ordinal: int, content: str) -> None`
- `write_log(chunk_id: str, content: str) -> None`
- `write_failure(chunk_id: str, content: str) -> None`

Remove from port:
- `prepare_next()`
- `advance()`
- `get_batch_context()`
- `set_cutoff()`
- implicit `current_id/current_ordinal` dependency for IO methods

## BatchToolsService (new shape)

Add explicit session lifecycle:
- `begin_batch(context, known_ids, tree_dict, ordinal)`
- `succeeded()` (same meaning)
- `committed_cutoff_batch_line() -> int | None`

Maintain MCP tool methods:
- `read_batch`
- `submit_clean`
- `commit_batch`

Behavior change:
- `commit_batch` no longer writes cutoff into state adapter.
- It stores the chosen cutoff line in service session state.

---

## Implementation Phases

## Phase 0 - Safety net

1. Add characterization tests for current run flow behavior at application level.
2. Add tests for:
   - planning boundaries
   - cutoff clamp behavior
   - batch tools commit semantics (`submit_clean` then `commit_batch`).

## Phase 1 - Pure run functions

1. Replace `RunEngine` class methods with module-level pure functions.
2. Keep dataclasses (`RunSnapshot`, `BatchPlan`) initially.
3. Update call sites to functions.

## Phase 2 - StatePort redesign

1. Introduce explicit persistence-oriented methods in `ports/state.py`.
2. Update `FilesystemStateStore` to implement new methods.
3. Keep temporary compatibility wrappers only if needed during migration.

## Phase 3 - ParsingService owns orchestration

1. Load raw lines/snapshot/tree at run start.
2. Build batch plan in service.
3. Write raw artifact explicitly.
4. Build batch context and start tools session.
5. After tool commit, read committed cutoff from tools service, clamp, and advance snapshot in service.
6. Persist snapshot/tree and commit through state adapter.

## Phase 4 - Batch tools session refactor

1. Add `begin_batch(...)` with explicit context.
2. Remove direct dependency on `state.get_batch_context()` and `state.set_cutoff()`.
3. Keep clean batch writes through explicit `write_clean_batch(ordinal, ...)`.

## Phase 5 - Transport and composition cleanup

1. Wire `BatchToolsService` in `cli.py` and inject into `BatchMCPServer`.
2. Keep MCP server as transport-only shell.
3. Simplify `BatchToolsPort` to the minimal transport lifecycle needed after refactor.

## Phase 6 - Class/file reduction pass

1. Remove `ToolSpec` dataclass.
2. Inline/replace `models.py` dataclasses with `TypedDict` or plain dict responses.
3. Delete dead compatibility methods and fields from filesystem adapter.

## Phase 7 - Docs and contract updates

1. Update `architecture.md` and `CLAUDE.md` to the new ownership model.
2. Update README run-flow description.

---

## File-by-File Plan (all files outside `notes/*`)

## Root files

- `.gitignore`: no change.
- `.python-version`: no change.
- `README.md`: update architecture/run-flow summary after refactor.
- `annotation_schema.txt`: no schema change expected.
- `architecture.md`: update state progression ownership and flow steps.
- `CLAUDE.md`: update canonical rules (remove "State progression stays in StatePort + RunEngine").
- `opencode.json`: no change.
- `pyproject.toml`:
  - keep dependencies;
  - optional cleanup: fix/remove stale script entrypoint `claude_parser.validator_cli:main` (module does not exist).
- `uv.lock`: only change if dependency set changes (not expected).

## Scratch files

- `scratch/debug.py`: no runtime impact, keep as-is unless explicitly cleaning scratch.
- `scratch/quick.py`: stale imports and constructor args; keep ignored or delete in cleanup-only commit.

## Source package init files

- `src/claude_parser/__init__.py`: no change.
- `src/claude_parser/adapters/__init__.py`: no change.
- `src/claude_parser/application/__init__.py`: no change.
- `src/claude_parser/ports/__init__.py`: no change.

## CLI and config

- `src/claude_parser/cli.py`:
  - wire state + batch service + MCP server explicitly;
  - ensure batch service instance is shared where needed.
- `src/claude_parser/config.py`: no required change unless we add optional toggles.

## Ports

- `src/claude_parser/ports/state.py`: major redesign to explicit persistence API.
- `src/claude_parser/ports/batch_tools.py`:
  - keep with minor adjustments, or remove if transport no longer needs a port.
- `src/claude_parser/ports/llm.py`: no change.

## Application

- `src/claude_parser/application/run_engine.py`:
  - remove class `RunEngine`;
  - keep or rename dataclasses + expose pure functions.
- `src/claude_parser/application/parsing/service.py`: major orchestration rewrite.
- `src/claude_parser/application/tokens.py`: optional micro-opt (cache encoding).
- `src/claude_parser/application/prompt_builder.py`: no change.
- `src/claude_parser/application/prompt_templates.py`: no required change.
- `src/claude_parser/application/serialization.py`: no required change.

### Batch tools package

- `src/claude_parser/application/batch_tools/service.py`: major refactor to explicit `begin_batch` and commit result retrieval.
- `src/claude_parser/application/batch_tools/cutoff_alignment.py`: no change.
- `src/claude_parser/application/batch_tools/tree_preview.py`: no change.
- `src/claude_parser/application/batch_tools/models.py`: likely delete/inline for class reduction.
- `src/claude_parser/application/batch_tools/__init__.py`: update exports if models are removed.

## Adapters

### LLM adapter

- `src/claude_parser/adapters/llm/claude_cli.py`: no behavioral change expected.
- `src/claude_parser/adapters/llm/__init__.py`: no change.

### MCP adapter

- `src/claude_parser/adapters/mcp/server.py`:
  - inject pre-built `BatchToolsService`;
  - stay transport-only.
- `src/claude_parser/adapters/mcp/__init__.py`: no change.

### State adapter

- `src/claude_parser/adapters/state/filesystem.py`: large simplification.
  - remove `RunEngine` dependency;
  - remove `_current_plan`, `_current_cutoff`, `_current_id`, `_current_ordinal`, and hidden batch lifecycle methods;
  - implement explicit persistence methods keyed by `ordinal` / `chunk_id` arguments.
- `src/claude_parser/adapters/state/__init__.py`: no change.

## Domain (no behavioral refactor planned)

- `src/claude_parser/domain/annotation_parser.py`: no change.
- `src/claude_parser/domain/annotation_tree_builder.py`: no change.
- `src/claude_parser/domain/validator.py`: no change.
- `src/claude_parser/domain/content.py`: no change.
- `src/claude_parser/domain/content_bound.py`: no change.
- `src/claude_parser/domain/partition.py`: no change (optional mutable default cleanup later).
- `src/claude_parser/domain/protocols.py`: no change.
- `src/claude_parser/domain/node.py`: no change in this refactor.
- `src/claude_parser/domain/__init__.py`: no required change.

## Tests and fixtures

- `tests/fixtures/basic_tree.json`: no change.
- `tests/fixtures/invalid_ordering.json`: no change.
- `tests/test_annotation_parser.py`: no change.
- `tests/test_annotation_tree_builder.py`: no change.
- `tests/test_content.py`: no change.
- `tests/test_tree.py`: no change.
- `tests/test_validator.py`: no change.
- `tests/test_json_adapter.py`: may need updates only if serialization defaults are cleaned up separately.
- `tests/test_serialization_roundtrip.py`: may need updates only if serialization schema changes (not planned).

Add new tests:
- `tests/test_run_flow.py` (new): plan/clamp/advance pure-function behavior.
- `tests/test_parsing_service_flow.py` (new): end-to-end orchestration with fake ports.
- `tests/test_batch_tools_session.py` (new): explicit session begin/submit/commit behavior.

---

## Acceptance Criteria

- No adapter owns run progression decisions.
- `ParsingService` is the sole owner of batch progression control flow.
- `RunEngine` class removed and replaced by pure functions.
- `FilesystemStateStore` only persists and retrieves artifacts/state.
- Batch tools commit returns cutoff to application orchestration; no hidden adapter mutation required.
- Test suite passes:
  - `uv run pytest tests/`
  - `uv run ruff check src/ tests/`
  - `uv run ty check src/ tests/`
- Docs updated (`architecture.md`, `CLAUDE.md`, `README.md`) to match actual design.

---

## Risks and Mitigations

- Risk: behavior drift in cutoff handling.
  - Mitigation: characterization tests before refactor and explicit clamp tests.
- Risk: temporary dual APIs during migration.
  - Mitigation: short migration branches and remove compatibility shims in same series.
- Risk: MCP tool session regressions.
  - Mitigation: dedicated `BatchToolsService` session tests independent of transport.

---

## Suggested execution order for implementation

1. Add tests first (Phase 0).
2. Replace `RunEngine` class with pure functions.
3. Refactor `StatePort` + filesystem adapter.
4. Refactor `BatchToolsService` session API.
5. Update parsing orchestration.
6. Update MCP server wiring and docs.
7. Remove temporary compatibility and dead code.
