# Claude Code Guidelines

## Architecture

Hexagonal architecture — see `architecture.md` for full details. The critical rule:

**Dependencies point inward: `cli → adapters → application → ports → domain`**

- `domain/` has ZERO imports from other layers
- `application/` depends on domain + ports only — never import adapters here
- `adapters/` implement port protocols — may import `application/serialization`
- `cli.py` is the composition root — the only place concrete adapters are wired into ports

When adding a new feature:
- New business rules → `domain/`
- New infrastructure (API, DB, etc.) → create a port in `ports/`, implement in `adapters/`
- New orchestration logic → `application/`
- Never have `ParsingService` import from `adapters/`

## Commands

```bash
uv run pytest tests/                  # tests
uv run ruff check src/ tests/         # lint
uv run ruff check --fix src/ tests/   # lint with auto-fix
uv run ty check src/ tests/           # type checking
```
