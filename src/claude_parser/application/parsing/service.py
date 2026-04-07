import logging

from claude_parser.application.prompt_builder import build_batch_prompt
from claude_parser.config import ParserConfig
from claude_parser.domain.annotation_parser import parse_annotations
from claude_parser.domain.annotation_tree_builder import (
    has_visible_nodes,
    process_batch_annotations,
)
from claude_parser.domain.validator import validate_annotations
from claude_parser.ports.batch_tools import BatchToolsPort
from claude_parser.ports.llm import LLMPort
from claude_parser.ports.state import StatePort

logger = logging.getLogger(__name__)


class ParsingService:
    def __init__(
        self,
        config: ParserConfig,
        llm: LLMPort,
        state: StatePort,
        batch_tools: BatchToolsPort,
    ):
        self.config = config
        self.llm = llm
        self.state = state
        self.batch_tools = batch_tools

    def run(self) -> None:
        self.state.init_repo()
        self._run_main_loop()
        self._final_merge()

    def _run_main_loop(self) -> None:
        while not self.state.complete:
            if (
                self.config.max_sections is not None
                and self.state.sections_completed >= self.config.max_sections
            ):
                logger.info(
                    "Reached max_sections limit (%d).", self.config.max_sections
                )
                break

            self.state.prepare_next(self.config.batch_tokens, self.config.context_lines)
            self.batch_tools.prepare()
            seq = self.state.current_id

            prompt = build_batch_prompt()

            if self.config.dry_run:
                logger.info("DRY RUN — Batch prompt:\n%s", prompt[:500])
                break

            result = self.llm.invoke(
                prompt=prompt,
                model=self.config.task_model,
                allowed_tools=[],
                add_dirs=[],
                timeout=self.config.timeout,
                mcp_config_path=self.batch_tools.mcp_config_path,
            )

            self.state.write_log(result.stdout)

            if not result.success:
                self.state.write_failure(result.stdout or f"stderr: {result.stderr}")
                raise RuntimeError(
                    f"[{seq}] LLM invocation failed. "
                    f"See failures/{seq}_raw_response.txt"
                )

            if not self.batch_tools.succeeded():
                self.state.write_failure(result.stdout)
                raise RuntimeError(
                    f"[{seq}] No result submitted by LLM. "
                    f"See failures/{seq}_raw_response.txt"
                )

            if not self.state.clean_batch_exists():
                self.state.write_failure(result.stdout)
                raise RuntimeError(
                    f"[{seq}] Clean file not found after LLM invocation. "
                    f"See failures/{seq}_raw_response.txt"
                )

            clean_text = self.state.read_clean_batch()
            assert clean_text is not None
            clean_line_count = len(clean_text.splitlines())

            # Domain: parse and validate annotations
            events = parse_annotations(clean_text)

            validation = validate_annotations(
                events,
                known_ids=set(self.state.known_ids),
                cleaned_text=clean_text,
                has_existing_nodes=has_visible_nodes(self.state.tree_dict),
            )
            if not validation.valid:
                self.state.write_failure(result.stdout)
                raise RuntimeError(
                    f"[{seq}] Service-side annotation validation failed: "
                    f"{validation.errors}. "
                    f"See failures/{seq}_raw_response.txt"
                )

            if validation.warnings:
                for w in validation.warnings:
                    logger.warning("[%s] %s", seq, w)

            # Domain: build/extend tree
            try:
                apply_result = process_batch_annotations(
                    events,
                    self.state.tree_dict,
                    self.state.current_ordinal,
                    clean_line_count,
                )
            except (ValueError, KeyError) as e:
                self.state.write_failure(result.stdout)
                raise RuntimeError(
                    f"[{seq}] Tree building failed: {e}. "
                    f"See failures/{seq}_raw_response.txt"
                ) from e

            # Advance state (saves, commits)
            self.state.advance()

            logger.info(
                "[%s] Done. added=%d active_depth=%d",
                seq,
                apply_result.added_nodes,
                apply_result.active_depth,
            )

        logger.info("Main loop complete.")

    def _final_merge(self) -> None:
        content = self.state.read_all_clean_before_cutoff()
        if not content:
            logger.info("No clean files to merge.")
            return
        self.state.write_final(content)
        logger.info("Final merge complete.")
