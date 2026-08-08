import argparse
import logging
import os
import sys

from claude_parser.adapters.llm.claude_cli import ClaudeCLIAdapter
from claude_parser.adapters.llm.pi_sdk import PiSDKAdapter
from claude_parser.adapters.math import KaTeXMathValidator
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
        help="Print prompts without invoking an agent.",
    )
    parser.add_argument(
        "--llm-adapter",
        choices=("claude-cli", "pi-sdk"),
        default="claude-cli",
        help="Agent runtime to use (default: claude-cli).",
    )
    parser.add_argument(
        "--task-model",
        default=None,
        help=(
            "Model for batch processing. Defaults to haiku for claude-cli and "
            "Pi's configured default for pi-sdk. Pi accepts provider/model patterns."
        ),
    )
    parser.add_argument(
        "--batch-tokens",
        type=int,
        default=16000,
        help="Approximate core work target per batch (default: 16000).",
    )
    parser.add_argument(
        "--prior-clean-context-tokens",
        type=int,
        default=2000,
        help="Read-only cleaned context before the batch (default: 2000).",
    )
    parser.add_argument(
        "--next-raw-context-tokens",
        type=int,
        default=2000,
        help="Read-only raw context after the committable batch (default: 2000).",
    )
    parser.add_argument(
        "--pi-debug-stream-log",
        action="store_true",
        help=(
            "Persist sensitive raw Pi stream events, including text and thinking deltas."
        ),
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
        prior_clean_context_tokens=args.prior_clean_context_tokens,
        next_raw_context_tokens=args.next_raw_context_tokens,
        timeout=args.timeout,
        dry_run=args.dry_run,
        resume=args.resume,
        max_sections=args.max_sections,
        pi_debug_stream_log=args.pi_debug_stream_log,
    )

    state_store = FilesystemStateStore(
        state_dir=config.state_dir,
        raw_path=config.raw_path,
        resume=config.resume,
    )
    state_store.init()

    math_validator = KaTeXMathValidator()
    try:
        math_validator.validate("")
    except RuntimeError as exc:
        logger.error("%s", exc)
        sys.exit(1)

    if args.llm_adapter == "pi-sdk":
        llm = PiSDKAdapter(
            log_root=os.path.join(config.state_dir, "logs", "pi"),
            debug_stream_log=config.pi_debug_stream_log,
        )
    else:
        llm = ClaudeCLIAdapter()
    batch_tools = BatchMCPServer(state_store, config.state_dir, math_validator)
    if not config.dry_run:
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
        if not config.dry_run:
            batch_tools.stop()


if __name__ == "__main__":
    main()
