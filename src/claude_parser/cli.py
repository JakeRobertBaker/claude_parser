import argparse
import logging
import sys

from claude_parser.adapters.claude_cli import ClaudeCLIAdapter
from claude_parser.adapters.filesystem_store import FilesystemStore
from claude_parser.adapters.git_adapter import GitAdapter
from claude_parser.application.parsing_service import ParsingService
from claude_parser.config import ParserConfig

logger = logging.getLogger("claude_parser")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Parse mathematics/science markdown into a structured tree.",
    )
    parser.add_argument(
        "--raw", required=True,
        help="Path to the raw MinerU-generated markdown file.",
    )
    parser.add_argument(
        "--state", required=True,
        help="Path to the state directory (created if needed, git-tracked).",
    )
    parser.add_argument(
        "--resume", action="store_true",
        help="Resume from the last saved progress.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print prompts without invoking Claude.",
    )
    parser.add_argument(
        "--task-model", default="haiku",
        help="Model for section processing (default: haiku).",
    )
    parser.add_argument(
        "--phase0-model", default="haiku",
        help="Model for Phase 0 front matter analysis (default: haiku).",
    )
    parser.add_argument(
        "--stride", type=int, default=450,
        help="Lines per section window (default: 450).",
    )
    parser.add_argument(
        "--max-sections", type=int, default=None,
        help="Stop after N successful sections (useful for testing).",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Enable debug logging.",
    )

    args = parser.parse_args()

    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    config = ParserConfig(
        raw_path=args.raw,
        state_dir=args.state,
        task_model=args.task_model,
        phase0_model=args.phase0_model,
        section_stride=args.stride,
        dry_run=args.dry_run,
        resume=args.resume,
        max_sections=args.max_sections,
    )

    llm = ClaudeCLIAdapter()
    store = FilesystemStore(config.state_dir)
    vcs = GitAdapter(config.state_dir)

    service = ParsingService(
        config=config,
        llm=llm,
        store=store,
        vcs=vcs,
    )

    try:
        service.run()
    except RuntimeError as e:
        logger.error("%s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
