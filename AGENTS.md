# Agent Notes

## Fast Start

- Use Python 3.14 (`.python-version`, `pyproject.toml` requires `>=3.14`).
- This repo is `uv`-first; run commands from the repo root.
- No CI workflows are checked in; local verification is the source of truth.

## Verification Commands

- Lint: `uv run ruff check src/ tests/`
- Type check: `uv run ty check src/ tests/`
- Tests (works reliably): `uv run python -m pytest tests/`
- Single test: `uv run python -m pytest tests/test_run_engine.py -k <pattern>`

## Entrypoints and Runtime Behavior

- Main parser entrypoint: `uv run python -m claude_parser.cli --raw <raw.md> --state <state_dir> [--resume] [--dry-run]`.
- `BatchMCPServer` writes `mcp_config.json` inside `--state` and serves tools over local SSE.
- Parser runs write artifacts under `--state`: `raw/`, `clean/`, `logs/`, `failures/`, `state.json`, `tree.json`, `final.md`.
- `FilesystemStateStore.init_repo()` auto-initializes a git repo in `--state` if missing, and `commit_all()` commits each successful batch.
- Clean batch files are persisted as `clean/clean_<ordinal>.md` and end with `<!-- cutoff -->`; final merge only includes lines before that marker.

## Architecture Invariants (Do Not Break)

- Keep dependency direction strict: `cli -> adapters -> application -> ports -> domain`.
- `ParsingService` owns progression decisions (`plan_next`, `clamp_cutoff`, `advance`); `StatePort` adapters only persist state/artifacts.
- `BatchToolsService` owns tool semantics (`read_batch`, `submit_clean`, `commit_batch`); `adapters/mcp/server.py` should stay transport-only.
- `annotation_schema.txt` is authoritative; `src/claude_parser/application/prompt_templates.py` contains the condensed runtime schema.
- `application/` must not import from `adapters/`.
