# Stage 5 - Class Reduction and Documentation Alignment

## What changed

- Removed `ToolSpec` dataclass from batch-tools service.
- Replaced tool specs with plain constant dictionaries.
- Updated MCP server tool registration to consume dict-based specs.
- Updated docs to match implemented architecture:
  - `architecture.md`
  - `CLAUDE.md`
  - `README.md`

## Findings

- Core architecture is now aligned in both code and documentation.
- Batch-tools spec path has fewer classes and lower cognitive overhead.
- No behavior regressions were observed.

## Validation

- Quality gates passed:
  - `uv run pytest tests/`
  - `uv run ruff check src/ tests/`
  - `uv run ty check src/ tests/`
- Resume integration scenario passed into `test_rarefactor5`.

## Scrutiny answers

1. Dependency direction respected? **Yes**.
2. Hidden mutable state reduced? **Yes**. No new hidden mutable state added.
3. Responsibilities clearer? **Yes**. Docs now match actual code ownership.
4. Port interfaces simpler/explicit? **Yes**. Batch tools and state ports are explicit-session and explicit-argument based.
5. Behavior and stability preserved? **Yes**. All checks + resume integration run passed.
6. Temporary complexity introduced? **No**.
7. Failure paths still actionable? **Yes**.
8. Easier to test in isolation? **Yes**. Service boundaries remain explicit.
9. Implementation minimal? **Yes**. Removed one class and associated indirection.
10. Top risks before next stage?
    - Fresh-run integration (non-resume, with real LLM interactions) should be spot-checked.
    - Optional further cleanup: evaluate whether `application/batch_tools/models.py` should be inlined.

## Next steps

1. Run a full non-resume integration scenario when convenient to verify first-batch/ongoing-batch behavior.
2. Optionally remove `application/batch_tools/models.py` if you want to further reduce class count.
