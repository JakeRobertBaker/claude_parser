# Stage 2 - RunEngine Converted to Pure Functions

## What changed

- Removed the `RunEngine` class from `src/claude_parser/application/run_engine.py`.
- Kept `RunSnapshot` and `BatchPlan` dataclasses.
- Added module-level pure functions:
  - `complete(...)`
  - `plan_next(...)`
  - `clamp_cutoff(...)`
  - `advance(...)`
- Updated `FilesystemStateStore` to call pure functions directly.
- Updated `tests/test_run_engine.py` to validate function behavior (same semantics as before).

## Findings

- Behavior remained stable; no functional drift detected.
- This removed one class and reduced abstraction overhead with no readability loss.
- This stage was intentionally behavior-preserving and did not yet change ownership boundaries.

## Validation

- Quality gates passed:
  - `uv run pytest tests/`
  - `uv run ruff check src/ tests/`
  - `uv run ty check src/ tests/`
- Resume integration scenario passed into `test_rarefactor2`.

## Scrutiny answers

1. Dependency direction respected? **Yes**.
2. Hidden mutable state reduced? **Slightly**. Removed engine object state; adapter still owns `_current_*` state.
3. Responsibilities clearer? **Slightly**. Progression logic is now explicit pure functions.
4. Port interfaces simpler/explicit? **No change yet**.
5. Behavior and stability preserved? **Yes**. Unit/lint/type/integration checks all passed.
6. Temporary complexity introduced? **No**.
7. Failure paths still actionable? **Yes**. No error-path regressions introduced.
8. Easier to test in isolation? **Yes**. Function-level testing is now straightforward.
9. Implementation minimal? **Yes**. Net reduction in class surface.
10. Top risks before next stage?
    - State port redesign could be disruptive due broad call-site impact.
    - Batch tools/session reshaping must preserve commit/cutoff contract.

## Next steps (Stage 3)

1. Introduce explicit `BatchToolsService.begin_batch(...)` session state.
2. Slim `BatchToolsPort` to support explicit batch session start and committed cutoff retrieval.
3. Update `BatchMCPServer` to delegate session calls and keep transport-only concerns.
