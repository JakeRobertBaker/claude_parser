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

**Adapters** are the cables/dongles that connect specific infrastructure to those sockets. `ClaudeCLIAdapter` plugs the Claude CLI into `LLMPort`. `GitAdapter` plugs Git into `VCSPort`. You could swap either without touching the application layer.

**Application** sits between domain and adapters. It orchestrates: "load the tree, call the LLM, merge the result, save state, commit." It knows *what* to do but not *how* infrastructure works — that's delegated through ports.

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
├── validator_cli.py                    # CLI for annotation validator (invoked by Haiku via Bash)
│
├── domain/                             # Pure business logic, ZERO external deps
│   ├── node.py                         # Node, TreeDict, NodeType — core tree entities
│   ├── content.py                      # Content value object (chunk_number, first_line, last_line)
│   ├── content_bound.py                # ContentBound — spatial bounds with union/intersect
│   ├── partition.py                    # ContentPartition — overlap validation
│   ├── protocols.py                    # ContentBase protocol (ordering + truthiness)
│   ├── annotation_parser.py            # Parse <!-- tree:start/end --> comments from markdown
│   ├── annotation_tree_builder.py      # Fragment AST builder — handles cross-batch nodes
│   ├── batch_types.py                  # BatchResult, SubmitCleanResponse dataclasses
│   └── validator.py                    # Annotation validation (nesting, IDs, proves, deps)
│
├── ports/                              # Driven-side interfaces (Protocol classes)
│   ├── llm.py                          # LLMPort — invoke(prompt, model, ...) → LLMResult
│   ├── vcs.py                          # VCSPort — init_repo(), commit_all(message)
│   ├── state.py                        # StatePort — load/save pipeline state + tree
│   └── batch_tools.py                  # BatchToolsPort — MCP tool server lifecycle
│
├── application/                        # Use-case orchestration
│   ├── parsing_service.py              # ParsingService — single-phase annotation loop
│   ├── pipeline_state.py               # PipelineState dataclass (batch-to-batch state)
│   ├── merge.py                        # Legacy chunk merging (kept for reference)
│   ├── serialization.py                # Tree ↔ dict serialization (used by service + adapters)
│   ├── llm_response_parser.py          # Extract JSON from Claude's stream-json output
│   ├── prompt_builder.py               # Prompt assembly from templates
│   └── prompt_templates.py             # ANNOTATION_BATCH_TEMPLATE
│
├── adapters/                           # Infrastructure implementations
│   ├── claude_cli.py                   # LLMPort impl — wraps `claude` CLI via subprocess
│   ├── git_adapter.py                  # VCSPort impl — wraps `git` CLI via subprocess
│   ├── filesystem_state_store.py       # StatePort impl — state.json + tree.json on disk
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
llm         = ClaudeCLIAdapter()
state_store = FilesystemStateStore(config.state_dir)
state_store.init()
vcs         = GitAdapter(config.state_dir)
batch_tools = BatchMCPServer(state_store, config.state_dir)
batch_tools.start()

service = ParsingService(
    config=config,
    llm=llm,               # ...into LLMPort
    state=state_store,      # ...into StatePort
    vcs=vcs,                # ...into VCSPort
    batch_tools=batch_tools # ...into BatchToolsPort
)
```

`ParsingService` only sees the port shapes. It calls `self.llm.invoke(...)`, `self.state.save_tree(root)`, etc. — never knowing whether it's talking to Claude, a mock, or something else entirely.

## End-to-End Flow

```
CLI  →  creates adapters (LLM, State, VCS, BatchMCPServer)
     →  starts MCP server (SSE on localhost)
     →  injects into ParsingService, calls service.run()

Main Loop (per batch):
        → load state + tree (or initialize if first run)
        → compute batch end (token-based via tiktoken)
        → write raw_i.md (batch of raw lines)
        → setup MCP server state (raw content, open_stack, known_ids, etc.)
        → build prompt (raw content embedded + MCP tool instructions)
        → llm.invoke(mcp_config_path=...) with --system-prompt, --tools "", --strict-mcp-config
        → Haiku calls read_batch (metadata: open nodes, known IDs, context)
        → Haiku calls submit_clean (cleaned text + cutoff line)
            → server validates annotations, writes clean_i.md with cutoff + raw remainder
        → Haiku calls submit_result (structured metadata)
        → service reads result from MCP server
        → service parses annotations from clean_i.md
        → service-side validation (backup check)
        → process_batch_annotations() builds/extends domain tree
        → update PipelineState (open_stack, pending_edges)
        → save state + tree → git commit

Final:  → concatenate clean_i.md[before cutoff] → final.md
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
| `VCSPort`              | `GitAdapter`               | Git CLI subprocess            |
| `StatePort`            | `FilesystemStateStore`     | state.json + tree.json on disk|
| `BatchToolsPort`       | `BatchMCPServer`           | MCP SSE server (read/submit)  |

Tomorrow you could write `OpenAIAdapter` for `LLMPort`, `OpenCodeMCPAdapter` for `BatchToolsPort`, or `NoOpVCSAdapter` for dry runs — same ports, different adapters. The application layer wouldn't change.

## MCP Tools

Haiku interacts with three MCP tools instead of built-in Read/Write/Bash:

- **`read_batch`** — Returns batch metadata (chunk_id, open_stack, known_ids, context). Raw content is in the prompt.
- **`submit_clean(cleaned_text, cutoff_batch_line)`** — Submits cleaned markdown. Server validates annotations (token-based minimum, not line-based), appends cutoff marker + raw remainder, writes clean file. Returns validation result + alignment context.
- **`submit_result(chunk_id, cutoff_batch_line, n_lines_cleaned, notes)`** — Submits structured result. Replaces stdout JSON parsing.

The MCP server runs as an SSE server in a background thread, sharing StatePort with ParsingService. Claude CLI connects via `--mcp-config` with `--system-prompt` (overrides default to skip memory/CLAUDE.md), `--tools ""` (no built-in tools), and `--strict-mcp-config`.
