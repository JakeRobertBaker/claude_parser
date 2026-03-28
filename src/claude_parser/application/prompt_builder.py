import os
import textwrap

from claude_parser.config import ParserConfig

SKILL_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    os.pardir, os.pardir, os.pardir, "prompts", "task_skill.md",
)
SKILL_PATH = os.path.normpath(SKILL_PATH)


def build_phase0_prompt(raw_path: str, config: ParserConfig) -> str:
    return textwrap.dedent(f"""\
        You are a task agent analyzing the front matter of a mathematics textbook.

        ## Instructions
        1. Read the first 500 lines of: {raw_path}
           (Use the Read tool with limit=500)
        2. Identify the Table of Contents (if present) and parse it into a hierarchy tree
        3. If no ToC is found, return an empty hierarchy: {{"id": "root", "title": "Root", "children": []}}
        4. Identify where actual content begins (first chapter or introduction)
        5. Print ONLY this JSON to stdout (no other text):

        {{
          "content_start_line": <line number where content begins, 1-indexed>,
          "hierarchy": {{
            "id": "root",
            "title": "Root",
            "children": [
              {{
                "id": "ch01",
                "title": "Chapter Title",
                "children": [
                  {{
                    "id": "sec01_01",
                    "title": "Section Title",
                    "children": []
                  }}
                ]
              }}
            ]
          }}
        }}

        ## Rules
        - Use chapter/section numbering from the textbook (ch01, sec01_01, etc.)
        - Do NOT include any content fields — these are skeleton nodes
        - content_start_line should point to the first line of actual content
          (skip title pages, copyright, preface unless it has mathematical content)
        - stdout must contain ONLY the JSON — no commentary, no markdown fences
    """)


def build_section_prompt(
    raw_path: str,
    start_line: int,
    end_line: int,
    chunk_id: str,
    overlap_text: str,
    tree_state_json: str,
    config: ParserConfig,
) -> str:
    skill_path = _resolve_skill_path()
    min_lines = int((end_line - start_line) * 0.6)

    parts = [
        "You are a task agent in a textbook markdown cleaning pipeline.",
        "",
        "## Instructions",
        f"1. Read your skill instructions from: {skill_path}",
        f"2. Read lines {start_line + 1} through {end_line} from: {raw_path}",
        f"   (Use the Read tool with offset={start_line} and limit={end_line - start_line})",
        "3. Clean the text per the skill instructions",
        f"4. Write the cleaned chunk to: {{state_chunks_dir}}/{chunk_id}.md",
        "5. Print ONLY the metadata JSON to stdout (no other text)",
        "",
        "## Parameters",
        f"- Chunk ID: {chunk_id}",
        f"- Source file: {raw_path}",
        f"- Line range: {start_line + 1} to {end_line} (1-indexed)",
        f"- Minimum processing: {min_lines} lines (60% of stride)",
        "",
        "## Current Tree State",
        "Use this to assign correct node IDs and parent placement:",
        "```json",
        tree_state_json,
        "```",
    ]

    if overlap_text:
        parts.extend([
            "",
            "## CONTEXT (already processed, do not include in output):",
            overlap_text,
        ])

    return "\n".join(parts)


def build_retry_prompt(original_prompt: str, duplicate_ids: list[str]) -> str:
    ids_str = ", ".join(f"'{i}'" for i in duplicate_ids)
    suffix = (
        f"\n\n## IMPORTANT CORRECTION\n"
        f"The following node IDs are already taken: {ids_str}.\n"
        f"You MUST choose different, unique IDs for these nodes."
    )
    return original_prompt + suffix


def _resolve_skill_path() -> str:
    if os.path.exists(SKILL_PATH):
        return SKILL_PATH
    return "prompts/task_skill.md"
