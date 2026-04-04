from claude_parser.application.tokens import approximate_claude_tokens
import logging

from claude_parser.application.llm_response_parser import extract_json_from_stream
from claude_parser.application.pipeline_state import PipelineState
from claude_parser.application.prompt_builder import build_batch_prompt
from claude_parser.config import ParserConfig
from claude_parser.domain.annotation_parser import parse_annotations
from claude_parser.domain.annotation_tree_builder import process_batch_annotations
from claude_parser.domain.node import TreeDict
from claude_parser.domain.validator import validate_annotations
from claude_parser.ports.llm import LLMPort
from claude_parser.ports.state import StatePort
from claude_parser.ports.vcs import VCSPort

logger = logging.getLogger(__name__)

_BATCH_TOOLS = ["Write", "Bash"]
_CHARS_PER_TOKEN = 4


class ParsingService:
    def __init__(
        self,
        config: ParserConfig,
        llm: LLMPort,
        state: StatePort,
        vcs: VCSPort,
    ):
        self.config = config
        self.llm = llm
        self.state = state
        self.vcs = vcs

    def run(self) -> None:
        self.state.init_dirs()
        self.vcs.init_repo()

        self._run_main_loop()
        self._final_merge()

    def _run_main_loop(self) -> None:
        raw_lines = self._read_raw_lines()
        total_lines = len(raw_lines)

        # Load or initialize state
        pipeline_state = self.state.load_state() if self.config.resume else None
        if pipeline_state is None:
            pipeline_state = PipelineState(next_start_line=0, next_chunk_id=0)

        tree_result = self.state.load_tree() if self.config.resume else None
        if tree_result is not None:
            root, tree_dict = tree_result
        else:
            tree_dict = TreeDict()
            root = None

        logger.info(
            "Starting main loop at line %d of %d",
            pipeline_state.next_start_line,
            total_lines,
        )

        sections_completed = 0
        while pipeline_state.next_start_line < total_lines:
            if (
                self.config.max_sections is not None
                and sections_completed >= self.config.max_sections
            ):
                logger.info(
                    "Reached max_sections limit (%d).", self.config.max_sections
                )
                break

            start = pipeline_state.next_start_line
            end = self._compute_batch_end(raw_lines, start)
            chunk_id = f"chunk_{pipeline_state.next_chunk_id:03d}"
            batch_num = pipeline_state.next_chunk_id

            logger.info(
                "[%s] Processing raw lines %d–%d",
                chunk_id,
                start + 1,
                end,
            )

            # Write raw batch file
            batch_content = "".join(raw_lines[start:end])
            self.state.write_raw_batch(batch_num, batch_content)
            raw_batch_path = self.state.resolve_raw_path(batch_num)

            # Build context from previous clean file
            context_text = self.state.get_context_lines(
                batch_num,
                self.config.context_lines,
            )

            # Read memory if exists
            memory_text = self.state.read_memory()

            clean_path = self.state.resolve_clean_path(batch_num)
            known_ids = list(tree_dict._data.keys())

            prompt = build_batch_prompt(
                raw_path=raw_batch_path,
                clean_path=clean_path,
                chunk_id=chunk_id,
                raw_start=start + 1,
                raw_end=end,
                raw_line_count=end - start,
                open_stack=pipeline_state.open_stack,
                context_text=context_text,
                memory_text=memory_text,
                known_ids=known_ids,
                config=self.config,
            )

            if self.config.dry_run:
                logger.info("DRY RUN — Batch prompt:\n%s", prompt[:500])
                break

            # Invoke Haiku
            result = self.llm.invoke(
                prompt=prompt,
                model=self.config.task_model,
                allowed_tools=_BATCH_TOOLS,
                add_dirs=[self.config.state_dir],
                timeout=self.config.timeout,
            )

            # Save log
            self.state.write_log(chunk_id, result.stdout)

            if not result.success:
                failure_content = result.stdout or f"stderr: {result.stderr}"
                self.state.write_failure(chunk_id, failure_content)
                raise RuntimeError(
                    f"[{chunk_id}] LLM invocation failed. "
                    f"See failures/{chunk_id}_raw_response.txt"
                )

            # Parse LLM's JSON output for cutoff info
            metadata = extract_json_from_stream(result.stdout)
            cutoff_raw_line = end  # default: processed everything
            if metadata and "cutoff_raw_line" in metadata:
                reported = metadata["cutoff_raw_line"]
                if isinstance(reported, int):
                    if reported < start:
                        # LLM reported batch-relative line, convert to source line
                        cutoff_raw_line = start + reported
                        logger.warning(
                            "[%s] cutoff %d < batch start %d, treating as batch-relative → %d",
                            chunk_id,
                            reported,
                            start,
                            cutoff_raw_line,
                        )
                    else:
                        cutoff_raw_line = reported
                    # Clamp to batch bounds
                    cutoff_raw_line = max(start + 1, min(cutoff_raw_line, end))

            # Read and parse the clean file
            if not self.state.clean_batch_exists(batch_num):
                self.state.write_failure(chunk_id, result.stdout)
                raise RuntimeError(
                    f"[{chunk_id}] Clean file not written by LLM: {clean_path}. "
                    f"See failures/{chunk_id}_raw_response.txt"
                )

            clean_text = self.state.read_clean_batch(batch_num)
            assert clean_text is not None  # guarded by clean_batch_exists above
            clean_line_count = len(clean_text.splitlines())

            # Parse annotations
            events = parse_annotations(clean_text)

            # Service-side validation (last-resort safety net)
            validation = validate_annotations(events, known_ids=set(known_ids))
            if not validation.valid:
                self.state.write_failure(chunk_id, result.stdout)
                raise RuntimeError(
                    f"[{chunk_id}] Service-side annotation validation failed: "
                    f"{validation.errors}. "
                    f"See failures/{chunk_id}_raw_response.txt"
                )

            if validation.warnings:
                for w in validation.warnings:
                    logger.warning("[%s] %s", chunk_id, w)

            # Build/extend tree
            chunk_number = pipeline_state.next_chunk_id
            try:
                fragment = process_batch_annotations(
                    events,
                    tree_dict,
                    pipeline_state.open_stack,
                    chunk_number,
                    clean_line_count,
                )
            except (ValueError, KeyError) as e:
                self.state.write_failure(chunk_id, result.stdout)
                raise RuntimeError(
                    f"[{chunk_id}] Tree building failed: {e}. "
                    f"See failures/{chunk_id}_raw_response.txt"
                ) from e

            if root is None and tree_dict.root_node is not None:
                root = tree_dict.root_node

            # Update state
            pipeline_state.next_start_line = cutoff_raw_line
            pipeline_state.next_chunk_id += 1
            pipeline_state.open_stack = fragment.open_stack
            pipeline_state.last_closed_node_id = fragment.last_closed_node_id

            # Save and commit
            self.state.save_state(pipeline_state)
            if root is not None:
                self.state.save_tree(root)
            self.vcs.commit_all(chunk_id)
            sections_completed += 1

            logger.info(
                "[%s] Done. new=%d closed=%d open=%d cutoff=%d",
                chunk_id,
                len(fragment.new_nodes),
                len(fragment.closed_nodes),
                len(fragment.open_stack),
                cutoff_raw_line,
            )

        logger.info("Main loop complete.")

    def _compute_batch_end(self, raw_lines: list[str], start: int) -> int:
        tokens = 0
        raw_lines
        for i in range(start, len(raw_lines)):
            tokens += approximate_claude_tokens(raw_lines[i])
            if tokens >= self.config.batch_tokens:
                return i + 1
        return len(raw_lines)

    def _final_merge(self) -> None:
        """Concatenate all clean files (before cutoff) into final.md."""
        content = self.state.read_all_clean_before_cutoff()
        if not content:
            logger.info("No clean files to merge.")
            return
        self.state.write_final(content)
        logger.info("Final merge complete.")

    def _read_raw_lines(self) -> list[str]:
        with open(self.config.raw_path, encoding="utf-8") as f:
            return f.readlines()
