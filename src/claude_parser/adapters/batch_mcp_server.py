"""MCP server providing batch processing tools for Haiku.

Tools: read_batch, submit_clean, submit_result.
Runs as an SSE server in a background thread. Reads batch data from the
shared FilesystemStateStore — no intermediate objects passed through the service.
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

from claude_parser.adapters.filesystem_state_store import FilesystemStateStore
from claude_parser.application.tokens import approximate_claude_tokens
from claude_parser.domain.annotation_parser import parse_annotations
from claude_parser.domain.validator import validate_annotations

logger = logging.getLogger(__name__)


@dataclass
class _SubmitCleanResponse:
    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    raw_context_lines: list[str] = field(default_factory=list)
    clean_tail_lines: list[str] = field(default_factory=list)


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class BatchMCPServer:
    """MCP server with read_batch, submit_clean, submit_result tools.

    Reads batch data directly from the shared FilesystemStateStore.
    ParsingService calls prepare() before each LLM invocation,
    then succeeded() after.
    """

    def __init__(self, state_store: FilesystemStateStore, state_dir: str):
        self._state_store = state_store
        self._state_dir = os.path.abspath(state_dir)
        self._submitted: bool = False
        self._port = _find_free_port()
        self._thread: threading.Thread | None = None
        self._uvicorn_server: Any = None

        self._mcp_config_file = os.path.join(self._state_dir, "mcp_config.json")
        self._mcp_server = Server("batch_tools")
        self._register_tools()

    def _register_tools(self) -> None:
        server = self._mcp_server

        @server.list_tools()
        async def list_tools() -> list[mcp_types.Tool]:
            return [
                mcp_types.Tool.model_validate({
                    "name": "read_batch",
                    "description": (
                        "Read the raw text and batch metadata: chunk_id, open nodes, "
                        "context, known IDs. Returns everything needed for this batch."
                    ),
                    "inputSchema": {"type": "object", "properties": {}},
                    "_meta": {"anthropic/maxResultSizeChars": 500000},
                }),
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
                            "cutoff_batch_line": {
                                "type": "integer",
                                "description": (
                                    "1-indexed line number within THIS BATCH where you stopped cleaning. "
                                    "For example, if you cleaned up to line 300 of the batch, use 300."
                                ),
                            },
                        },
                        "required": ["cleaned_text", "cutoff_batch_line"],
                    },
                ),
                mcp_types.Tool(
                    name="submit_result",
                    description="Submit the final result for this batch after successful validation.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "chunk_id": {"type": "string"},
                            "cutoff_batch_line": {
                                "type": "integer",
                                "description": "Same cutoff_batch_line you used in submit_clean.",
                            },
                            "n_lines_cleaned": {"type": "integer"},
                            "notes": {"type": ["string", "null"]},
                        },
                        "required": ["chunk_id", "cutoff_batch_line", "n_lines_cleaned"],
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

    # -- Tool handlers --

    def _handle_read_batch(self) -> list[mcp_types.TextContent]:
        s = self._state_store
        data = {
            "chunk_id": s.current_id,
            "raw_content": s.current_raw_content,
            "batch_line_count": s.current_raw_line_count,
            "raw_start": s.current_raw_start + 1,  # 1-indexed for display
            "raw_end": s.current_raw_end,
            "open_stack": s.open_stack,
            "previous_batch_tail": s.current_context_text,
            "known_ids": s.current_known_ids,
            "memory_text": s.current_memory_text,
        }
        return [mcp_types.TextContent(type="text", text=json.dumps(data, ensure_ascii=False))]

    def _handle_submit_clean(self, args: dict[str, Any]) -> list[mcp_types.TextContent]:
        cleaned_text: str = args["cleaned_text"]
        cutoff_batch_line: int = args["cutoff_batch_line"]

        response = self._validate_and_write_clean(cleaned_text, cutoff_batch_line)
        data = {
            "valid": response.valid,
            "errors": response.errors,
            "warnings": response.warnings,
            "raw_context_lines": response.raw_context_lines,
            "clean_tail_lines": response.clean_tail_lines,
        }
        return [mcp_types.TextContent(type="text", text=json.dumps(data, ensure_ascii=False))]

    def _handle_submit_result(self, args: dict[str, Any]) -> list[mcp_types.TextContent]:
        cutoff_batch_line: int = args["cutoff_batch_line"]
        # Convert batch-relative to source-relative, write to state
        source_line = self._state_store.current_raw_start + cutoff_batch_line
        self._state_store.set_cutoff(source_line)
        self._submitted = True
        return [mcp_types.TextContent(type="text", text='{"status": "ok"}')]

    # -- Validation + file writing --

    def _validate_and_write_clean(
        self, cleaned_text: str, cutoff_batch_line: int
    ) -> _SubmitCleanResponse:
        s = self._state_store
        errors: list[str] = []

        if cutoff_batch_line < 1:
            errors.append(f"cutoff_batch_line {cutoff_batch_line} must be >= 1")
        if cutoff_batch_line > s.current_raw_line_count:
            errors.append(
                f"cutoff_batch_line {cutoff_batch_line} exceeds batch size {s.current_raw_line_count}"
            )

        if errors:
            return _SubmitCleanResponse(valid=False, errors=errors)

        warnings: list[str] = []
        cleaned_tokens = approximate_claude_tokens(cleaned_text)
        if cleaned_tokens < s.current_min_tokens:
            warnings.append(
                f"Cleaned text is ~{cleaned_tokens} tokens, suggested minimum is ~{s.current_min_tokens} tokens "
                f"(this is a soft warning, not an error)"
            )

        events = parse_annotations(cleaned_text)
        known = set(s.current_known_ids)
        validation = validate_annotations(events, known_ids=known)
        errors.extend(validation.errors)
        warnings.extend(validation.warnings)

        if errors:
            return _SubmitCleanResponse(valid=False, errors=errors, warnings=warnings)

        # Build full clean file: cleaned text + cutoff + raw remainder
        raw_lines = s.current_raw_content.splitlines(keepends=True)
        cutoff_offset = cutoff_batch_line
        raw_remainder_lines = raw_lines[cutoff_offset:]

        if cleaned_text and not cleaned_text.endswith("\n"):
            cleaned_text += "\n"

        full_content = cleaned_text + "<!-- cutoff -->\n" + "".join(raw_remainder_lines)
        s.write_clean_batch(full_content)

        # Report unclosed nodes
        stack: list[str] = []
        for event in events:
            if event.event_type == "start":
                stack.append(event.id)
            elif event.event_type == "end" and stack and stack[-1] == event.id:
                stack.pop()
        if stack:
            warnings.append(f"Unclosed nodes will carry to next batch: {list(stack)}")

        raw_context = raw_lines[max(0, cutoff_offset - 5) : cutoff_offset]
        cleaned_lines = cleaned_text.splitlines()
        clean_tail = cleaned_lines[-5:] if len(cleaned_lines) >= 5 else cleaned_lines

        return _SubmitCleanResponse(
            valid=True,
            errors=[],
            warnings=warnings,
            raw_context_lines=[line.rstrip("\n") for line in raw_context],
            clean_tail_lines=clean_tail,
        )

    # -- Public API for ParsingService --

    def prepare(self) -> None:
        self._submitted = False

    def succeeded(self) -> bool:
        return self._submitted

    @property
    def mcp_config_path(self) -> str:
        return self._mcp_config_file

    def start(self) -> None:
        self._write_mcp_config()
        self._thread = threading.Thread(target=self._run_server, daemon=True)
        self._thread.start()
        self._wait_for_port()
        logger.info("MCP server started on port %d", self._port)

    def _wait_for_port(self, timeout: float = 10.0) -> None:
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
            app, host="127.0.0.1", port=self._port, log_level="warning",
        )
        server = uvicorn.Server(config)
        self._uvicorn_server = server

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(server.serve())
        loop.close()
