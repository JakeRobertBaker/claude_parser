"""Application service that powers MCP tools (read/submit/commit)."""

from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Any

from claude_parser.application.batch_tools.cutoff_alignment import infer_cutoff_line
from claude_parser.application.batch_tools.models import (
    CommitResult,
    PriorContinuationPayload,
    ReadBatchPayload,
    SubmitCleanResult,
)
from claude_parser.application.batch_tools.semantic_boundary import (
    incomplete_trailing_semantic_unit_start,
)
from claude_parser.application.batch_tools.tree_preview import tree_preview
from claude_parser.application.serialization import tree_from_dict, tree_to_dict
from claude_parser.application.tokens import approximate_claude_tokens
from claude_parser.domain.annotation_parser import AnnotationEvent, parse_annotations
from claude_parser.domain.annotation_tree_builder import (
    active_trace_ids,
    has_visible_nodes,
    process_batch_annotations,
)
from claude_parser.domain.node import TreeDict
from claude_parser.domain.validator import validate_annotations
from claude_parser.ports.state import BatchContext, StatePort

logger = logging.getLogger(__name__)

_ALIGNMENT_CONFIDENCE_MIN = 0.6
_ALIGNMENT_MIN_CUTOFF_TOKEN_RATIO = 0.2
_CLEAN_TOKEN_HARD_WARNING_RATIO = 0.4


class BatchToolsService:
    """Application service backing the MCP batch tools."""

    def __init__(self, state: StatePort):
        self._state = state
        self._context: BatchContext | None = None
        self._known_ids: list[str] = []
        self._tree_dict: TreeDict = TreeDict()
        self._current_ordinal: int = 0
        self.prepare_batch()

    def begin_batch(
        self,
        context: BatchContext,
        known_ids: list[str],
        tree_dict: TreeDict,
        current_ordinal: int,
    ) -> None:
        self._context = context
        self._known_ids = list(known_ids)
        self._tree_dict = tree_dict
        self._current_ordinal = current_ordinal
        self.prepare_batch()

    def prepare_batch(self) -> None:
        self._submitted = False
        self._last_submit_valid = False
        self._inferred_cutoff_line: int | None = None
        self._committed_source_line: int | None = None
        self._continuation_node_id: str | None = None

    def succeeded(self) -> bool:
        return self._submitted

    def committed_source_line(self) -> int | None:
        return self._committed_source_line

    def committed_continuation_node_id(self) -> str | None:
        return self._continuation_node_id

    def tool_specs(self) -> list[dict[str, Any]]:
        return _TOOL_SPECS

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name == "read_batch":
            payload = self.build_read_batch_payload()
            return asdict(payload)
        if name == "submit_clean":
            cleaned_text = arguments["cleaned_text"]
            result = self.handle_submit_clean(
                cleaned_text,
                cutoff_kind=arguments["cutoff_kind"],
                continuation_node_id=arguments.get("continuation_node_id"),
            )
            data = asdict(result)
            if data["match_confidence"] is not None:
                data["match_confidence"] = round(data["match_confidence"], 3)
            return data
        if name == "commit_batch":
            result = self.handle_commit_batch()
            if result.success:
                return {"status": "ok"}
            return {"status": "error", "error": result.error}
        raise ValueError(f"Unknown tool: {name}")

    def build_read_batch_payload(self) -> ReadBatchPayload:
        context = self._require_context()
        return ReadBatchPayload(
            raw_content=context.raw_content,
            batch_line_count=context.raw_line_count,
            raw_token_count=context.raw_token_count,
            current_tree=tree_preview(self._tree_dict),
            prior_clean_context=context.prior_clean_context,
            next_raw_context=context.next_raw_context,
            next_raw_context_line_count=context.next_raw_context_line_count,
            next_raw_context_token_count=context.next_raw_context_token_count,
            prior_continuation=self._prior_continuation_payload(context),
            known_ids=self._known_ids,
            memory_text=context.memory_text,
        )

    def handle_submit_clean(
        self,
        cleaned_text: str,
        cutoff_kind: str,
        continuation_node_id: str | None = None,
    ) -> SubmitCleanResult:
        context = self._require_context()
        errors: list[str] = []
        warnings: list[str] = []

        if cutoff_kind not in {"clean_boundary", "continuation"}:
            errors.append(
                "cutoff_kind must be either 'clean_boundary' or 'continuation'."
            )
        elif cutoff_kind == "clean_boundary" and continuation_node_id is not None:
            errors.append(
                "continuation_node_id must be omitted for a clean_boundary cutoff."
            )
        elif cutoff_kind == "continuation" and not continuation_node_id:
            errors.append(
                "continuation_node_id is required for a continuation cutoff."
            )

        cleaned_tokens = approximate_claude_tokens(cleaned_text)
        hard_token_target = max(
            1, int(context.clean_token_target * _CLEAN_TOKEN_HARD_WARNING_RATIO)
        )
        if cleaned_tokens < hard_token_target:
            warnings.append(
                "Cleaned text is ~%d tokens, hard minimum is ~%d tokens (hard warning)."
                % (cleaned_tokens, hard_token_target)
            )
        elif cleaned_tokens < context.clean_token_target:
            warnings.append(
                "Cleaned text is ~%d tokens, suggested minimum is ~%d tokens (soft warning)."
                % (cleaned_tokens, context.clean_token_target)
            )

        events = parse_annotations(cleaned_text)
        validation = validate_annotations(
            events,
            known_ids=set(self._known_ids),
            cleaned_text=cleaned_text,
            has_existing_nodes=has_visible_nodes(self._tree_dict),
        )
        errors.extend(validation.errors)
        warnings.extend(validation.warnings)

        raw_lines = context.raw_content.splitlines(keepends=True)
        next_context_lines = context.next_raw_context.splitlines(keepends=True)
        alignment = infer_cutoff_line(cleaned_text, raw_lines)
        if not alignment.ok:
            if alignment.error_code == "raw_has_no_content_tokens":
                errors.append(
                    "Alignment failed: raw batch has 0 alignable content tokens."
                )
            elif alignment.error_code == "cleaned_too_short_for_alignment":
                errors.append(
                    (
                        "Alignment failed: cleaned text has %d content tokens, "
                        "minimum required is %d (derived from raw content token count=%d)."
                    )
                    % (
                        alignment.cleaned_token_count,
                        alignment.min_cleaned_token_requirement,
                        alignment.raw_token_count,
                    )
                )
            elif alignment.error_code == "no_token_overlap":
                errors.append(
                    (
                        "Alignment failed: no token overlap between cleaned and raw content "
                        "(cleaned content tokens=%d, raw content tokens=%d)."
                    )
                    % (alignment.cleaned_token_count, alignment.raw_token_count)
                )
            else:
                errors.append("Alignment failed for an unknown reason.")
            return self._finalize_submit(
                errors,
                warnings,
                cutoff_kind=cutoff_kind,
                continuation_node_id=continuation_node_id,
            )

        assert alignment.cutoff_line is not None
        assert alignment.confidence is not None
        assert alignment.cutoff_token_count is not None

        cutoff_line = alignment.cutoff_line
        confidence = alignment.confidence
        next_raw_context_violation = False

        if next_context_lines:
            combined_alignment = infer_cutoff_line(
                cleaned_text, [*raw_lines, *next_context_lines]
            )
            next_raw_context_violation = (
                combined_alignment.ok
                and combined_alignment.cutoff_line is not None
                and combined_alignment.cutoff_line > context.raw_line_count
                and combined_alignment.matched_token_count
                > alignment.matched_token_count
            )
            if next_raw_context_violation:
                errors.append(
                    "Next raw context check failed: cleaned_text contains material "
                    "from read-only next_raw_context. Roll back within raw_content."
                )
        min_cutoff_tokens = max(
            1,
            int(alignment.raw_token_count * _ALIGNMENT_MIN_CUTOFF_TOKEN_RATIO),
        )

        if confidence < _ALIGNMENT_CONFIDENCE_MIN:
            errors.append(
                (
                    "Alignment confidence check failed: confidence=%.3f is below the "
                    "required minimum %.3f (matched_content_tokens=%d, "
                    "cleaned_content_tokens=%d, inferred_cutoff_batch_line=%d)."
                    % (
                        confidence,
                        _ALIGNMENT_CONFIDENCE_MIN,
                        alignment.matched_token_count,
                        alignment.cleaned_token_count,
                        cutoff_line,
                    )
                )
            )

        if alignment.cutoff_token_count < min_cutoff_tokens:
            errors.append(
                (
                    "Cutoff position check failed: inferred cutoff lands at content token %d, "
                    "but minimum allowed is %d (%.0f%% of raw content tokens=%d). "
                    "This usually means the submission stops too early in the batch."
                    % (
                        alignment.cutoff_token_count,
                        min_cutoff_tokens,
                        _ALIGNMENT_MIN_CUTOFF_TOKEN_RATIO * 100,
                        alignment.raw_token_count,
                    )
                )
            )

        incomplete_unit_start = incomplete_trailing_semantic_unit_start(
            raw_lines, next_context_lines
        )
        if (
            cutoff_kind == "clean_boundary"
            and incomplete_unit_start is not None
            and cutoff_line >= incomplete_unit_start
        ):
            errors.append(
                "Semantic boundary check failed: next_raw_context continues the "
                "semantic unit starting at raw_content line %d. Roll back before "
                "that heading, or use an allowed opening-unit continuation."
                % incomplete_unit_start
            )

        if errors:
            return self._finalize_submit(
                errors,
                warnings,
                cutoff_line=cutoff_line,
                confidence=confidence,
                next_raw_context_violation=next_raw_context_violation,
                cutoff_kind=cutoff_kind,
                continuation_node_id=continuation_node_id,
            )

        if cleaned_text and not cleaned_text.endswith("\n"):
            cleaned_text += "\n"

        raw_context = raw_lines[
            max(0, cutoff_line - 5) : min(len(raw_lines), cutoff_line + 2)
        ]
        cleaned_lines = cleaned_text.splitlines()
        clean_tail = cleaned_lines[-5:] if len(cleaned_lines) >= 5 else cleaned_lines

        proposed_tree = tree_preview(self._tree_dict)
        proposed_tree_dict: TreeDict | None = None
        try:
            proposed_tree_dict = self._build_proposed_tree(events, cleaned_text)
            proposed_tree = tree_preview(proposed_tree_dict)
        except (ValueError, KeyError) as exc:
            logger.warning("proposed_tree failed: %s", exc)
            errors.append(f"Could not build proposed_tree: {exc}")

        if cutoff_kind == "continuation" and continuation_node_id:
            trace = (
                active_trace_ids(proposed_tree_dict)
                if proposed_tree_dict is not None
                else []
            )
            active_leaf_id = trace[-1] if trace else None
            if continuation_node_id != active_leaf_id:
                errors.append(
                    "continuation_node_id must match the proposed tree's active leaf "
                    f"({active_leaf_id!r}); received {continuation_node_id!r}."
                )
            else:
                errors.extend(
                    self._validate_continuation_policy(
                        events, cleaned_text, continuation_node_id
                    )
                )

        if not errors:
            full_content = cleaned_text + "<!-- cutoff -->\n"
            self._state.write_clean_batch(self._current_ordinal, full_content)
            self._inferred_cutoff_line = cutoff_line
            self._continuation_node_id = continuation_node_id

        return self._finalize_submit(
            errors,
            warnings,
            cutoff_line=cutoff_line,
            confidence=confidence,
            raw_context=[line.rstrip("\n") for line in raw_context],
            clean_tail=clean_tail,
            proposed_tree=proposed_tree,
            cutoff_kind=cutoff_kind,
            continuation_node_id=continuation_node_id,
            next_raw_context_violation=next_raw_context_violation,
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
        cutoff_kind: str | None = None,
        continuation_node_id: str | None = None,
        next_raw_context_violation: bool = False,
    ) -> SubmitCleanResult:
        context = self._context
        batch_line_count = context.raw_line_count if context is not None else None
        rollback_lines = (
            max(0, batch_line_count - cutoff_line)
            if cutoff_line is not None and batch_line_count is not None
            else 0
        )
        result = SubmitCleanResult(
            valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
            inferred_cutoff_batch_line=cutoff_line,
            match_confidence=confidence,
            raw_context_around_cutoff=raw_context or [],
            clean_tail=clean_tail or [],
            proposed_tree=proposed_tree,
            batch_line_count=batch_line_count,
            rollback_lines=rollback_lines,
            next_raw_context_violation=next_raw_context_violation,
            cutoff_kind=cutoff_kind,
            continuation_node_id=continuation_node_id,
        )
        self._last_submit_valid = result.valid
        return result

    def handle_commit_batch(self) -> CommitResult:
        cutoff_batch_line = self._inferred_cutoff_line
        if cutoff_batch_line is None or not self._last_submit_valid:
            return CommitResult(
                success=False,
                error=(
                    "No valid submit_clean available. Call submit_clean until valid=true before commit_batch."
                ),
            )

        context = self._require_context()
        self._committed_source_line = context.raw_start_line + cutoff_batch_line
        self._submitted = True
        return CommitResult(success=True)

    def _require_context(self) -> BatchContext:
        if self._context is None:
            raise ValueError("No active batch. begin_batch() must be called first.")
        return self._context

    def _prior_continuation_payload(
        self, context: BatchContext
    ) -> PriorContinuationPayload | None:
        node_id = context.prior_continuation_node_id
        if node_id is None:
            return None
        try:
            node = self._tree_dict[node_id]
        except KeyError:
            logger.warning("Persisted continuation node %s is absent from tree", node_id)
            return None

        depth = 0
        cursor = node
        while cursor.parent is not None:
            depth += 1
            cursor = cursor.parent
        return PriorContinuationPayload(
            node_id=node.id,
            title=node.title,
            node_type=node.node_type.value,
            depth=depth,
            proves_id=node._proves_id,
            dependency_ids=list(node._dependency_ids),
        )

    def _validate_continuation_policy(
        self,
        events: list[AnnotationEvent],
        cleaned_text: str,
        continuation_node_id: str,
    ) -> list[str]:
        context = self._require_context()
        if not context.next_raw_context:
            return [
                "Continuation cutoff is invalid at source EOF because there is no "
                "next raw content to continue."
            ]

        if continuation_node_id == context.prior_continuation_node_id:
            return []

        header = next(
            (
                event
                for event in events
                if event.event_type == "header"
                and event.id == continuation_node_id
            ),
            None,
        )
        if header is None:
            return [
                "A new continuation node must be annotated in this batch's opening "
                "header block. Roll back before a later-starting unit."
            ]

        annotation_lines = {
            event.line_number for event in events if event.event_type == "header"
        }
        lines = cleaned_text.splitlines()
        has_substantive_prefix = any(
            line.strip() and line_number not in annotation_lines
            for line_number, line in enumerate(lines[: header.line_number - 1], start=1)
        )
        if has_substantive_prefix:
            return [
                "Continuation is allowed only for a prior continuation or a unit "
                "introduced in the opening annotation block. Roll back before this unit."
            ]
        return []

    def _build_proposed_tree(
        self, events: list[AnnotationEvent], cleaned_text: str
    ) -> TreeDict:
        tree_dict_copy = TreeDict()
        if self._tree_dict.root_node is not None:
            snapshot = tree_to_dict(self._tree_dict.root_node)
            _, tree_dict_copy = tree_from_dict(snapshot)

        cleaned_line_count = len(cleaned_text.splitlines())
        process_batch_annotations(
            events,
            tree_dict_copy,
            self._current_ordinal,
            cleaned_line_count,
        )
        return tree_dict_copy


_TOOL_SPECS: list[dict[str, Any]] = [
    {
        "name": "read_batch",
        "description": (
            "Read the committable raw batch plus read-only context before and after it. "
            "Only raw_content may appear in cleaned_text."
        ),
        "input_schema": {"type": "object", "properties": {}},
        "meta": {"anthropic/maxResultSizeChars": 500000},
    },
    {
        "name": "submit_clean",
        "description": (
            "Submit cleaned markdown with annotations. Returns validation info, inferred cutoff, "
            "raw context, clean tail, and proposed_tree."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "cleaned_text": {
                    "type": "string",
                    "description": (
                        "Cleaned markdown from raw_content up to the cutoff. Never include "
                        "prior_clean_context or next_raw_context."
                    ),
                },
                "cutoff_kind": {
                    "type": "string",
                    "enum": ["clean_boundary", "continuation"],
                    "description": (
                        "Use clean_boundary at a complete semantic boundary; use continuation "
                        "only when the cleaned text ends inside an unfinished unit."
                    ),
                },
                "continuation_node_id": {
                    "type": "string",
                    "description": (
                        "Required only for continuation; must be the active leaf node whose "
                        "content continues in the next batch."
                    ),
                },
            },
            "required": ["cleaned_text", "cutoff_kind"],
        },
    },
    {
        "name": "commit_batch",
        "description": (
            "Finalize this batch using the valid cutoff inferred by submit_clean."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
]
