# Stage 4 - StatePort Redesign and Service-Owned Progression

## What changed

- Replaced `StatePort` contract with explicit persistence-oriented API in `src/claude_parser/ports/state.py`.
- Refactored `FilesystemStateStore` to remove hidden current-batch lifecycle fields:
  - removed `_current_plan`, `_current_cutoff`, `_current_id`, `_current_ordinal`, etc.
  - added explicit methods keyed by `ordinal`/`chunk_id` (`write_raw_batch`, `read_clean_batch`, `write_log`, etc.).
  - exposed `raw_lines`, `snapshot`, `save_snapshot`, `save_tree`.
- Rewrote `ParsingService` orchestration around pure run functions and explicit state calls:
  - service now computes `BatchPlan`
  - service writes raw artifact
  - service builds `BatchContext`
  - service clamps/advances snapshot itself
  - service persists snapshot/tree and commits.
- Updated `BatchToolsService` clean write call to explicit `write_clean_batch(ordinal, content)`.
- Updated tests to match state API changes.

## Findings

- This stage achieved the main architecture shift: progression control is now clearly application-owned.
- Adapter responsibilities are significantly narrower and easier to reason about.
- No regressions were observed in existing tests or resume integration scenario.

## Validation

- Quality gates passed:
  - `uv run pytest tests/`
  - `uv run ruff check src/ tests/`
  - `uv run ty check src/ tests/`
- Resume integration scenario passed into `test_rarefactor4`.

## Scrutiny answers

1. Dependency direction respected? **Yes**.
2. Hidden mutable state reduced? **Yes (major)**. Adapter no longer stores active batch lifecycle state.
3. Responsibilities clearer? **Yes (major)**. `ParsingService` owns orchestration; adapter persists.
4. Port interfaces simpler/explicit? **Yes**. APIs are explicit and argument-driven.
5. Behavior and stability preserved? **Yes**. All checks + resume integration run passed.
6. Temporary complexity introduced? **Low**. Some docs now lag implementation and should be updated next.
7. Failure paths still actionable? **Yes**. Error messages remain contextual by chunk id.
8. Easier to test in isolation? **Yes**. State interactions are now explicit and mock-friendly.
9. Implementation minimal? **Mostly yes**. One remaining simplification: remove tool/model dataclass overhead.
10. Top risks before next stage?
    - Documentation mismatch (`architecture.md`, `CLAUDE.md`) may mislead future contributors.
    - Remaining DTO/spec classes in batch tools are extra moving parts.

## Next steps (Stage 5)

1. Remove `ToolSpec` dataclass and use constant dict tool specs.
2. Inline or simplify `application/batch_tools/models.py` usage.
3. Update `architecture.md`, `CLAUDE.md`, and `README.md` to match implemented architecture.
