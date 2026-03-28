import json
import logging
import os

from claude_parser.adapters.claude_cli import extract_json_from_stream
from claude_parser.adapters.chunk_lines.json_adapter import (
    tree_from_dict as chunk_lines_tree_from_dict,
    tree_to_dict,
)
from claude_parser.adapters.filesystem_store import FilesystemStore
from claude_parser.application.merge import (
    build_dependency_report,
    check_duplicate_ids,
    merge_chunk,
    validate_metadata,
)
from claude_parser.application.progress import ProgressState
from claude_parser.application.prompt_builder import (
    build_phase0_prompt,
    build_retry_prompt,
    build_section_prompt,
)
from claude_parser.config import ParserConfig
from claude_parser.domain.node import Node, TreeDict
from claude_parser.ports.llm import LLMPort
from claude_parser.ports.vcs import VCSPort

logger = logging.getLogger(__name__)


class ParsingService:
    def __init__(
        self,
        config: ParserConfig,
        llm: LLMPort,
        store: FilesystemStore,
        vcs: VCSPort,
    ):
        self.config = config
        self.llm = llm
        self.store = store
        self.vcs = vcs

    def run(self) -> None:
        self.store.init()
        self.vcs.init_repo()

        if not self.config.resume:
            self._run_phase0()
        self._run_main_loop()

        result = self.store.load()
        if result:
            root, tree_dict = result
            report = build_dependency_report(tree_dict)
            report_path = os.path.join(self.store.state_dir, "dependency_report.json")
            with open(report_path, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2)
            logger.info("Dependency report saved to %s", report_path)

    def _run_phase0(self) -> None:
        logger.info("Phase 0: Analyzing front matter...")
        raw_path = os.path.abspath(self.config.raw_path)
        prompt = build_phase0_prompt(raw_path, self.config)

        if self.config.dry_run:
            logger.info("DRY RUN — Phase 0 prompt:\n%s", prompt)
            return

        result = self.llm.invoke(
            prompt=prompt,
            model=self.config.phase0_model,
            allowed_tools=self.config.allowed_tools.split(","),
            add_dirs=[os.path.dirname(raw_path)],
            timeout=self.config.timeout,
        )

        if not result.success:
            logger.error("Phase 0 failed: %s", result.stderr[:200])
            raise RuntimeError("Phase 0: Claude invocation failed")

        metadata = extract_json_from_stream(result.stdout)
        if metadata is None:
            self._save_failure("phase0", result.stdout)
            raise RuntimeError("Phase 0: Could not parse JSON from output")

        if "hierarchy" not in metadata or "content_start_line" not in metadata:
            self._save_failure("phase0", result.stdout)
            raise RuntimeError("Phase 0: Missing 'hierarchy' or 'content_start_line'")

        root, tree_dict = chunk_lines_tree_from_dict(metadata["hierarchy"])

        self.store.save(root)
        progress = ProgressState(
            next_start_line=metadata["content_start_line"] - 1,  # 0-indexed
            next_chunk_id=0,
            section_index=0,
        )
        self.store.save_progress(progress)
        self.vcs.commit_all("Phase 0: skeleton hierarchy")
        logger.info(
            "Phase 0 complete. Content starts at line %d. %d skeleton nodes.",
            metadata["content_start_line"], len(tree_dict),
        )

    def _run_main_loop(self) -> None:
        raw_path = os.path.abspath(self.config.raw_path)
        raw_lines = self._read_raw_lines()

        progress = self.store.load_progress()
        if progress is None:
            raise RuntimeError("No progress state found. Run without --resume first.")

        result = self.store.load()
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
                prompt = build_section_prompt(
                    raw_path, start, end, chunk_id_str,
                    overlap_text, tree_json, self.config,
                )
                logger.info("DRY RUN — Section prompt:\n%s", prompt[:500])
                break

            metadata = self._process_section(
                raw_path, start, end, chunk_id_str,
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
                    progress.next_start_line = end
                    progress.section_index += 1
                    self.store.save_progress(progress)
                    continue

                cutoff = metadata.get("cutoff_line", end)
                progress.next_start_line = cutoff
                progress.next_chunk_id += 1
                progress.section_index += 1

                self.store.save(root)
                self.store.save_progress(progress)
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
                self.store.save_progress(progress)

        logger.info("Main loop complete.")

    def _process_section(
        self,
        raw_path: str,
        start: int,
        end: int,
        chunk_id: str,
        overlap_text: str,
        root: Node,
        tree_dict: TreeDict,
    ) -> dict | None:
        tree_json = json.dumps(tree_to_dict(root), indent=2)
        prompt = build_section_prompt(
            raw_path, start, end, chunk_id,
            overlap_text, tree_json, self.config,
        )

        # Replace placeholder with actual chunks dir
        prompt = prompt.replace("{state_chunks_dir}", self.store.chunks_dir)

        result = self.llm.invoke(
            prompt=prompt,
            model=self.config.task_model,
            allowed_tools=self.config.allowed_tools.split(","),
            add_dirs=[os.path.dirname(raw_path), self.store.state_dir],
            timeout=self.config.timeout,
        )

        log_path = os.path.join(
            self.store.logs_dir, f"{chunk_id}.json",
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

        # Check for duplicate IDs — retry once with correction
        duplicates = check_duplicate_ids(tree_dict, metadata)
        if duplicates:
            logger.warning(
                "Duplicate IDs %s for %s, retrying...", duplicates, chunk_id,
            )
            retry_prompt = build_retry_prompt(prompt, duplicates)
            result = self.llm.invoke(
                prompt=retry_prompt,
                model=self.config.task_model,
                allowed_tools=self.config.allowed_tools.split(","),
                add_dirs=[os.path.dirname(raw_path), self.store.state_dir],
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

            still_dupes = check_duplicate_ids(tree_dict, metadata)
            if still_dupes:
                logger.error(
                    "Retry still has duplicate IDs %s for %s", still_dupes, chunk_id,
                )
                return None

        return metadata

    def _read_raw_lines(self) -> list[str]:
        with open(self.config.raw_path, encoding="utf-8") as f:
            return f.readlines()

    def _save_failure(self, label: str, content: str) -> None:
        path = os.path.join(self.store.failures_dir, f"{label}_raw_response.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        logger.debug("Saved failure log to %s", path)
