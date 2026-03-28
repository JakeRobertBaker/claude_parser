from dataclasses import dataclass


@dataclass
class ParserConfig:
    raw_path: str
    state_dir: str
    task_model: str = "haiku"
    phase0_model: str = "haiku"
    section_stride: int = 450
    overlap_lines: int = 15
    timeout: int = 300
    allowed_tools: str = "Read,Write,Glob"
    dry_run: bool = False
    resume: bool = False
    max_sections: int | None = None
