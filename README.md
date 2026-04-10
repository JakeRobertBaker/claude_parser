# Claude Parser

## Commands

```bash
uv run pytest tests/
```

Some linting things to run

```bash
# Ruff - linting
uv run ruff check src/ tests/

# Ruff - with auto-fix
uv run ruff check --fix src/ tests/

# ty - type checking
uv run ty check src/ tests/
```

## Parser command templates

Replace placeholders with your own paths:
- `<RAW_FILE>`: MinerU-generated markdown file
- `<STATE_DIR>`: state directory for this run

```bash
# Fresh run (new state directory)
uv run python -m claude_parser.cli \
  --raw "<RAW_FILE>" \
  --state "<STATE_DIR>"

# Resume an existing run
uv run python -m claude_parser.cli \
  --raw "<RAW_FILE>" \
  --state "<STATE_DIR>" \
  --resume

# Dry run (preview prompt, no Claude invocation)
uv run python -m claude_parser.cli \
  --raw "<RAW_FILE>" \
  --state "<STATE_DIR>_dry" \
  --dry-run

# Quick smoke test (single successful section)
uv run python -m claude_parser.cli \
  --raw "<RAW_FILE>" \
  --state "<STATE_DIR>_smoke" \
  --max-sections 1
```
