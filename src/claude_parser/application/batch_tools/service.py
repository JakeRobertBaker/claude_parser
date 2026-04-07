from __future__ import annotations

import logging

from claude_parser.application.batch_tools.cutoff_alignment import infer_cutoff_line
from claude_parser.application.batch_tools.models import (
    CommitResult,
    ReadBatchPayload,
    SubmitCleanResult,
)
from claude_parser.application.batch_tools.tree_preview import tree_preview
from claude_parser.application.serialization import tree_from_dict, tree_to_dict
from claude_parser.application.tokens import approximate_claude_tokens
from claude_parser.domain.annotation_parser import AnnotationEvent, parse_annotations
from claude_parser.domain.annotation_tree_builder import (
    has_visible_nodes,
    process_batch_annotations,
)
from claude_parser.domain.node import TreeDict
from claude_parser.domain.validator import validate_annotations
from claude_parser.ports.state import StatePort

logger = logging.getLogger(__name__)


class BatchToolsService:
    """Application service backing the MCP batch tools."""

    def __init__(self, state: StatePort):
        self._state = state
        self.prepare_batch()

    def prepare_batch(self) -> None:
        self._submitted = False
        self._last_submit_valid = False
        self._inferred_cutoff_line: int | None = None

    def succeeded(self) -> bool:
        return self._submitted

    def build_read_batch_payload(self) -> ReadBatchPayload:
        context = self._state.get_batch_context()
        return ReadBatchPayload(
            raw_content=context.raw_content,
            batch_line_count=context.raw_line_count,
            current_tree=tree_preview(self._state.tree_dict),
            prior_clean_tail=context.prior_clean_tail,
            known_ids=self._state.known_ids,
            memory_text=context.memory_text,
        )

    def handle_submit_clean(self, cleaned_text: str) -> SubmitCleanResult:
        context = self._state.get_batch_context()
        errors: list[str] = []
        warnings: list[str] = []

        cleaned_tokens = approximate_claude_tokens(cleaned_text)
        if cleaned_tokens < context.min_tokens:
            warnings.append(
                "Cleaned text is ~%d tokens, suggested minimum is ~%d tokens (soft warning)."
                % (cleaned_tokens, context.min_tokens)
            )

        events = parse_annotations(cleaned_text)
        validation = validate_annotations(
            events,
            known_ids=set(self._state.known_ids),
            cleaned_text=cleaned_text,
            has_existing_nodes=has_visible_nodes(self._state.tree_dict),
        )
        errors.extend(validation.errors)
        warnings.extend(validation.warnings)

        raw_lines = context.raw_content.splitlines(keepends=True)
        inferred = infer_cutoff_line(cleaned_text, raw_lines)
        if inferred is None:
            errors.append(
                "Cleaned text is too short to align with raw content. Submit >=20 content tokens."
            )
            return self._finalize_submit(errors, warnings)

        cutoff_line, confidence = inferred
        min_cutoff = max(1, int(context.raw_line_count * 0.2))
        if confidence < 0.6 or cutoff_line < min_cutoff:
            errors.append(
                (
                    "Could not align cleaned text to raw (confidence=%.2f, inferred_line=%d, batch has %d lines)."
                    % (confidence, cutoff_line, context.raw_line_count)
                )
            )
            errors.append(
                "Re-read the raw batch and resubmit with cleaned text matching the raw content more closely."
            )
            return self._finalize_submit(
                errors, warnings, cutoff_line=None, confidence=None
            )

        if cleaned_text and not cleaned_text.endswith("\n"):
            cleaned_text += "\n"

        full_content = cleaned_text + "<!-- cutoff -->\n"
        self._state.write_clean_batch(full_content)
        self._inferred_cutoff_line = cutoff_line

        raw_context = raw_lines[
            max(0, cutoff_line - 5) : min(len(raw_lines), cutoff_line + 2)
        ]
        cleaned_lines = cleaned_text.splitlines()
        clean_tail = cleaned_lines[-5:] if len(cleaned_lines) >= 5 else cleaned_lines

        proposed_tree = tree_preview(self._state.tree_dict)
        if not errors:
            try:
                proposed_tree = self._build_proposed_tree_preview(events, cleaned_text)
            except (ValueError, KeyError) as exc:
                logger.warning("proposed_tree failed: %s", exc)
                errors.append(f"Could not build proposed_tree: {exc}")

        return self._finalize_submit(
            errors,
            warnings,
            cutoff_line=cutoff_line,
            confidence=confidence,
            raw_context=[line.rstrip("\n") for line in raw_context],
            clean_tail=clean_tail,
            proposed_tree=proposed_tree,
        )

    def _finalize_submit(
        self,
        errors: list[str],
        warnings: list[str],
        *,
        cutoff_line: int | None = None,
        confidence: float | None = None,
        raw_context: list[str] | None = None,
        clean_tail: list[str] | None = None,
        proposed_tree: str = "",
    ) -> SubmitCleanResult:
        result = SubmitCleanResult(
            valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
            inferred_cutoff_batch_line=cutoff_line,
            match_confidence=confidence,
            raw_context_around_cutoff=raw_context or [],
            clean_tail=clean_tail or [],
            proposed_tree=proposed_tree,
        )
        self._last_submit_valid = result.valid
        return result

    def handle_commit_batch(self, cutoff_batch_line: int | None) -> CommitResult:
        if cutoff_batch_line is None:
            cutoff_batch_line = self._inferred_cutoff_line

        if cutoff_batch_line is None or not self._last_submit_valid:
            return CommitResult(
                success=False,
                error=(
                    "No valid submit_clean available. Call submit_clean until valid=true before commit_batch."
                ),
            )

        context = self._state.get_batch_context()
        source_line = context.raw_start_line + cutoff_batch_line
        self._state.set_cutoff(source_line)
        self._submitted = True
        return CommitResult(success=True)

    def _build_proposed_tree_preview(
        self, events: list[AnnotationEvent], cleaned_text: str
    ) -> str:
        tree_dict_copy = TreeDict()
        if self._state.tree_dict.root_node is not None:
            snapshot = tree_to_dict(self._state.tree_dict.root_node)
            _, tree_dict_copy = tree_from_dict(snapshot)

        cleaned_line_count = len(cleaned_text.splitlines())
        process_batch_annotations(
            events,
            tree_dict_copy,
            self._state.current_ordinal,
            cleaned_line_count,
        )
        return tree_preview(tree_dict_copy)
