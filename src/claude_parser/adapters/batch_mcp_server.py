"""MCP server providing batch processing tools for Haiku.

Tools: read_batch, submit_clean, submit_result.
Runs as an SSE server in a background thread, sharing state with ParsingService.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
import threading
from dataclasses import dataclass, field
from typing import Any

import mcp.types as mcp_types
from mcp.server.lowlevel import Server
from mcp.server.sse import SseServerTransport
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Mount, Route

from claude_parser.domain.annotation_parser import parse_annotations
from claude_parser.domain.batch_types import BatchResult, SubmitCleanResponse
from claude_parser.domain.validator import validate_annotations
from claude_parser.ports.state import StatePort

logger = logging.getLogger(__name__)


@dataclass
class _BatchState:
    """Mutable state for the current batch, set by ParsingService before each invocation."""

    batch_num: int = 0
    raw_content: str = ""
    chunk_id: str = ""
    raw_start: int = 0
    raw_end: int = 0
    open_stack: list[str] = field(default_factory=list)
    context_text: str = ""
    known_ids: list[str] = field(default_factory=list)
    memory_text: str = ""
    min_clean_lines: int = 0
    # Written by submit_result tool
    result: BatchResult | None = None


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class BatchMCPServer:
    """MCP server with read_batch, submit_clean, submit_result tools.

    Runs an SSE server in a background thread. ParsingService calls
    setup_batch() before each LLM invocation, then get_result() after.
    """

    def __init__(self, state_store: StatePort, state_dir: str):
        self._state_store = state_store
        self._state_dir = os.path.abspath(state_dir)
        self._batch = _BatchState()
        self._port = _find_free_port()
        self._thread: threading.Thread | None = None
        self._uvicorn_server: Any = None  # uvicorn.Server, set in _run_server

        # Build MCP config file path
        self._mcp_config_file = os.path.join(self._state_dir, "mcp_config.json")

        # Build the MCP server
        self._mcp_server = Server("batch_tools")
        self._register_tools()

    def _register_tools(self) -> None:
        server = self._mcp_server

        @server.list_tools()
        async def list_tools() -> list[mcp_types.Tool]:
            return [
                mcp_types.Tool(
                    name="read_batch",
                    description="Read the current batch data: raw content, open nodes, context, and metadata.",
                    inputSchema={"type": "object", "properties": {}},
                ),
                mcp_types.Tool(
                    name="submit_clean",
                    description=(
                        "Submit cleaned and annotated markdown. "
                        "Only include content up to your cutoff point (do NOT include raw remainder). "
                        "The server appends the cutoff marker and raw remainder automatically, "
                        "runs validation, and returns results."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "cleaned_text": {
                                "type": "string",
                                "description": "The cleaned and annotated markdown text (everything before cutoff).",
                            },
                            "cutoff_raw_line": {
                                "type": "integer",
                                "description": (
                                    "1-indexed raw source line where you stopped cleaning. "
                                    "This is relative to the full source file, not the batch."
                                ),
                            },
                        },
                        "required": ["cleaned_text", "cutoff_raw_line"],
                    },
                ),
                mcp_types.Tool(
                    name="submit_result",
                    description="Submit the final result for this batch after successful validation.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "chunk_id": {"type": "string"},
                            "cutoff_raw_line": {"type": "integer"},
                            "n_lines_cleaned": {"type": "integer"},
                            "notes": {"type": ["string", "null"]},
                        },
                        "required": ["chunk_id", "cutoff_raw_line", "n_lines_cleaned"],
                    },
                ),
            ]

        @server.call_tool()
        async def call_tool(
            name: str, arguments: dict[str, Any]
        ) -> list[mcp_types.TextContent]:
            if name == "read_batch":
                return self._handle_read_batch()
            elif name == "submit_clean":
                return self._handle_submit_clean(arguments)
            elif name == "submit_result":
                return self._handle_submit_result(arguments)
            else:
                return [mcp_types.TextContent(type="text", text=f"Unknown tool: {name}")]

    # -- Tool handlers (sync, called from async context) --

    def _handle_read_batch(self) -> list[mcp_types.TextContent]:
        b = self._batch
        data = {
            "chunk_id": b.chunk_id,
            "raw_content": b.raw_content,
            "raw_start": b.raw_start,
            "raw_end": b.raw_end,
            "raw_line_count": b.raw_end - b.raw_start,
            "min_clean_lines": b.min_clean_lines,
            "open_stack": b.open_stack,
            "context_text": b.context_text,
            "known_ids": b.known_ids,
            "memory_text": b.memory_text,
        }
        return [mcp_types.TextContent(type="text", text=json.dumps(data, ensure_ascii=False))]

    def _handle_submit_clean(self, args: dict[str, Any]) -> list[mcp_types.TextContent]:
        cleaned_text: str = args["cleaned_text"]
        cutoff_raw_line: int = args["cutoff_raw_line"]
        b = self._batch

        response = self._validate_and_write_clean(cleaned_text, cutoff_raw_line, b)
        data = {
            "valid": response.valid,
            "errors": response.errors,
            "warnings": response.warnings,
            "raw_context_lines": response.raw_context_lines,
            "clean_tail_lines": response.clean_tail_lines,
        }
        return [mcp_types.TextContent(type="text", text=json.dumps(data, ensure_ascii=False))]

    def _handle_submit_result(self, args: dict[str, Any]) -> list[mcp_types.TextContent]:
        self._batch.result = BatchResult(
            chunk_id=args["chunk_id"],
            cutoff_raw_line=args["cutoff_raw_line"],
            n_lines_cleaned=args["n_lines_cleaned"],
            notes=args.get("notes"),
        )
        return [mcp_types.TextContent(type="text", text='{"status": "ok"}')]

    # -- Validation + file writing --

    def _validate_and_write_clean(
        self, cleaned_text: str, cutoff_raw_line: int, b: _BatchState
    ) -> SubmitCleanResponse:
        errors: list[str] = []

        # Validate cutoff bounds
        if cutoff_raw_line < b.raw_start:
            errors.append(
                f"cutoff_raw_line {cutoff_raw_line} is before batch start {b.raw_start}"
            )
        if cutoff_raw_line > b.raw_end:
            errors.append(
                f"cutoff_raw_line {cutoff_raw_line} is after batch end {b.raw_end}"
            )

        if errors:
            return SubmitCleanResponse(valid=False, errors=errors)

        # Validate cleaned text is non-empty
        cleaned_lines = cleaned_text.splitlines()
        if len(cleaned_lines) < b.min_clean_lines:
            errors.append(
                f"Only {len(cleaned_lines)} cleaned lines, minimum is {b.min_clean_lines}"
            )

        # Run annotation validation
        events = parse_annotations(cleaned_text)
        known = set(b.known_ids)
        validation = validate_annotations(events, known_ids=known)
        errors.extend(validation.errors)

        if errors:
            return SubmitCleanResponse(
                valid=False,
                errors=errors,
                warnings=validation.warnings,
            )

        # Build the full clean file: cleaned text + cutoff + raw remainder
        raw_lines = b.raw_content.splitlines(keepends=True)
        # cutoff_raw_line is 1-indexed source line; batch starts at raw_start (also 1-indexed)
        cutoff_offset = cutoff_raw_line - b.raw_start
        raw_remainder_lines = raw_lines[cutoff_offset:]

        # Ensure cleaned_text ends with newline
        if cleaned_text and not cleaned_text.endswith("\n"):
            cleaned_text += "\n"

        full_content = cleaned_text + "<!-- cutoff -->\n" + "".join(raw_remainder_lines)

        # Write the clean file
        clean_path = self._state_store.resolve_clean_path(b.batch_num)
        with open(clean_path, "w", encoding="utf-8") as f:
            f.write(full_content)

        # Build context lines for Haiku to verify alignment
        raw_context = raw_lines[max(0, cutoff_offset - 5) : cutoff_offset]
        clean_tail = cleaned_lines[-5:] if len(cleaned_lines) >= 5 else cleaned_lines

        return SubmitCleanResponse(
            valid=True,
            errors=[],
            warnings=validation.warnings,
            raw_context_lines=[line.rstrip("\n") for line in raw_context],
            clean_tail_lines=clean_tail,
        )

    # -- Public API for ParsingService --

    def setup_batch(
        self,
        batch_num: int,
        raw_content: str,
        chunk_id: str,
        raw_start: int,
        raw_end: int,
        open_stack: list[str],
        context_text: str,
        known_ids: list[str],
        memory_text: str,
        min_clean_lines: int,
    ) -> None:
        self._batch = _BatchState(
            batch_num=batch_num,
            raw_content=raw_content,
            chunk_id=chunk_id,
            raw_start=raw_start,
            raw_end=raw_end,
            open_stack=open_stack,
            context_text=context_text,
            known_ids=known_ids,
            memory_text=memory_text,
            min_clean_lines=min_clean_lines,
            result=None,
        )

    def get_result(self) -> BatchResult | None:
        return self._batch.result

    @property
    def mcp_config_path(self) -> str:
        return self._mcp_config_file

    def start(self) -> None:
        """Start the SSE server in a background thread."""
        self._write_mcp_config()
        self._thread = threading.Thread(target=self._run_server, daemon=True)
        self._thread.start()
        self._wait_for_port()
        logger.info("MCP server started on port %d", self._port)

    def _wait_for_port(self, timeout: float = 10.0) -> None:
        """Poll until the server is accepting connections."""
        import time

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", self._port), timeout=0.5):
                    return
            except OSError:
                time.sleep(0.1)
        raise RuntimeError(f"MCP server did not start within {timeout}s")

    def stop(self) -> None:
        """Stop the SSE server."""
        if self._uvicorn_server is not None:
            self._uvicorn_server.should_exit = True
        if self._thread is not None:
            self._thread.join(timeout=10)
        logger.info("MCP server stopped")

    def _write_mcp_config(self) -> None:
        config = {
            "mcpServers": {
                "batch_tools": {
                    "type": "sse",
                    "url": f"http://127.0.0.1:{self._port}/sse",
                }
            }
        }
        with open(self._mcp_config_file, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)

    def _run_server(self) -> None:
        """Run the SSE server (called in background thread)."""
        import uvicorn

        sse_transport = SseServerTransport("/messages/")
        mcp_server = self._mcp_server

        async def handle_sse(request: Request) -> Response:
            async with sse_transport.connect_sse(
                request.scope, request.receive, request._send
            ) as streams:
                await mcp_server.run(
                    streams[0],
                    streams[1],
                    mcp_server.create_initialization_options(),
                )
            return Response()

        app = Starlette(
            routes=[
                Route("/sse", endpoint=handle_sse, methods=["GET"]),
                Mount("/messages/", app=sse_transport.handle_post_message),
            ],
        )

        config = uvicorn.Config(
            app,
            host="127.0.0.1",
            port=self._port,
            log_level="warning",
        )
        server = uvicorn.Server(config)
        self._uvicorn_server = server

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(server.serve())
        loop.close()
