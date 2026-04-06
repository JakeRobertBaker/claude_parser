# Architecture

This project follows **hexagonal architecture** (ports & adapters). If you've read chapters 1–3 of Cosmic Python, the key addition is the **application layer** (covered in chapter 4 as the "Service Layer") — a distinct layer between domain and adapters that orchestrates use cases without containing business logic itself.

## The Four Layers

```
Domain       — entities, value objects, business rules (depends on nothing)
Ports        — interfaces defining how the app talks to infrastructure
Application  — use-case orchestration (the "glue")
Adapters     — infrastructure implementations of ports
```

**Domain** is pure business logic. It has zero imports from any other layer. If you can't justify something as a business rule or domain concept, it doesn't belong here.

**Ports** are Python `Protocol` classes — they define the *shape* of a connection (like a USB socket on a laptop). The application layer programs against these abstractions without knowing what's plugged in.

**Adapters** are the cables/dongles that connect specific infrastructure to those sockets. `ClaudeCLIAdapter` plugs the Claude CLI into `LLMPort`. `FilesystemStateStore` plugs the filesystem (+ git) into `StatePort`. You could swap either without touching the application layer.

**Application** sits between domain and adapters. It orchestrates: "get next batch, call the LLM, parse annotations, build tree, advance state." It knows *what* to do but not *how* infrastructure works — that's delegated through ports.

The **CLI** (`cli.py`) is the **composition root** — the one place where all layers meet to wire adapters into ports. This is the only file that imports concrete adapter classes.

## Dependency Rule

Dependencies always point inward:

```
cli.py → adapters/ → application/ → ports/ → domain/
                         ↓                      ↑
                         └──────────────────────┘
```

- `domain/` depends on nothing
- `ports/` depends on domain (references domain types in signatures)
- `application/` depends on domain + ports
- `adapters/` depends on domain + ports + application/serialization
- `cli.py` depends on everything (composition root)

## Project Structure

```
src/claude_parser/
├── cli.py                              # Composition root: wires adapters into ports
├── config.py                           # ParserConfig dataclass
│
├── domain/                             # Pure business logic, ZERO external deps
│   ├── node.py                         # Node, TreeDict, NodeType — core tree entities
│   ├── content.py                      # Content value object (chunk_number, first_line, last_line)
│   ├── content_bound.py                # ContentBound — spatial bounds with union/intersect
│   ├── partition.py                    # ContentPartition — overlap validation
│   ├── protocols.py                    # ContentBase protocol (ordering + truthiness)
│   ├── annotation_parser.py            # Parse <!-- tree:start/end --> comments from markdown
│   ├── annotation_tree_builder.py      # Fragment AST builder — handles cross-batch nodes
│   └── validator.py                    # Annotation validation (nesting, IDs, proves, deps)
│
├── ports/                              # Driven-side interfaces (Protocol classes)
│   ├── llm.py                          # LLMPort — invoke(prompt, model, ...) → LLMResult
│   ├── state.py                        # StatePort — batch progression, tree access, persistence
│   └── batch_tools.py                  # BatchToolsPort — MCP tool server lifecycle
│
├── application/                        # Use-case orchestration
│   ├── parsing_service.py              # ParsingService — pure orchestration loop
│   ├── serialization.py                # Tree ↔ dict serialization (used by service + adapters)
│   ├── llm_response_parser.py          # Extract JSON from Claude's stream-json output
│   ├── prompt_builder.py               # Prompt assembly from templates
│   └── prompt_templates.py             # ANNOTATION_BATCH_TEMPLATE
│
├── adapters/                           # Infrastructure implementations
│   ├── claude_cli.py                   # LLMPort impl — wraps `claude` CLI via subprocess
│   ├── filesystem_state_store.py       # StatePort impl — state.json + tree.json + git on disk
│   └── batch_mcp_server.py            # BatchToolsPort impl — MCP SSE server with 3 tools

tests/
├── test_tree.py                        # Node construction, ordering rules, propagation
├── test_content.py                     # Content ordering, ContentPartition overlap checks
├── test_json_adapter.py                # Tree deserialization from fixture files
├── test_serialization_roundtrip.py     # Serialize → deserialize → verify identity
├── test_merge.py                       # merge_chunk, validate_metadata, dependency report
├── test_annotation_parser.py           # Parse start/end/cutoff events from markdown
├── test_validator.py                   # Nesting errors, duplicate IDs, proves warnings
└── test_annotation_tree_builder.py     # Fragment AST: single batch, cross-batch, cutoff
```

## Wiring Example

The CLI creates concrete adapters and injects them into the service via port-typed parameters:

```python
# cli.py — the only place that knows which adapter goes in which port
state_store = FilesystemStateStore(config.state_dir, config.raw_path, config.resume)
state_store.init()

llm         = ClaudeCLIAdapter()
batch_tools = BatchMCPServer(state_store, config.state_dir)
batch_tools.start()

service = ParsingService(
    config=config,
    llm=llm,               # ...into LLMPort
    state=state_store,      # ...into StatePort
    batch_tools=batch_tools # ...into BatchToolsPort
)
```

`ParsingService` only sees the port shapes. It calls `self.state.prepare_next(...)`, `self.llm.invoke(...)`, `self.state.advance(fragment)` — never knowing whether it's talking to Claude, a mock, or something else entirely. No data objects flow between state and batch_tools — they share a reference and communicate directly. State owns all progression logic (line tracking, batch computation, tree persistence, git commit). The service does pure orchestration: prepare → invoke LLM → run domain logic → advance.

## End-to-End Flow

```
CLI  →  creates adapters (State, LLM, BatchMCPServer)
     →  state.init() loads raw file + resumes saved progress
     →  starts MCP server (SSE on localhost)
     →  injects into ParsingService, calls service.run()

Main Loop:  while not state.complete
        → state.prepare_next(batch_tokens, context_lines)
        → batch_tools.prepare()  (reads from shared state — no args)
        → llm.invoke(mcp_config_path=...)
        → Haiku calls read_batch (raw content + metadata from state)
        → Haiku calls submit_clean (cleaned text + cutoff line)
            → server validates, writes clean file, reports unclosed nodes
        → Haiku calls submit_result → MCP server writes cutoff to state
        → service checks batch_tools.succeeded()
        → service reads clean file, runs domain logic:
            → parse_annotations → validate_annotations → process_batch_annotations
        → state.advance(fragment) — uses stored cutoff, saves state + tree, commits

Final:  → concatenate clean files → final.md
     →  stop MCP server
```

## Annotation Format

Haiku embeds structure inline using HTML comments:

```markdown
<!-- tree:start id="thm_1_2" type="theorem" title="Theorem 1.2" -->
Statement of the theorem...
<!-- tree:end id="thm_1_2" -->
```

Attributes: id (required), title (required), type (optional, semantic only),
anc (optional, advisory), proves (optional, proof only),
dependencies (optional, comma-separated IDs).

Nesting is the source of truth for tree structure. A `<!-- cutoff -->` comment
marks where cleaning stops; lines after it are unchanged raw text.

## Ports & Adapters Analogy

A **port** is a socket — it defines what shape plugs in. An **adapter** is the dongle that connects a specific thing to that socket.

| Port (socket)          | Adapter (dongle)           | What it connects              |
|------------------------|----------------------------|-------------------------------|
| `LLMPort`              | `ClaudeCLIAdapter`         | Claude CLI subprocess         |
| `StatePort`            | `FilesystemStateStore`     | state.json + tree.json + git  |
| `BatchToolsPort`       | `BatchMCPServer`           | MCP SSE server (read/submit)  |

Tomorrow you could write `OpenAIAdapter` for `LLMPort`, `OpenCodeMCPAdapter` for `BatchToolsPort`, or `MemoryStateStore` for testing — same ports, different adapters. The application layer wouldn't change.

## MCP Tools

Haiku interacts with three MCP tools instead of built-in Read/Write/Bash:

- **`read_batch`** — Returns raw content + batch metadata (chunk_id, open_stack, known_ids, previous_batch_tail). Uses `_meta.anthropic.maxResultSizeChars: 500000` to avoid truncation.
- **`submit_clean(cleaned_text, cutoff_batch_line)`** — Submits cleaned markdown. Server validates annotations (token-based soft minimum at 50%), appends cutoff marker + raw remainder, writes clean file. Returns validation result + alignment context + unclosed node info.
- **`submit_result(chunk_id, cutoff_batch_line, n_lines_cleaned, notes)`** — Submits structured result. Replaces stdout JSON parsing.

Open nodes across batches are supported — Haiku can leave nodes unclosed at cutoff. The open_stack carries them to the next batch. The token minimum is a soft warning, not a hard error.

The MCP server runs as an SSE server in a background thread, sharing StatePort with ParsingService. Claude CLI connects via `--mcp-config` with `--system-prompt` (overrides default to skip memory/CLAUDE.md), `--tools ""` (no built-in tools), and `--strict-mcp-config`.
