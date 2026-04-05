from claude_parser.domain.annotation_parser import parse_annotations
from claude_parser.domain.validator import validate_annotations
import json


invoke_path = "/home/jake/ai_tool_development/knowledge_prasing/claude_chat_log/mcp_test_9/invoke_1.jsonl"


search_term = "mcp__batch_tools__submit_clean"
found_elements = []
data = []

with open(invoke_path, "r", encoding="utf-8") as f:
    for line in f:
        # Replicates 'Control + F' - check if text exists in the raw line
        line_data = json.loads(line)
        data.append(line_data)
        if search_term in line:
            # Parse only the matching line into a Python object
            found_elements.append(line_data)


def find_all_with_paths(data, query, path=None):
    if path is None:
        path = []

    # 1. Check if the query is in a string value
    if isinstance(data, str) and query in data:
        yield {"path": path, "value": data}

    # 2. Check Dictionaries (Keys and Values)
    elif isinstance(data, dict):
        for key, value in data.items():
            current_path = path + [key]

            # Check if query is in the KEY itself
            if query in str(key):
                yield {"path": current_path, "value": value}

            # Search deeper into the VALUE
            yield from find_all_with_paths(value, query, current_path)

    # 3. Check Lists
    elif isinstance(data, list):
        for index, item in enumerate(data):
            current_path = path + [index]
            yield from find_all_with_paths(item, query, current_path)


# --- Usage ---
results = list(find_all_with_paths(data, "unclosed_nodes"))
result_data = json.loads(results[2]["value"])

known_ids = result_data["known_ids"]
open_stack = result_data["unclosed_nodes"]
cleaned_text = found_elements[0]["message"]["content"][0]["input"]["cleaned_text"]
events = parse_annotations(cleaned_text)

validate_annotations(events, known_ids, open_stack)
