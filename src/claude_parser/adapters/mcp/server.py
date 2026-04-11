"""MCP SSE server exposing read_batch/submit_clean/commit_batch tools."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
import threading
from typing import Any

import mcp.types as mcp_types
from mcp.server.lowlevel import Server
from mcp.server.sse import SseServerTransport
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Mount, Route

from claude_parser.application.batch_tools import BatchToolsService
from claude_parser.domain.node import TreeDict
from claude_parser.ports.batch_tools import BatchToolsPort
from claude_parser.ports.state import BatchContext, StatePort

logger = logging.getLogger(__name__)


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class BatchMCPServer(BatchToolsPort):
    """Adapter that backs the BatchToolsPort via MCP SSE server."""

    def __init__(self, state: StatePort, state_dir: str):
        self._state_dir = os.path.abspath(state_dir)
        self._service = BatchToolsService(state)
        self._port = _find_free_port()
        self._thread: threading.Thread | None = None
        self._uvicorn_server: Any = None

        self._mcp_config_file = os.path.join(self._state_dir, "mcp_config.json")
        self._mcp_server = Server("batch_tools")
        self._register_tools()

    # -- BatchToolsPort --

    def begin_batch(
        self,
        context: BatchContext,
        known_ids: list[str],
        tree_dict: TreeDict,
        current_ordinal: int,
    ) -> None:
        self._service.begin_batch(context, known_ids, tree_dict, current_ordinal)

    def succeeded(self) -> bool:
        return self._service.succeeded()

    def committed_source_line(self) -> int | None:
        return self._service.committed_source_line()

    @property
    def mcp_config_path(self) -> str:
        return self._mcp_config_file

    def start(self) -> None:
        self._write_mcp_config()
        self._thread = threading.Thread(target=self._run_server, daemon=True)
        self._thread.start()
        self._wait_for_port()
        logger.info("MCP server started on port %d", self._port)

    def stop(self) -> None:
        if self._uvicorn_server is not None:
            self._uvicorn_server.should_exit = True
        if self._thread is not None:
            self._thread.join(timeout=10)
        logger.info("MCP server stopped")

    # -- MCP tool wiring --

    def _register_tools(self) -> None:
        server = self._mcp_server

        @server.list_tools()
        async def list_tools() -> list[mcp_types.Tool]:
            tools: list[mcp_types.Tool] = []
            for spec in self._service.tool_specs():
                payload = {
                    "name": spec.name,
                    "description": spec.description,
                    "inputSchema": spec.input_schema,
                }
                if spec.meta:
                    payload["_meta"] = spec.meta
                tools.append(mcp_types.Tool.model_validate(payload))
            return tools

        @server.call_tool()
        async def call_tool(
            name: str, arguments: dict[str, Any]
        ) -> list[mcp_types.TextContent]:
            try:
                data = self._service.call_tool(name, arguments)
            except ValueError as exc:
                data = {"status": "error", "error": str(exc)}
            return [
                mcp_types.TextContent(
                    type="text", text=json.dumps(data, ensure_ascii=False)
                )
            ]

    # -- Server lifecycle helpers --

    def _write_mcp_config(self) -> None:
        config = {
            "mcpServers": {
                "batch_tools": {
                    "type": "sse",
                    "url": f"http://127.0.0.1:{self._port}/sse",
                }
            }
        }
        with open(self._mcp_config_file, "w", encoding="utf-8") as handle:
            json.dump(config, handle, indent=2)

    def _run_server(self) -> None:
        import uvicorn

        sse_transport = SseServerTransport("/messages/")
        mcp_server = self._mcp_server

        async def handle_sse(request: Request) -> Response:
            async with sse_transport.connect_sse(
                request.scope, request.receive, request._send
            ) as streams:
                await mcp_server.run(
                    streams[0], streams[1], mcp_server.create_initialization_options()
                )
            return Response()

        app = Starlette(
            routes=[
                Route("/sse", endpoint=handle_sse, methods=["GET"]),
                Mount("/messages/", app=sse_transport.handle_post_message),
            ]
        )

        config = uvicorn.Config(
            app, host="127.0.0.1", port=self._port, log_level="warning"
        )
        server = uvicorn.Server(config)
        self._uvicorn_server = server

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(server.serve())
        loop.close()

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
