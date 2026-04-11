"""Application service that powers MCP tools (read/submit/commit)."""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from typing import Any

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

    def succeeded(self) -> bool:
        return self._submitted

    def committed_source_line(self) -> int | None:
        return self._committed_source_line

    def tool_specs(self) -> list[ToolSpec]:
        return _TOOL_SPECS

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name == "read_batch":
            payload = self.build_read_batch_payload()
            return asdict(payload)
        if name == "submit_clean":
            cleaned_text = arguments["cleaned_text"]
            result = self.handle_submit_clean(cleaned_text)
            data = asdict(result)
            if data["match_confidence"] is not None:
                data["match_confidence"] = round(data["match_confidence"], 3)
            return data
        if name == "commit_batch":
            cutoff = arguments.get("cutoff_batch_line")
            result = self.handle_commit_batch(cutoff)
            if result.success:
                return {"status": "ok"}
            return {"status": "error", "error": result.error}
        raise ValueError(f"Unknown tool: {name}")

    def build_read_batch_payload(self) -> ReadBatchPayload:
        context = self._require_context()
        return ReadBatchPayload(
            raw_content=context.raw_content,
            batch_line_count=context.raw_line_count,
            current_tree=tree_preview(self._tree_dict),
            prior_clean_tail=context.prior_clean_tail,
            known_ids=self._known_ids,
            memory_text=context.memory_text,
        )

    def handle_submit_clean(self, cleaned_text: str) -> SubmitCleanResult:
        context = self._require_context()
        errors: list[str] = []
        warnings: list[str] = []

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
            return self._finalize_submit(errors, warnings)

        assert alignment.cutoff_line is not None
        assert alignment.confidence is not None
        assert alignment.cutoff_token_count is not None

        cutoff_line = alignment.cutoff_line
        confidence = alignment.confidence
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

        if errors:
            return self._finalize_submit(
                errors,
                warnings,
                cutoff_line=cutoff_line,
                confidence=confidence,
            )

        if cleaned_text and not cleaned_text.endswith("\n"):
            cleaned_text += "\n"

        full_content = cleaned_text + "<!-- cutoff -->\n"
        self._state.write_clean_batch(self._current_ordinal, full_content)
        self._inferred_cutoff_line = cutoff_line

        raw_context = raw_lines[
            max(0, cutoff_line - 5) : min(len(raw_lines), cutoff_line + 2)
        ]
        cleaned_lines = cleaned_text.splitlines()
        clean_tail = cleaned_lines[-5:] if len(cleaned_lines) >= 5 else cleaned_lines

        proposed_tree = tree_preview(self._tree_dict)
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

        context = self._require_context()
        self._committed_source_line = context.raw_start_line + cutoff_batch_line
        self._submitted = True
        return CommitResult(success=True)

    def _require_context(self) -> BatchContext:
        if self._context is None:
            raise ValueError("No active batch. begin_batch() must be called first.")
        return self._context

    def _build_proposed_tree_preview(
        self, events: list[AnnotationEvent], cleaned_text: str
    ) -> str:
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
        return tree_preview(tree_dict_copy)


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]
    meta: dict[str, Any] | None = None


_TOOL_SPECS: list[ToolSpec] = [
    ToolSpec(
        name="read_batch",
        description=(
            "Read current raw batch and context. Returns raw_content, batch_line_count, "
            "current_tree, prior_clean_tail, known_ids, memory_text."
        ),
        input_schema={"type": "object", "properties": {}},
        meta={"anthropic/maxResultSizeChars": 500000},
    ),
    ToolSpec(
        name="submit_clean",
        description=(
            "Submit cleaned markdown with annotations. Returns validation info, inferred cutoff, "
            "raw context, clean tail, and proposed_tree."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "cleaned_text": {
                    "type": "string",
                    "description": (
                        "Cleaned markdown up to the cutoff (exclude raw content after cutoff)."
                    ),
                }
            },
            "required": ["cleaned_text"],
        },
    ),
    ToolSpec(
        name="commit_batch",
        description=(
            "Finalize this batch. Call after submit_clean succeeds. Optional cutoff_batch_line overrides the inferred cutoff."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "cutoff_batch_line": {
                    "type": "integer",
                    "description": "1-indexed raw line within this batch where cleaning stops.",
                }
            },
        },
    ),
]
