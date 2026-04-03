from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PipelineState:
    next_start_line: int
    next_chunk_id: int
    open_stack: list[str] = field(default_factory=list)
    pending_edges: dict[str, list[str]] = field(default_factory=dict)
    last_closed_node_id: str | None = None
