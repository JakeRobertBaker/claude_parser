# State/MCP Refinement Plan

## Goal
Extract reusable run-progression logic and MCP tool contract from adapters so new storage/MCP transports stay thin, while keeping the system lean (minimal extra files/objects).

## Target Architecture

### Run Engine (shared logic)
- `application/run_engine.py`
  - `RunSnapshot`: next start line, next chunk id, sections completed.
  - `BatchPlan`: ordinal/id + raw slice metadata + min token guidance.
  - `RunEngine`: pure functions for `complete`, `plan_next`, `clamp_cutoff`, `advance`.
- Every state store (filesystem/S3/SQL) keeps IO but delegates progression math to `RunEngine`.

### State Store
- Still one concrete class per backend implementing `StatePort`.
- Responsibilities per store:
  - Persist `RunSnapshot` + tree payloads + batch artifacts (raw/clean/log/failure/memory/final).
  - Call `RunEngine` to compute next batch + clamp cutoff + advance snapshot.
  - Git auto-commit remains a filesystem-only side effect (no versioning port).

### MCP Tools
- `BatchToolsService` exposes:
  - `tool_specs()` → shared schema/description list.
  - `call_tool(name, args)` → returns JSON serializable dict.
- `adapters/mcp/server.py` only handles transport (SSE thread, config path) and marshals specs/results.
- Future MCP transports reuse the same `tool_specs`/`call_tool` without copying logic.

### Minimalism Check
- Only one new module (`run_engine.py`).
- No facade layer; existing `StatePort` remains the application boundary.
- MCP contract reuse adds zero new packages beyond tiny helper methods.
- From-scratch design would likely land on the same layout: a pure progression engine plus thin adapters.
