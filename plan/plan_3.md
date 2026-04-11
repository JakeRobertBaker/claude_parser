# Stage 3 - Explicit Batch-Tools Session Lifecycle

## What changed

- Slimmed `BatchToolsPort` in `src/claude_parser/ports/batch_tools.py`:
  - replaced `prepare()` with explicit `begin_batch(...)`
  - added `committed_source_line()`
- Refactored `BatchToolsService` to explicit session data:
  - added `begin_batch(context, known_ids, tree_dict, current_ordinal)`
  - removed direct `state.get_batch_context()` reads
  - removed direct `state.set_cutoff(...)` writes in `commit_batch`
  - added `committed_source_line()` accessor
- Updated `BatchMCPServer` to implement new port methods and delegate session setup.
- Updated `ParsingService` to:
  - gather context from `StatePort`
  - call `batch_tools.begin_batch(...)` before LLM run
  - read `batch_tools.committed_source_line()` and then call `state.set_cutoff(...)` explicitly.
- Updated `tests/test_batch_tools_service.py` to use `begin_batch(...)`.

## Findings

- Control flow is now clearer: batch tools no longer mutate progression state directly.
- Parsing service now explicitly owns the handoff between tool commit and state cutoff.
- This is an important boundary improvement toward service-owned orchestration.

## Validation

- Quality gates passed:
  - `uv run pytest tests/`
  - `uv run ruff check src/ tests/`
  - `uv run ty check src/ tests/`
- Resume integration scenario passed into `test_rarefactor3`.

## Scrutiny answers

1. Dependency direction respected? **Yes**.
2. Hidden mutable state reduced? **Yes**. Cutoff mutation is now explicit in `ParsingService`.
3. Responsibilities clearer? **Yes**. Batch tools computes/returns commit info; state adapter applies cutoff.
4. Port interfaces simpler/explicit? **Yes**. Session lifecycle is explicit and transport-focused.
5. Behavior and stability preserved? **Yes**. Full quality gates + resume integration run passed.
6. Temporary complexity introduced? **Minor**. Transitional coupling still exists through `StatePort.get_batch_context()`.
7. Failure paths still actionable? **Yes**. Missing committed cutoff now raises a clear service error.
8. Easier to test in isolation? **Yes**. Batch tools can be driven with explicit session fixtures.
9. Implementation minimal? **Yes**. No extra service classes introduced.
10. Top risks before next stage?
    - `StatePort` still has implicit "current batch" APIs that can hide sequencing issues.
    - Full port redesign will require coordinated adapter/service updates.

## Next steps (Stage 4)

1. Redesign `StatePort` to explicit persistence methods with explicit ordinals/chunk IDs.
2. Refactor `FilesystemStateStore` to remove `_current_*` lifecycle state where practical.
3. Update `ParsingService` and `BatchToolsService` to use explicit state methods.
