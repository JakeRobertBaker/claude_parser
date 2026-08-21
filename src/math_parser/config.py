from dataclasses import dataclass


@dataclass
class ParserConfig:
    raw_path: str
    state_dir: str
    task_model: str | None = None
    batch_tokens: int = 16000
    prior_clean_context_tokens: int = 2000
    next_raw_context_tokens: int = 2000
    timeout: int = 600
    dry_run: bool = False
    resume: bool = False
    max_sections: int | None = None
    pi_debug_stream_log: bool = False
