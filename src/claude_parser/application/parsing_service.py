import logging
import os

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

        self._clean_dir = os.path.join(config.state_dir, "clean")
        self._raw_dir = os.path.join(config.state_dir, "raw")
        self._logs_dir = os.path.join(config.state_dir, "logs")
        self._failures_dir = os.path.join(config.state_dir, "failures")
        self._memory_path = os.path.join(config.state_dir, "memory.md")

    def run(self) -> None:
        for d in [self._clean_dir, self._raw_dir, self._logs_dir, self._failures_dir]:
            os.makedirs(d, exist_ok=True)
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
            pipeline_state.next_start_line, total_lines,
        )

        sections_completed = 0
        while pipeline_state.next_start_line < total_lines:
            if (
                self.config.max_sections is not None
                and sections_completed >= self.config.max_sections
            ):
                logger.info("Reached max_sections limit (%d).", self.config.max_sections)
                break

            start = pipeline_state.next_start_line
            end = self._compute_batch_end(raw_lines, start)
            chunk_id = f"chunk_{pipeline_state.next_chunk_id:03d}"

            logger.info(
                "[%s] Processing raw lines %d–%d",
                chunk_id, start + 1, end,
            )

            # Write raw batch file (raw_i.md per notes spec)
            batch_num = pipeline_state.next_chunk_id
            raw_batch_path = os.path.join(self._raw_dir, f"raw_{batch_num}.md")
            with open(raw_batch_path, "w", encoding="utf-8") as f:
                f.writelines(raw_lines[start:end])

            # Build context from previous clean file
            context_text = self._get_context(pipeline_state)

            # Read memory if exists
            memory_text = ""
            if os.path.exists(self._memory_path):
                with open(self._memory_path, encoding="utf-8") as f:
                    memory_text = f.read()

            clean_path = os.path.join(self._clean_dir, f"clean_{batch_num}.md")
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
            log_path = os.path.join(self._logs_dir, f"{chunk_id}.json")
            with open(log_path, "w", encoding="utf-8") as f:
                f.write(result.stdout)

            if not result.success:
                logger.error("[%s] LLM invocation failed", chunk_id)
                self._save_failure(chunk_id, result.stdout)
                pipeline_state.next_start_line = end
                pipeline_state.next_chunk_id += 1
                self.state.save_state(pipeline_state)
                continue

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
                            chunk_id, reported, start, cutoff_raw_line,
                        )
                    else:
                        cutoff_raw_line = reported
                    # Clamp to batch bounds
                    cutoff_raw_line = max(start + 1, min(cutoff_raw_line, end))

            # Read and parse the clean file
            if not os.path.exists(clean_path):
                logger.error("[%s] Clean file not written: %s", chunk_id, clean_path)
                self._save_failure(chunk_id, result.stdout)
                pipeline_state.next_start_line = end
                pipeline_state.next_chunk_id += 1
                self.state.save_state(pipeline_state)
                continue

            with open(clean_path, encoding="utf-8") as f:
                clean_text = f.read()
            clean_line_count = len(clean_text.splitlines())

            # Parse annotations
            events = parse_annotations(clean_text)

            # Service-side validation
            validation = validate_annotations(events, known_ids=set(known_ids))
            if not validation.valid:
                logger.error(
                    "[%s] Annotation validation failed: %s",
                    chunk_id, validation.errors,
                )
                self._save_failure(chunk_id, result.stdout)
                pipeline_state.next_start_line = cutoff_raw_line
                pipeline_state.next_chunk_id += 1
                self.state.save_state(pipeline_state)
                continue

            if validation.warnings:
                for w in validation.warnings:
                    logger.warning("[%s] %s", chunk_id, w)

            # Build/extend tree
            chunk_number = pipeline_state.next_chunk_id
            try:
                fragment = process_batch_annotations(
                    events, tree_dict, pipeline_state.open_stack,
                    chunk_number, clean_line_count,
                )
            except (ValueError, KeyError) as e:
                logger.error("[%s] Tree building failed: %s", chunk_id, e)
                self._save_failure(chunk_id, result.stdout)
                pipeline_state.next_start_line = cutoff_raw_line
                pipeline_state.next_chunk_id += 1
                self.state.save_state(pipeline_state)
                continue

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
                chunk_id, len(fragment.new_nodes), len(fragment.closed_nodes),
                len(fragment.open_stack), cutoff_raw_line,
            )

        logger.info("Main loop complete.")

    def _compute_batch_end(self, raw_lines: list[str], start: int) -> int:
        """Walk lines from start, estimating ~4 chars/token, return end index."""
        char_budget = self.config.batch_tokens * _CHARS_PER_TOKEN
        chars = 0
        for i in range(start, len(raw_lines)):
            chars += len(raw_lines[i])
            if chars >= char_budget:
                return i + 1
        return len(raw_lines)

    def _get_context(self, state: PipelineState) -> str:
        """Get last N lines from previous clean file as context."""
        if state.next_chunk_id == 0:
            return ""
        prev_num = state.next_chunk_id - 1
        prev_clean_path = os.path.join(self._clean_dir, f"clean_{prev_num}.md")
        if not os.path.exists(prev_clean_path):
            return ""

        with open(prev_clean_path, encoding="utf-8") as f:
            lines = f.readlines()

        # Find cutoff line in previous file
        cutoff_idx = len(lines)
        for i, line in enumerate(lines):
            if "<!-- cutoff -->" in line:
                cutoff_idx = i
                break

        # Take last N lines before cutoff
        n = self.config.context_lines
        context_start = max(0, cutoff_idx - n)
        context_lines = lines[context_start:cutoff_idx]
        return "".join(context_lines)

    def _final_merge(self) -> None:
        """Concatenate all clean files (before cutoff) into final.md."""
        clean_files = sorted(
            f for f in os.listdir(self._clean_dir) if f.endswith(".md")
        )
        if not clean_files:
            logger.info("No clean files to merge.")
            return

        final_path = os.path.join(self.config.state_dir, "final.md")
        with open(final_path, "w", encoding="utf-8") as out:
            for clean_file in clean_files:
                chunk_path = os.path.join(self._clean_dir, clean_file)
                with open(chunk_path, encoding="utf-8") as f:
                    lines = f.readlines()

                # Find cutoff and write only lines before it
                for i, line in enumerate(lines):
                    if "<!-- cutoff -->" in line:
                        break
                    out.write(line)

        logger.info("Final merge complete: %s (%d files)", final_path, len(clean_files))

    def _read_raw_lines(self) -> list[str]:
        with open(self.config.raw_path, encoding="utf-8") as f:
            return f.readlines()

    def _save_failure(self, label: str, content: str) -> None:
        path = os.path.join(self._failures_dir, f"{label}_raw_response.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        logger.debug("Saved failure log to %s", path)
