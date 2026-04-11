"""High-level orchestration for the parsing loop."""

import logging

from claude_parser.application.prompt_builder import build_batch_prompt
from claude_parser.application.run_engine import (
    advance,
    clamp_cutoff,
    complete,
    plan_next,
)
from claude_parser.application.tokens import approximate_claude_tokens
from claude_parser.config import ParserConfig
from claude_parser.domain.annotation_parser import parse_annotations
from claude_parser.domain.annotation_tree_builder import (
    has_visible_nodes,
    process_batch_annotations,
)
from claude_parser.domain.validator import validate_annotations
from claude_parser.ports.batch_tools import BatchToolsPort
from claude_parser.ports.llm import LLMPort
from claude_parser.ports.state import BatchContext, StatePort

logger = logging.getLogger(__name__)


class ParsingService:
    """Runs the plan -> LLM -> validate -> persist loop for each batch."""

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
        raw_lines = self.state.raw_lines
        snapshot = self.state.snapshot

        while not complete(snapshot, len(raw_lines)):
            if (
                self.config.max_sections is not None
                and snapshot.sections_completed >= self.config.max_sections
            ):
                logger.info(
                    "Reached max_sections limit (%d).", self.config.max_sections
                )
                break

            plan = plan_next(
                snapshot,
                raw_lines,
                self.config.batch_tokens,
                approximate_claude_tokens,
            )

            self.state.write_raw_batch(plan.ordinal, plan.raw_content)
            context = BatchContext(
                raw_content=plan.raw_content,
                raw_start_line=plan.start_line,
                raw_end_line=plan.end_line,
                raw_line_count=plan.raw_line_count,
                raw_token_count=plan.raw_token_count,
                prior_clean_tail=self.state.read_prior_clean_tail(
                    plan.ordinal, self.config.context_lines
                ),
                memory_text=self.state.read_memory(),
                clean_token_target=plan.clean_token_target,
            )
            self.batch_tools.begin_batch(
                context=context,
                known_ids=self.state.known_ids,
                tree_dict=self.state.tree_dict,
                current_ordinal=plan.ordinal,
            )
            seq = plan.chunk_id

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

            self.state.write_log(seq, result.stdout)

            if not result.success:
                self.state.write_failure(
                    seq, result.stdout or f"stderr: {result.stderr}"
                )
                raise RuntimeError(
                    f"[{seq}] LLM invocation failed. "
                    f"See failures/{seq}_raw_response.txt"
                )

            if not self.batch_tools.succeeded():
                self.state.write_failure(seq, result.stdout)
                raise RuntimeError(
                    f"[{seq}] No result submitted by LLM. "
                    f"See failures/{seq}_raw_response.txt"
                )

            if not self.state.clean_batch_exists(plan.ordinal):
                self.state.write_failure(seq, result.stdout)
                raise RuntimeError(
                    f"[{seq}] Clean file not found after LLM invocation. "
                    f"See failures/{seq}_raw_response.txt"
                )

            clean_text = self.state.read_clean_batch(plan.ordinal)
            assert clean_text is not None
            clean_line_count = len(clean_text.splitlines())

            events = parse_annotations(clean_text)

            validation = validate_annotations(
                events,
                known_ids=set(self.state.known_ids),
                cleaned_text=clean_text,
                has_existing_nodes=has_visible_nodes(self.state.tree_dict),
            )
            if not validation.valid:
                self.state.write_failure(seq, result.stdout)
                raise RuntimeError(
                    f"[{seq}] Service-side annotation validation failed: "
                    f"{validation.errors}. "
                    f"See failures/{seq}_raw_response.txt"
                )

            if validation.warnings:
                for warning in validation.warnings:
                    logger.warning("[%s] %s", seq, warning)

            try:
                apply_result = process_batch_annotations(
                    events,
                    self.state.tree_dict,
                    plan.ordinal,
                    clean_line_count,
                )
            except (ValueError, KeyError) as exc:
                self.state.write_failure(seq, result.stdout)
                raise RuntimeError(
                    f"[{seq}] Tree building failed: {exc}. "
                    f"See failures/{seq}_raw_response.txt"
                ) from exc

            committed_source_line = self.batch_tools.committed_source_line()
            if committed_source_line is None:
                self.state.write_failure(seq, result.stdout)
                raise RuntimeError(
                    f"[{seq}] Batch commit did not provide a cutoff source line. "
                    f"See failures/{seq}_raw_response.txt"
                )

            snapshot = advance(snapshot, clamp_cutoff(plan, committed_source_line))
            self.state.save_snapshot(snapshot)
            self.state.save_tree()
            self.state.commit_all(seq)

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
