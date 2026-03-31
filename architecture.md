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
│
├── domain/                             # Pure business logic, ZERO external deps
│   ├── node.py                         # Node, TreeDict, NodeType — core tree entities
│   ├── content.py                      # Content value object (chunk_number, first_line, last_line)
│   ├── content_bound.py                # ContentBound — spatial bounds with union/intersect
│   ├── partition.py                    # ContentPartition — overlap validation
│   └── protocols.py                    # ContentBase protocol (ordering + truthiness)
│
├── ports/                              # Driven-side interfaces (Protocol classes)
│   ├── llm.py                          # LLMPort — invoke(prompt, model, ...) → LLMResult
│   ├── vcs.py                          # VCSPort — init_repo(), commit_all(message)
│   ├── tree_repository.py              # TreeRepositoryPort — load/save the tree
│   └── progress_store.py               # ProgressStorePort — load/save progress state
│
├── application/                        # Use-case orchestration
│   ├── parsing_service.py              # ParsingService — main entry point, depends on ports only
│   ├── merge.py                        # Chunk merging + domain validation
│   ├── serialization.py                # Tree ↔ dict serialization (used by service + adapters)
│   ├── llm_response_parser.py          # Extract JSON from Claude's stream-json output
│   ├── prompt_builder.py               # Prompt assembly from templates
│   ├── prompt_templates.py             # PHASE0_TEMPLATE, SECTION_TEMPLATE
│   └── progress.py                     # ProgressState dataclass
│
├── adapters/                           # Infrastructure implementations
│   ├── claude_cli.py                   # LLMPort impl — wraps `claude` CLI via subprocess
│   ├── git_adapter.py                  # VCSPort impl — wraps `git` CLI via subprocess
│   └── filesystem_store.py             # TreeRepositoryPort + ProgressStorePort impl — JSON files
│
tests/
├── test_tree.py                        # Node construction, ordering rules, propagation
├── test_content.py                     # Content ordering, ContentPartition overlap checks
├── test_json_adapter.py                # Tree deserialization from fixture files
├── test_serialization_roundtrip.py     # Serialize → deserialize → verify identity
└── test_merge.py                       # merge_chunk, validate_metadata, dependency report
```

## Wiring Example

The CLI creates concrete adapters and injects them into the service via port-typed parameters:

```python
# cli.py — the only place that knows which adapter goes in which port
llm   = ClaudeCLIAdapter()              # plug this adapter...
store = FilesystemStore(config.state_dir)
store.init()
vcs   = GitAdapter(config.state_dir)

service = ParsingService(
    config=config,
    llm=llm,                            # ...into LLMPort
    tree_repo=store,                    # ...into TreeRepositoryPort
    progress_store=store,               # ...into ProgressStorePort
    vcs=vcs,                            # ...into VCSPort
)
```

`ParsingService` only sees the port shapes. It calls `self.llm.invoke(...)`, `self.tree_repo.save(root)`, etc. — never knowing whether it's talking to Claude, a mock, or something else entirely.

## End-to-End Flow

```
CLI  →  creates adapters, injects into ParsingService
     →  calls service.run()

Phase 0:  read first 500 lines of raw markdown
        → build phase0 prompt → llm.invoke() (no tools)
        → parse JSON → deserialize skeleton tree → save tree → git commit

Main Loop (per section):
        → load progress + tree → calculate window [start, end)
        → build section prompt (with overlap) → llm.invoke(tools=["Write"])
        → Claude writes chunk file + returns metadata JSON
        → validate metadata → check for duplicate IDs (retry if needed)
        → merge_chunk() into domain tree (Node.add_content / add_child)
        → save tree + progress → git commit

Final:  → build + save dependency_report.json
```

## Ports & Adapters Analogy

A **port** is a socket — it defines what shape plugs in. An **adapter** is the dongle that connects a specific thing to that socket.

| Port (socket)          | Adapter (dongle)       | What it connects              |
|------------------------|------------------------|-------------------------------|
| `LLMPort`              | `ClaudeCLIAdapter`     | Claude CLI subprocess         |
| `VCSPort`              | `GitAdapter`           | Git CLI subprocess            |
| `TreeRepositoryPort`   | `FilesystemStore`      | tree.json on disk             |
| `ProgressStorePort`    | `FilesystemStore`      | progress.json on disk         |

Tomorrow you could write `OpenAIAdapter` for `LLMPort` or `NoOpVCSAdapter` for dry runs — same ports, different adapters. The application layer wouldn't change.
