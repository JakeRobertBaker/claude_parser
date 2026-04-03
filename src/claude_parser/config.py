from dataclasses import dataclass


@dataclass
class ParserConfig:
    raw_path: str
    state_dir: str
    task_model: str = "haiku"
    batch_tokens: int = 8000
    context_lines: int = 20
    timeout: int = 300
    dry_run: bool = False
    resume: bool = False
    max_sections: int | None = None
