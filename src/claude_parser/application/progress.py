from dataclasses import dataclass


@dataclass
class ProgressState:
    next_start_line: int
    next_chunk_id: int
    section_index: int
