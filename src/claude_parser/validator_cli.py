"""CLI entry point for the annotation validator.

Invoked by Haiku via Bash tool:
    uv run python -m claude_parser.validator_cli <clean_file> [--raw-file <raw_file>]
"""

import argparse
import json
import os
import sys

from claude_parser.domain.annotation_parser import parse_annotations
from claude_parser.domain.validator import validate_annotations


def _check_cutoff_match(clean_lines: list[str], raw_path: str, cutoff_line: int) -> list[str]:
    """Check that lines after cutoff in clean file match tail of raw file."""
    errors: list[str] = []
    with open(raw_path, encoding="utf-8") as f:
        raw_lines = f.readlines()

    # Lines after cutoff in clean file (0-indexed: cutoff_line onwards)
    clean_tail = clean_lines[cutoff_line:]
    if not clean_tail:
        return errors

    # Find matching tail in raw file
    n_tail = len(clean_tail)
    raw_tail = raw_lines[-n_tail:] if n_tail <= len(raw_lines) else []

    if len(clean_tail) != len(raw_tail):
        errors.append(
            f"Post-cutoff length mismatch: clean has {len(clean_tail)} "
            f"lines after cutoff, raw tail has {len(raw_tail)}"
        )
        return errors

    for i, (cl, rl) in enumerate(zip(clean_tail, raw_tail)):
        if cl != rl:
            errors.append(
                f"Post-cutoff mismatch at line {cutoff_line + i + 1}: "
                f"clean != raw"
            )
            break

    return errors


def _check_file_basics(clean_file: str, text: str, raw_file: str | None) -> list[str]:
    """Check that the clean file is non-empty and has a cutoff marker."""
    errors: list[str] = []

    if not os.path.exists(clean_file):
        errors.append(f"Clean file does not exist: {clean_file}")
        return errors

    if not text.strip():
        errors.append("Clean file is empty")
        return errors

    lines = text.splitlines()
    has_cutoff = any("<!-- cutoff -->" in line for line in lines)
    if not has_cutoff:
        errors.append("Clean file has no <!-- cutoff --> marker")

    # Check reasonable lines-cleaned ratio against raw
    if raw_file and has_cutoff:
        with open(raw_file, encoding="utf-8") as f:
            raw_line_count = sum(1 for _ in f)
        cutoff_idx = next(i for i, ln in enumerate(lines) if "<!-- cutoff -->" in ln)
        cleaned_lines = cutoff_idx
        if raw_line_count > 0 and cleaned_lines < raw_line_count * 0.3:
            errors.append(
                f"Cleaned only {cleaned_lines}/{raw_line_count} raw lines "
                f"({cleaned_lines * 100 // raw_line_count}%) — expected at least 30%"
            )

    return errors


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate tree annotations in a cleaned markdown file.")
    parser.add_argument("clean_file", help="Path to the cleaned/annotated markdown file")
    parser.add_argument("--raw-file", help="Path to the raw input file (for cutoff verification)")
    parser.add_argument("--known-ids", nargs="*", default=[], help="Node IDs from previous batches")
    args = parser.parse_args()

    all_errors: list[str] = []

    # Basic file checks first
    if not os.path.exists(args.clean_file):
        all_errors.append(f"Clean file does not exist: {args.clean_file}")
        output: dict[str, object] = {"valid": False, "errors": all_errors, "warnings": []}
        json.dump(output, sys.stdout, indent=2)
        print()
        sys.exit(1)

    with open(args.clean_file, encoding="utf-8") as f:
        text = f.read()
    clean_lines = text.splitlines(keepends=True)

    basic_errors = _check_file_basics(args.clean_file, text, args.raw_file)
    all_errors.extend(basic_errors)

    events = parse_annotations(text)
    known = set(args.known_ids) if args.known_ids else set()
    result = validate_annotations(events, known_ids=known)
    all_errors.extend(result.errors)

    # Find cutoff line and verify against raw
    cutoff_line = None
    for event in events:
        if event.event_type == "cutoff":
            cutoff_line = event.line_number
            break

    if args.raw_file and cutoff_line is not None:
        cutoff_errors = _check_cutoff_match(clean_lines, args.raw_file, cutoff_line)
        all_errors.extend(cutoff_errors)

    valid = len(all_errors) == 0
    output: dict[str, object] = {
        "valid": valid,
        "errors": all_errors,
        "warnings": result.warnings,
    }
    if cutoff_line is not None:
        output["cutoff_line"] = cutoff_line

    json.dump(output, sys.stdout, indent=2)
    print()

    sys.exit(0 if valid else 1)


if __name__ == "__main__":
    main()
