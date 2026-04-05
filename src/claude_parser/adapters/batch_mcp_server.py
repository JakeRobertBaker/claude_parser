"""MCP server providing batch processing tools for Haiku.

Tools: read_batch, submit_clean, submit_result.
Runs as an SSE server in a background thread. Reads batch data from the
shared FilesystemStateStore — no intermediate objects passed through the service.
"""

from __future__ import annotations

import asyncio
import difflib
import json
import logging
import os
import re
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
    inferred_cutoff_batch_line: int | None = None
    match_confidence: float | None = None
    raw_context_around_cutoff: list[str] = field(default_factory=list)
    cleaned_tail_lines: list[str] = field(default_factory=list)
    unclosed_nodes: list[str] = field(default_factory=list)


_WORD_RE = re.compile(r"[a-z]{4,}")
_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_MATH_BLOCK_RE = re.compile(r"\$\$.*?\$\$", re.DOTALL)
_MATH_INLINE_RE = re.compile(r"\$[^$\n]*?\$")


def _content_tokens(text: str) -> list[str]:
    """Extract normalized content words: lowercased, alphabetic, length >= 4.

    Strips HTML comments and LaTeX math to avoid structural/math noise.
    """
    text = _COMMENT_RE.sub(" ", text)
    text = _MATH_BLOCK_RE.sub(" ", text)
    text = _MATH_INLINE_RE.sub(" ", text)
    return _WORD_RE.findall(text.lower())


def _infer_cutoff_line(
    cleaned_text: str, raw_lines: list[str]
) -> tuple[int, float] | None:
    """Infer the raw cutoff line from cleaned_text via token-sequence alignment.

    Uses difflib.SequenceMatcher on content-token sequences to find where the
    cleaned content ends within the raw batch. Robust to repeated phrases
    because it maximizes global alignment, not per-window overlap.

    Returns (cutoff_line_1indexed, confidence) where confidence is the
    fraction of cleaned tokens that aligned to raw. Returns None if cleaned
    text is too short to align reliably.
    """
    cleaned_toks = _content_tokens(cleaned_text)
    if len(cleaned_toks) < 20:
        return None

    raw_toks: list[str] = []
    tok_to_line: list[int] = []
    for i, line in enumerate(raw_lines):
        for t in _content_tokens(line):
            raw_toks.append(t)
            tok_to_line.append(i + 1)

    if not raw_toks:
        return None

    sm = difflib.SequenceMatcher(a=cleaned_toks, b=raw_toks, autojunk=False)
    blocks = [b for b in sm.get_matching_blocks() if b.size > 0]
    if not blocks:
        return None

    last = blocks[-1]
    raw_end_tok_idx = last.b + last.size - 1
    cutoff_line = tok_to_line[raw_end_tok_idx]
    confidence = sum(b.size for b in blocks) / len(cleaned_toks)
    return cutoff_line, confidence


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
        self._inferred_cutoff_line: int | None = None
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
                mcp_types.Tool.model_validate(
                    {
                        "name": "read_batch",
                        "description": (
                            "Get the raw batch and its metadata. "
                            "Response fields: raw_content (str), "
                            "batch_line_count (int, number of lines in raw_content), "
                            "unclosed_nodes (list[str], outer-to-inner, nodes still open "
                            "from prior batches — continue or close them), "
                            "prior_clean_tail (str, last cleaned lines for context), "
                            "known_ids (list[str], all node ids defined in prior batches — "
                            "do NOT reuse), memory_text (str, persistent notes)."
                        ),
                        "inputSchema": {"type": "object", "properties": {}},
                        "_meta": {"anthropic/maxResultSizeChars": 500000},
                    }
                ),
                mcp_types.Tool(
                    name="submit_clean",
                    description=(
                        "Submit cleaned, annotated markdown for this batch. "
                        "Include only content up to your cutoff — do NOT append raw "
                        "remainder. The server validates annotations (IDs, nesting) "
                        "and infers the raw cutoff line by aligning your cleaned "
                        "text's content tokens against raw_content. "
                        "Response fields: "
                        "valid (bool), errors (list[str]), warnings (list[str]), "
                        "inferred_cutoff_batch_line (int, 1-indexed within batch — "
                        "pass this to commit_batch), "
                        "match_confidence (float 0-1, fraction of cleaned tokens "
                        "aligned to raw; <0.6 is rejected), "
                        "raw_context_around_cutoff (list[str], raw lines near the "
                        "inferred cutoff so you can verify), "
                        "cleaned_tail_lines (list[str], last lines you submitted), "
                        "unclosed_nodes (list[str], outer-to-inner, nodes carrying "
                        "to next batch). If valid=false, fix and resubmit."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "cleaned_text": {
                                "type": "string",
                                "description": (
                                    "Cleaned, annotated markdown. Everything up to "
                                    "(but not including) the raw cutoff."
                                ),
                            },
                        },
                        "required": ["cleaned_text"],
                    },
                ),
                mcp_types.Tool(
                    name="commit_batch",
                    description=(
                        "Finalize this batch. Call AFTER submit_clean returns valid. "
                        "By default the server uses the inferred_cutoff_batch_line "
                        "from your last submit_clean. Pass cutoff_batch_line only "
                        "to override it (e.g. inferred line sits mid-paragraph). "
                        'Response: {"status": "ok"}.'
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "cutoff_batch_line": {
                                "type": "integer",
                                "description": (
                                    "Optional. 1-indexed raw line within this "
                                    "batch where cleaning stops. Omit to use the "
                                    "server's inferred cutoff."
                                ),
                            },
                        },
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
            elif name == "commit_batch":
                return self._handle_commit_batch(arguments)
            else:
                return [
                    mcp_types.TextContent(type="text", text=f"Unknown tool: {name}")
                ]

    # -- Tool handlers --

    def _handle_read_batch(self) -> list[mcp_types.TextContent]:
        s = self._state_store
        data = {
            "raw_content": s.current_raw_content,
            "batch_line_count": s.current_raw_line_count,
            "unclosed_nodes": s.open_stack,
            "prior_clean_tail": s.current_prior_clean_tail,
            "known_ids": s.current_known_ids,
            "memory_text": s.current_memory_text,
        }
        return [
            mcp_types.TextContent(
                type="text", text=json.dumps(data, ensure_ascii=False)
            )
        ]

    def _handle_submit_clean(self, args: dict[str, Any]) -> list[mcp_types.TextContent]:
        cleaned_text: str = args["cleaned_text"]

        response = self._validate_and_write_clean(cleaned_text)
        data: dict[str, Any] = {
            "valid": response.valid,
            "errors": response.errors,
            "warnings": response.warnings,
        }
        if response.inferred_cutoff_batch_line is not None:
            data["inferred_cutoff_batch_line"] = response.inferred_cutoff_batch_line
        if response.match_confidence is not None:
            data["match_confidence"] = round(response.match_confidence, 3)
        data["raw_context_around_cutoff"] = response.raw_context_around_cutoff
        data["cleaned_tail_lines"] = response.cleaned_tail_lines
        data["unclosed_nodes"] = response.unclosed_nodes
        return [
            mcp_types.TextContent(
                type="text", text=json.dumps(data, ensure_ascii=False)
            )
        ]

    def _handle_commit_batch(self, args: dict[str, Any]) -> list[mcp_types.TextContent]:
        cutoff_batch_line = args.get("cutoff_batch_line")
        if cutoff_batch_line is None:
            cutoff_batch_line = self._inferred_cutoff_line
        if cutoff_batch_line is None:
            return [
                mcp_types.TextContent(
                    type="text",
                    text=json.dumps(
                        {
                            "status": "error",
                            "error": (
                                "No cutoff available. Call submit_clean successfully "
                                "first, or pass cutoff_batch_line explicitly."
                            ),
                        }
                    ),
                )
            ]
        # Convert batch-relative to source-relative, write to state
        source_line = self._state_store.current_raw_start + cutoff_batch_line
        self._state_store.set_cutoff(source_line)
        self._submitted = True
        return [mcp_types.TextContent(type="text", text='{"status": "ok"}')]

    # -- Validation + file writing --

    def _validate_and_write_clean(self, cleaned_text: str) -> _SubmitCleanResponse:
        s = self._state_store
        errors: list[str] = []
        warnings: list[str] = []

        cleaned_tokens = approximate_claude_tokens(cleaned_text)
        if cleaned_tokens < s.current_min_tokens:
            warnings.append(
                f"Cleaned text is ~{cleaned_tokens} tokens, suggested minimum is ~{s.current_min_tokens} tokens "
                f"(this is a soft warning, not an error)"
            )

        events = parse_annotations(cleaned_text)
        known = set(s.current_known_ids)
        validation = validate_annotations(
            events, known_ids=known, open_stack=s.open_stack
        )
        errors.extend(validation.errors)
        warnings.extend(validation.warnings)

        raw_lines = s.current_raw_content.splitlines(keepends=True)
        batch_line_count = len(raw_lines)

        inferred = _infer_cutoff_line(cleaned_text, raw_lines)
        if inferred is None:
            errors.append(
                "Cleaned text is too short to align with raw content. "
                "Submit a substantive batch (>=20 content tokens)."
            )
            return _SubmitCleanResponse(valid=False, errors=errors, warnings=warnings)

        cutoff_line, confidence = inferred
        min_cutoff = max(1, int(batch_line_count * 0.2))
        if confidence < 0.6 or cutoff_line < min_cutoff:
            errors.append(
                f"Could not align cleaned text to raw (confidence={confidence:.2f}, "
                f"inferred_line={cutoff_line}, batch has {batch_line_count} lines). "
                "Re-read the raw batch and resubmit with cleaned text that matches "
                "the raw content more closely."
            )
            return _SubmitCleanResponse(valid=False, errors=errors, warnings=warnings)

        # Compute unclosed nodes (start with carried-over open stack)
        stack: list[str] = list(s.open_stack)
        for event in events:
            if event.event_type == "start":
                stack.append(event.id)
            elif event.event_type == "end" and stack and stack[-1] == event.id:
                stack.pop()

        # Soft warning: if more source content follows, the outermost
        # container should usually remain open so content can continue.
        if not stack and not s.is_final_batch:
            warnings.append(
                "You closed every node, but more of the source document "
                "follows in later batches. If the outermost container "
                "(book, chapter, current section) continues past your "
                "cutoff, leave it OPEN so content carries to the next batch."
            )

        if cleaned_text and not cleaned_text.endswith("\n"):
            cleaned_text += "\n"

        full_content = cleaned_text + "<!-- cutoff -->\n"
        s.write_clean_batch(full_content)
        self._inferred_cutoff_line = cutoff_line

        raw_context = raw_lines[
            max(0, cutoff_line - 5) : min(batch_line_count, cutoff_line + 2)
        ]
        cleaned_lines = cleaned_text.splitlines()
        clean_tail = cleaned_lines[-5:] if len(cleaned_lines) >= 5 else cleaned_lines

        return _SubmitCleanResponse(
            valid=False if errors else True,
            errors=errors,
            warnings=warnings,
            inferred_cutoff_batch_line=cutoff_line,
            match_confidence=confidence,
            raw_context_around_cutoff=[line.rstrip("\n") for line in raw_context],
            cleaned_tail_lines=clean_tail,
            unclosed_nodes=stack,
        )

    # -- Public API for ParsingService --

    def prepare(self) -> None:
        self._submitted = False
        self._inferred_cutoff_line = None

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
