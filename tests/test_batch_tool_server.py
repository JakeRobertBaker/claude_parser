from __future__ import annotations

import json
from pathlib import Path
from urllib.request import Request, urlopen

from claude_parser.adapters.mcp.server import BatchMCPServer
from claude_parser.adapters.state.filesystem import FilesystemStateStore
from claude_parser.application.tokens import approximate_claude_tokens
from claude_parser.ports.state import BatchContext


def test_json_transport_lists_and_calls_batch_tools(tmp_path: Path) -> None:
    raw_path = tmp_path / "raw.md"
    raw_content = "A short raw batch.\n"
    raw_path.write_text(raw_content, encoding="utf-8")
    state_dir = tmp_path / "state"
    state = FilesystemStateStore(str(state_dir), str(raw_path))
    state.init()

    server = BatchMCPServer(state, str(state_dir))
    server.start()
    try:
        context = BatchContext(
            raw_content=raw_content,
            raw_start_line=0,
            raw_end_line=1,
            raw_line_count=1,
            raw_token_count=approximate_claude_tokens(raw_content),
            next_raw_context="Following raw context.\n",
            next_raw_context_line_count=1,
            next_raw_context_token_count=approximate_claude_tokens(
                "Following raw context.\n"
            ),
            prior_clean_context="Prior clean context.\n",
            prior_continuation_node_id=None,
            memory_text="",
            clean_token_target=1,
        )
        server.begin_batch(context, state.known_ids, state.tree_dict, 0)

        with urlopen(server.tool_endpoint, timeout=2) as response:
            specs = json.load(response)
        assert {spec["name"] for spec in specs} == {
            "read_batch",
            "submit_clean",
            "commit_batch",
        }

        request = Request(
            server.tool_endpoint,
            data=json.dumps({"name": "read_batch", "arguments": {}}).encode(),
            headers={"content-type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=2) as response:
            payload = json.load(response)
        assert payload["raw_content"] == raw_content
        assert payload["batch_line_count"] == 1
        assert payload["prior_clean_context"] == "Prior clean context.\n"
        assert payload["next_raw_context"] == "Following raw context.\n"
    finally:
        server.stop()
