import json
import logging
import os

from claude_parser.application.llm_response_parser import extract_json_from_stream
from claude_parser.application.merge import (
    build_dependency_report,
    check_intra_duplicates,
    merge_chunk,
    validate_chunk_file,
    validate_metadata,
)
from claude_parser.application.progress import ProgressState
from claude_parser.application.prompt_builder import (
    build_phase0_prompt,
    build_retry_prompt,
    build_section_prompt,
)
from claude_parser.application.serialization import tree_from_dict, tree_to_dict
from claude_parser.config import ParserConfig
from claude_parser.domain.node import Node, TreeDict
from claude_parser.ports.llm import LLMPort
from claude_parser.ports.progress_store import ProgressStorePort
from claude_parser.ports.tree_repository import TreeRepositoryPort
from claude_parser.ports.vcs import VCSPort

logger = logging.getLogger(__name__)

# Phase 0 only prints JSON — no tool calls needed.
_PHASE0_TOOLS: list[str] = []
# Section processing needs Write to create the chunk .md file.
_SECTION_TOOLS = ["Write"]


class ParsingService:
    def __init__(
        self,
        config: ParserConfig,
        llm: LLMPort,
        tree_repo: TreeRepositoryPort,
        progress_store: ProgressStorePort,
        vcs: VCSPort,
    ):
        self.config = config
        self.llm = llm
        self.tree_repo = tree_repo
        self.progress_store = progress_store
        self.vcs = vcs

        self._chunks_dir = os.path.join(config.state_dir, "chunks")
        self._logs_dir = os.path.join(config.state_dir, "logs")
        self._failures_dir = os.path.join(config.state_dir, "failures")

    def run(self) -> None:
        for d in [self._chunks_dir, self._logs_dir, self._failures_dir]:
            os.makedirs(d, exist_ok=True)
        self.vcs.init_repo()

        if not self.config.resume:
            self._run_phase0()
        self._run_main_loop()

        result = self.tree_repo.load()
        if result:
            root, tree_dict = result
            report = build_dependency_report(tree_dict)
            report_path = os.path.join(self.config.state_dir, "dependency_report.json")
            with open(report_path, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2)
            logger.info("Dependency report saved to %s", report_path)

    def _run_phase0(self) -> None:
        logger.info("Phase 0: Analyzing front matter...")
        raw_lines = self._read_raw_lines()
        raw_content = "".join(raw_lines[:500])
        prompt = build_phase0_prompt(raw_content, self.config)

        if self.config.dry_run:
            logger.info("DRY RUN — Phase 0 prompt:\n%s", prompt)
            return

        result = self.llm.invoke(
            prompt=prompt,
            model=self.config.phase0_model,
            allowed_tools=_PHASE0_TOOLS,
            add_dirs=[],
            timeout=self.config.timeout,
        )

        if not result.success:
            logger.error("Phase 0 failed: %s", result.stderr[:200])
            raise RuntimeError("Phase 0: Claude invocation failed")

        metadata = extract_json_from_stream(result.stdout)
        if metadata is None:
            self._save_failure("phase0", result.stdout)
            raise RuntimeError("Phase 0: Could not parse JSON from output")

        if "hierarchy" not in metadata:
            self._save_failure("phase0", result.stdout)
            raise RuntimeError("Phase 0: Missing 'hierarchy' in output")

        root, tree_dict = tree_from_dict(metadata["hierarchy"])

        self.tree_repo.save(root)
        progress = ProgressState(
            next_start_line=0,
            next_chunk_id=0,
            section_index=0,
        )
        self.progress_store.save_progress(progress)
        self.vcs.commit_all("Phase 0: skeleton hierarchy")
        logger.info("Phase 0 complete. %d skeleton nodes.", len(tree_dict))

    def _run_main_loop(self) -> None:
        raw_lines = self._read_raw_lines()

        progress = self.progress_store.load_progress()
        if progress is None:
            raise RuntimeError("No progress state found. Run without --resume first.")

        result = self.tree_repo.load()
        if result is None:
            raise RuntimeError("No tree state found. Run without --resume first.")
        root, tree_dict = result

        total_lines = len(raw_lines)
        logger.info(
            "Starting main loop at line %d of %d",
            progress.next_start_line, total_lines,
        )

        sections_completed = 0
        while progress.next_start_line < total_lines:
            if (
                self.config.max_sections is not None
                and sections_completed >= self.config.max_sections
            ):
                logger.info(
                    "Reached max_sections limit (%d). Stopping early.",
                    self.config.max_sections,
                )
                break

            start = progress.next_start_line
            end = min(start + self.config.section_stride, total_lines)
            chunk_id_str = f"chunk_{progress.next_chunk_id:03d}"

            overlap_text = ""
            if start > 0 and self.config.overlap_lines > 0:
                overlap_start = max(0, start - self.config.overlap_lines)
                overlap_text = "".join(raw_lines[overlap_start:start])

            logger.info(
                "[Section %d] Processing lines %d-%d as %s",
                progress.section_index, start + 1, end, chunk_id_str,
            )

            if self.config.dry_run:
                tree_json = json.dumps(tree_to_dict(root), indent=2)
                window_content = "".join(raw_lines[start:end])
                chunk_path = os.path.join(
                    self._chunks_dir, f"{chunk_id_str}.md",
                )
                prompt = build_section_prompt(
                    window_content, start, end, chunk_id_str,
                    overlap_text, tree_json, chunk_path,
                    self.config,
                )
                logger.info("DRY RUN — Section prompt:\n%s", prompt[:500])
                break

            metadata = self._process_section(
                raw_lines, start, end, chunk_id_str,
                overlap_text, root, tree_dict,
            )

            if metadata is not None:
                try:
                    chunk_number = progress.next_chunk_id
                    merge_chunk(tree_dict, root, metadata, chunk_number)
                except (ValueError, KeyError) as e:
                    logger.error(
                        "[Section %d] Merge failed: %s", progress.section_index, e,
                    )
                    self._save_failure(
                        f"section_{progress.section_index:03d}",
                        json.dumps(metadata, indent=2),
                    )
                    cutoff = metadata.get("cutoff_line", end)
                    progress.next_start_line = cutoff
                    progress.section_index += 1
                    self.progress_store.save_progress(progress)
                    continue

                cutoff = metadata.get("cutoff_line", end)
                progress.next_start_line = cutoff
                progress.next_chunk_id += 1
                progress.section_index += 1

                self.tree_repo.save(root)
                self.progress_store.save_progress(progress)
                self.vcs.commit_all(f"{chunk_id_str}")
                sections_completed += 1
                logger.info("[Section %d] Committed %s", progress.section_index - 1, chunk_id_str)
            else:
                logger.warning(
                    "[Section %d] Failed, advancing past stride",
                    progress.section_index,
                )
                progress.next_start_line = end
                progress.section_index += 1
                self.progress_store.save_progress(progress)

        logger.info("Main loop complete.")

    def _write_window(
        self, raw_lines: list[str], start: int, end: int, chunk_id: str,
    ) -> str:
        """Write window to disk for debug logging (not used in the prompt)."""
        window_path = os.path.join(self.config.state_dir, f"current_window_{chunk_id}.md")
        with open(window_path, "w", encoding="utf-8") as f:
            f.writelines(raw_lines[start:end])
        return window_path

    def _process_section(
        self,
        raw_lines: list[str],
        start: int,
        end: int,
        chunk_id: str,
        overlap_text: str,
        root: Node,
        tree_dict: TreeDict,
    ) -> dict | None:
        # Write window to disk for debugging
        self._write_window(raw_lines, start, end, chunk_id)

        window_content = "".join(raw_lines[start:end])
        tree_json = json.dumps(tree_to_dict(root), indent=2)
        chunk_path = os.path.join(self._chunks_dir, f"{chunk_id}.md")
        prompt = build_section_prompt(
            window_content, start, end, chunk_id,
            overlap_text, tree_json, chunk_path,
            self.config,
        )

        result = self.llm.invoke(
            prompt=prompt,
            model=self.config.task_model,
            allowed_tools=_SECTION_TOOLS,
            add_dirs=[self.config.state_dir],
            timeout=self.config.timeout,
        )

        log_path = os.path.join(
            self._logs_dir, f"{chunk_id}.json",
        )
        with open(log_path, "w", encoding="utf-8") as f:
            f.write(result.stdout)

        if not result.success:
            logger.error("Claude invocation failed for %s", chunk_id)
            return None

        metadata = extract_json_from_stream(result.stdout)
        if metadata is None:
            logger.error("Could not parse JSON for %s", chunk_id)
            self._save_failure(chunk_id, result.stdout)
            return None

        error = validate_metadata(metadata)
        if error:
            logger.error("Invalid metadata for %s: %s", chunk_id, error)
            self._save_failure(chunk_id, result.stdout)
            return None

        # Check for duplicate IDs within the output — retry once with correction
        duplicates = check_intra_duplicates(metadata)
        if duplicates:
            logger.warning(
                "Intra-duplicate IDs %s for %s, retrying...", duplicates, chunk_id,
            )
            retry_prompt = build_retry_prompt(prompt, duplicates)
            result = self.llm.invoke(
                prompt=retry_prompt,
                model=self.config.task_model,
                allowed_tools=_SECTION_TOOLS,
                add_dirs=[self.config.state_dir],
                timeout=self.config.timeout,
            )

            if not result.success:
                logger.error("Retry failed for %s", chunk_id)
                return None

            metadata = extract_json_from_stream(result.stdout)
            if metadata is None:
                logger.error("Retry: could not parse JSON for %s", chunk_id)
                return None

            error = validate_metadata(metadata)
            if error:
                logger.error("Retry: invalid metadata for %s: %s", chunk_id, error)
                return None

            still_dupes = check_intra_duplicates(metadata)
            if still_dupes:
                logger.error(
                    "Retry still has duplicate IDs %s for %s", still_dupes, chunk_id,
                )
                return None

        # Validate that chunk file matches metadata
        chunk_error = validate_chunk_file(metadata, chunk_path, start + 1, end)
        if chunk_error:
            logger.error("Chunk validation failed for %s: %s", chunk_id, chunk_error)
            self._save_failure(chunk_id, result.stdout)
            return None

        # Diagnostic logging
        self._log_chunk_diagnostics(chunk_id, metadata, chunk_path, start, end)

        return metadata

    def _log_chunk_diagnostics(
        self,
        chunk_id: str,
        metadata: dict,
        chunk_path: str,
        start: int,
        end: int,
    ) -> None:
        """Log diagnostic info about a processed chunk for debugging."""
        cutoff = metadata.get("cutoff_line", end)
        nodes = metadata.get("nodes", [])
        node_count = len(nodes)

        # Count actual lines in chunk file
        try:
            with open(chunk_path, encoding="utf-8") as f:
                actual_lines = sum(1 for _ in f)
        except FileNotFoundError:
            actual_lines = 0

        # Find content line range from metadata
        min_line = float("inf")
        max_line = 0
        for node_data in nodes:
            for content in node_data.get("content", []):
                first = content.get("first_line", 0)
                last = content.get("last_line", 0)
                if first < min_line:
                    min_line = first
                if last > max_line:
                    max_line = last

        raw_covered = cutoff - (start + 1) + 1

        logger.info(
            "[%s] cutoff=%d, raw_covered=%d, chunk_lines=%d, "
            "metadata_lines=%d-%d, nodes=%d",
            chunk_id, cutoff, raw_covered, actual_lines,
            min_line if min_line != float("inf") else 0,
            max_line, node_count,
        )

        # Log per-node summary
        for node_data in nodes:
            node_id = node_data.get("id", "?")
            content_ranges = [
                f"{c['first_line']}-{c['last_line']}"
                for c in node_data.get("content", [])
            ]
            logger.debug(
                "[%s]   node=%s type=%s content=%s",
                chunk_id, node_id,
                node_data.get("node_type", "existing"),
                ", ".join(content_ranges) if content_ranges else "none",
            )

    def _read_raw_lines(self) -> list[str]:
        with open(self.config.raw_path, encoding="utf-8") as f:
            return f.readlines()

    def _save_failure(self, label: str, content: str) -> None:
        path = os.path.join(self._failures_dir, f"{label}_raw_response.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        logger.debug("Saved failure log to %s", path)
