import argparse
import logging
import sys

from claude_parser.adapters.llm.claude_cli import ClaudeCLIAdapter
from claude_parser.adapters.mcp.server import BatchMCPServer
from claude_parser.adapters.state.filesystem import FilesystemStateStore
from claude_parser.application.parsing import ParsingService
from claude_parser.config import ParserConfig

logger = logging.getLogger("claude_parser")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Parse mathematics/science markdown into a structured tree.",
    )
    parser.add_argument(
        "--raw",
        required=True,
        help="Path to the raw MinerU-generated markdown file.",
    )
    parser.add_argument(
        "--state",
        required=True,
        help="Path to the state directory (created if needed, git-tracked).",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume from the last saved progress.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print prompts without invoking Claude.",
    )
    parser.add_argument(
        "--task-model",
        default="haiku",
        help="Model for batch processing (default: haiku).",
    )
    parser.add_argument(
        "--batch-tokens",
        type=int,
        default=16000,
        help="Approximate token budget per batch (default: 16000).",
    )
    parser.add_argument(
        "--max-sections",
        type=int,
        default=None,
        help="Stop after N successful sections (useful for testing).",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=600,
        help="Timeout in seconds per LLM invocation (default: 600).",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
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
        batch_tokens=args.batch_tokens,
        timeout=args.timeout,
        dry_run=args.dry_run,
        resume=args.resume,
        max_sections=args.max_sections,
    )

    state_store = FilesystemStateStore(
        state_dir=config.state_dir,
        raw_path=config.raw_path,
        resume=config.resume,
    )
    state_store.init()

    llm = ClaudeCLIAdapter()
    batch_tools = BatchMCPServer(state_store, config.state_dir)
    batch_tools.start()

    try:
        service = ParsingService(
            config=config,
            llm=llm,
            state=state_store,
            batch_tools=batch_tools,
        )
        service.run()
    except RuntimeError as e:
        logger.error("%s", e)
        sys.exit(1)
    finally:
        batch_tools.stop()


if __name__ == "__main__":
    main()
