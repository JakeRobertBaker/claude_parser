"""Application service that powers MCP tools (read/submit/commit)."""

from __future__ import annotations

import logging
import re
from dataclasses import asdict
from typing import Any

from claude_parser.application.batch_tools.cutoff_alignment import infer_cutoff_line
from claude_parser.application.batch_tools.heading_coverage import (
    source_heading_advisories,
)
from claude_parser.application.batch_tools.models import (
    AdjustDepthsResult,
    CommittableRawPayload,
    CommitResult,
    PriorContinuationPayload,
    ReadBatchPayload,
    ReadOnlyContextPayload,
    SubmitCleanResult,
)
from claude_parser.application.batch_tools.semantic_boundary import (
    incomplete_trailing_semantic_unit_start,
)
from claude_parser.application.batch_tools.tree_views import (
    inspect_tree,
    proposed_tree,
    tree_context,
)
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
from claude_parser.ports.math_validation import (
    MathValidationPort,
    MathValidationResult,
)
from claude_parser.ports.state import BatchContext, StatePort

logger = logging.getLogger(__name__)

_ALIGNMENT_CONFIDENCE_MIN = 0.6
_ALIGNMENT_MIN_CUTOFF_TOKEN_RATIO = 0.2
_CLEAN_TOKEN_HARD_WARNING_RATIO = 0.4


class BatchToolsService:
    """Application service backing the MCP batch tools."""

    def __init__(self, state: StatePort, math_validator: MathValidationPort):
        self._state = state
        self._math_validator = math_validator
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
        self._pending_cleaned_text: str | None = None
        self._pending_events: list[AnnotationEvent] = []
        self._pending_tree: TreeDict | None = None
        self._pending_math_validation: dict[str, Any] = {}
        self._pending_cutoff_kind: str | None = None

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
        if name == "inspect_tree":
            return inspect_tree(
                self._tree_dict,
                arguments["node_id"],
                child_offset=arguments.get("child_offset", 0),
                child_limit=arguments.get("child_limit", 50),
            )
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
        if name == "adjust_depths":
            result = self.handle_adjust_depths(arguments["edits"])
            return asdict(result)
        if name == "commit_batch":
            result = self.handle_commit_batch()
            if result.success:
                return {"status": "ok"}
            return {"status": "error", "error": result.error}
        raise ValueError(f"Unknown tool: {name}")

    def build_read_batch_payload(self) -> ReadBatchPayload:
        context = self._require_context()
        return ReadBatchPayload(
            committable_raw=CommittableRawPayload(
                scope=(
                    "COMMITTABLE SOURCE: cleaned_text may contain material only "
                    "from content in this object."
                ),
                content=context.raw_content,
                line_count=context.raw_line_count,
                token_count=context.raw_token_count,
            ),
            tree_context=tree_context(self._tree_dict),
            known_ids=self._known_ids,
            read_only_context=ReadOnlyContextPayload(
                scope=(
                    "READ-ONLY CONTEXT: use this only to understand boundaries; "
                    "never reproduce its content in cleaned_text."
                ),
                prior_clean_content=context.prior_clean_context,
                next_raw_content=context.next_raw_context,
                next_raw_line_count=context.next_raw_context_line_count,
                next_raw_token_count=context.next_raw_context_token_count,
                prior_continuation=self._prior_continuation_payload(context),
                memory_text=context.memory_text,
            ),
        )

    def handle_submit_clean(
        self,
        cleaned_text: str,
        cutoff_kind: str,
        continuation_node_id: str | None = None,
    ) -> SubmitCleanResult:
        context = self._require_context()
        self._clear_pending()
        errors: list[str] = []
        warnings: list[str] = []
        math_payload: dict[str, Any] = {}

        try:
            math_result = self._math_validator.validate(cleaned_text)
        except RuntimeError as exc:
            errors.append(f"Math validation unavailable: {exc}")
            self._clear_pending()
            return self._finalize_submit(
                errors,
                warnings,
                cutoff_kind=cutoff_kind,
                continuation_node_id=continuation_node_id,
            )

        cleaned_text = math_result.normalized_text
        math_payload = self._math_payload(math_result)
        errors.extend(
            f"Line {item.line}, column {item.column}: {item.message} "
            f"({item.code})."
            for item in math_result.errors
        )
        warnings.extend(
            f"Line {item.line}, column {item.column}: {item.message} "
            f"({item.code})."
            for item in math_result.warnings
        )

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
                math_validation=math_payload,
            )

        assert alignment.cutoff_line is not None
        assert alignment.confidence is not None
        assert alignment.cutoff_token_count is not None

        cutoff_line = alignment.cutoff_line
        confidence = alignment.confidence
        next_raw_context_violation = False

        committable_raw_context = raw_lines[
            max(0, cutoff_line - 5) : min(len(raw_lines), cutoff_line + 2)
        ]
        submitted_lines = cleaned_text.splitlines()
        submitted_clean_tail = (
            submitted_lines[-8:] if len(submitted_lines) >= 8 else submitted_lines
        )
        committable_raw_tail = raw_lines[-8:]
        read_only_next_raw_head = next_context_lines[:8]
        committable_raw_context_lines = [
            line.rstrip("\n") for line in committable_raw_context
        ]
        committable_raw_tail_lines = [
            line.rstrip("\n") for line in committable_raw_tail
        ]
        read_only_next_raw_head_lines = [
            line.rstrip("\n") for line in read_only_next_raw_head
        ]

        heading_advisories = source_heading_advisories(
            raw_lines, cutoff_line, events
        )

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
                    "from read_only_context.next_raw_content. Remove everything "
                    "after the last committable source material. Compare "
                    "submitted_clean_tail with committable_raw_tail and "
                    "read_only_next_raw_head returned in this response."
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
                "Semantic boundary check failed: read_only_context.next_raw_content "
                "continues the semantic unit starting at committable raw line %d. "
                "Roll back before that heading, or use an allowed opening-unit "
                "continuation."
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
                math_validation=math_payload,
                source_heading_advisories=heading_advisories,
                committable_raw_context=committable_raw_context_lines,
                submitted_clean_tail=submitted_clean_tail,
                committable_raw_tail=committable_raw_tail_lines,
                read_only_next_raw_head=read_only_next_raw_head_lines,
            )

        if cleaned_text and not cleaned_text.endswith("\n"):
            cleaned_text += "\n"

        proposed_tree_payload: dict[str, Any] = {}
        tree_advisories: list[dict[str, Any]] = []
        proposed_tree_dict: TreeDict | None = None
        try:
            proposed_tree_dict = self._build_proposed_tree(events, cleaned_text)
            proposed_tree_payload = proposed_tree(
                self._tree_dict, proposed_tree_dict, events
            )
            tree_advisories = self._proof_placement_advisories(
                proposed_tree_dict, events
            )
            warnings.extend(
                "Tree review: proof '%s' should be a sibling of '%s'; use "
                "annotation depth %s."
                % (item["node_id"], item["target_id"], item["suggested_depth"])
                for item in tree_advisories
            )
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

        if not errors and proposed_tree_dict is not None:
            self._pending_cleaned_text = cleaned_text
            self._pending_events = events
            self._pending_tree = proposed_tree_dict
            self._pending_math_validation = math_payload
            self._pending_cutoff_kind = cutoff_kind
            self._inferred_cutoff_line = cutoff_line
            self._continuation_node_id = continuation_node_id
        else:
            self._clear_pending()

        return self._finalize_submit(
            errors,
            warnings,
            cutoff_line=cutoff_line,
            confidence=confidence,
            proposed_tree=proposed_tree_payload,
            math_validation=math_payload,
            tree_advisories=tree_advisories,
            source_heading_advisories=heading_advisories,
            cutoff_kind=cutoff_kind,
            continuation_node_id=continuation_node_id,
            next_raw_context_violation=next_raw_context_violation,
            committable_raw_context=committable_raw_context_lines,
            submitted_clean_tail=submitted_clean_tail,
            committable_raw_tail=committable_raw_tail_lines,
            read_only_next_raw_head=read_only_next_raw_head_lines,
        )

    def _finalize_submit(
        self,
        errors: list[str],
        warnings: list[str],
        *,
        cutoff_line: int | None = None,
        confidence: float | None = None,
        committable_raw_context: list[str] | None = None,
        submitted_clean_tail: list[str] | None = None,
        committable_raw_tail: list[str] | None = None,
        read_only_next_raw_head: list[str] | None = None,
        proposed_tree: dict[str, Any] | None = None,
        math_validation: dict[str, Any] | None = None,
        tree_advisories: list[dict[str, Any]] | None = None,
        source_heading_advisories: list[dict[str, Any]] | None = None,
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
            commit_ready=len(errors) == 0 and not tree_advisories,
            errors=errors,
            warnings=warnings,
            inferred_cutoff_batch_line=cutoff_line,
            match_confidence=confidence,
            committable_raw_context_around_cutoff=committable_raw_context or [],
            submitted_clean_tail=submitted_clean_tail or [],
            committable_raw_tail=committable_raw_tail or [],
            read_only_next_raw_head=read_only_next_raw_head or [],
            proposed_tree=proposed_tree or {},
            math_validation=math_validation or {},
            tree_advisories=tree_advisories or [],
            source_heading_advisories=source_heading_advisories or [],
            batch_line_count=batch_line_count,
            rollback_lines=rollback_lines,
            next_raw_context_violation=next_raw_context_violation,
            cutoff_kind=cutoff_kind,
            continuation_node_id=continuation_node_id,
        )
        self._last_submit_valid = result.valid
        return result

    def handle_adjust_depths(
        self, edits: list[dict[str, Any]]
    ) -> AdjustDepthsResult:
        if self._pending_cleaned_text is None or self._pending_tree is None:
            self._last_submit_valid = False
            return AdjustDepthsResult(
                valid=False,
                commit_ready=False,
                errors=[
                    "No pending valid submission. Call submit_clean until valid=true "
                    "before adjust_depths."
                ],
            )

        current_proposal = proposed_tree(
            self._tree_dict, self._pending_tree, self._pending_events
        )
        errors: list[str] = []
        if not isinstance(edits, list) or not edits:
            errors.append("edits must be a non-empty list.")
            return self._failed_adjust(errors, current_proposal)

        headers = {
            event.id: event
            for event in self._pending_events
            if event.event_type == "header"
        }
        normalized_edits: list[dict[str, int | str]] = []
        seen: set[str] = set()
        for edit in edits:
            if not isinstance(edit, dict):
                errors.append("Each depth edit must be an object.")
                continue
            node_id = edit.get("node_id")
            depth = edit.get("depth")
            if not isinstance(node_id, str) or not node_id:
                errors.append("Each depth edit requires a non-empty node_id.")
                continue
            if node_id in seen:
                errors.append(f"Duplicate depth edit for node '{node_id}'.")
                continue
            seen.add(node_id)
            if node_id not in headers:
                errors.append(
                    f"Node '{node_id}' was not created by the pending batch and "
                    "cannot be depth-edited."
                )
                continue
            if isinstance(depth, bool) or not isinstance(depth, int):
                errors.append(f"Depth for node '{node_id}' must be an integer.")
                continue
            if depth < 1 or depth > 32:
                errors.append(
                    f"Depth for node '{node_id}' must be between 1 and 32."
                )
                continue
            normalized_edits.append({"node_id": node_id, "depth": depth})

        if errors:
            return self._failed_adjust(errors, current_proposal)

        lines = self._pending_cleaned_text.splitlines(keepends=True)
        for edit in normalized_edits:
            node_id = str(edit["node_id"])
            depth = int(edit["depth"])
            line_index = headers[node_id].line_number - 1
            line = lines[line_index]
            ending = "\n" if line.endswith("\n") else ""
            body = line[:-1] if ending else line
            match = re.match(r"^(\s*@\s*)-+(\s+.*)$", body)
            if match is None:
                errors.append(
                    f"Could not locate the annotation depth marker for '{node_id}'."
                )
                continue
            lines[line_index] = (
                match.group(1) + ("-" * depth) + match.group(2) + ending
            )
        if errors:
            return self._failed_adjust(errors, current_proposal)

        snapshot = (
            self._pending_cleaned_text,
            self._pending_events,
            self._pending_tree,
            self._pending_math_validation,
            self._inferred_cutoff_line,
            self._continuation_node_id,
            self._pending_cutoff_kind,
        )
        result = self.handle_submit_clean(
            "".join(lines),
            cutoff_kind=self._pending_cutoff_kind or "clean_boundary",
            continuation_node_id=self._continuation_node_id,
        )
        if not result.valid:
            (
                self._pending_cleaned_text,
                self._pending_events,
                self._pending_tree,
                self._pending_math_validation,
                self._inferred_cutoff_line,
                self._continuation_node_id,
                self._pending_cutoff_kind,
            ) = snapshot
            self._last_submit_valid = False
            return AdjustDepthsResult(
                valid=False,
                commit_ready=False,
                errors=result.errors,
                warnings=result.warnings,
                proposed_tree=current_proposal,
                math_validation=self._pending_math_validation,
                tree_advisories=result.tree_advisories,
                source_heading_advisories=result.source_heading_advisories,
            )

        return AdjustDepthsResult(
            valid=True,
            commit_ready=result.commit_ready,
            warnings=result.warnings,
            applied_edits=normalized_edits,
            proposed_tree=result.proposed_tree,
            math_validation=result.math_validation,
            tree_advisories=result.tree_advisories,
            source_heading_advisories=result.source_heading_advisories,
        )

    def _failed_adjust(
        self, errors: list[str], current_proposal: dict[str, Any]
    ) -> AdjustDepthsResult:
        self._last_submit_valid = False
        return AdjustDepthsResult(
            valid=False,
            commit_ready=False,
            errors=errors,
            proposed_tree=current_proposal,
            math_validation=self._pending_math_validation,
        )

    def handle_commit_batch(self) -> CommitResult:
        cutoff_batch_line = self._inferred_cutoff_line
        if (
            cutoff_batch_line is None
            or not self._last_submit_valid
            or self._pending_cleaned_text is None
        ):
            return CommitResult(
                success=False,
                error=(
                    "No valid submit_clean available. Call submit_clean until valid=true before commit_batch."
                ),
            )

        assert self._pending_tree is not None
        unresolved_tree_advisories = self._proof_placement_advisories(
            self._pending_tree, self._pending_events
        )
        if unresolved_tree_advisories:
            return CommitResult(
                success=False,
                error=(
                    "Tree review is unresolved: proof nodes must be siblings of "
                    "the statements they prove. Apply the suggested tree_advisories "
                    "with adjust_depths before commit_batch."
                ),
            )

        context = self._require_context()
        full_content = self._pending_cleaned_text + "<!-- cutoff -->\n"
        self._state.write_clean_batch(self._current_ordinal, full_content)
        self._committed_source_line = context.raw_start_line + cutoff_batch_line
        self._submitted = True
        return CommitResult(success=True)

    def _clear_pending(self) -> None:
        self._last_submit_valid = False
        self._inferred_cutoff_line = None
        self._continuation_node_id = None
        self._pending_cleaned_text = None
        self._pending_events = []
        self._pending_tree = None
        self._pending_math_validation = {}
        self._pending_cutoff_kind = None

    @staticmethod
    def _math_payload(result: MathValidationResult) -> dict[str, Any]:
        return {
            "expressions_checked": result.expressions_checked,
            "corrections": [asdict(item) for item in result.corrections],
            "warnings": [asdict(item) for item in result.warnings],
            "errors": [asdict(item) for item in result.errors],
        }

    @staticmethod
    def _proof_placement_advisories(
        proposed_tree_dict: TreeDict,
        events: list[AnnotationEvent],
    ) -> list[dict[str, Any]]:
        advisories: list[dict[str, Any]] = []
        for event in events:
            if event.event_type != "header" or event.node_type != "proof":
                continue
            if not event.proves:
                continue
            try:
                proof = proposed_tree_dict[event.id]
                target = proposed_tree_dict[event.proves]
            except KeyError:
                continue
            proof_parent_id = proof.parent.id if proof.parent is not None else None
            target_parent_id = target.parent.id if target.parent is not None else None
            if proof_parent_id == target_parent_id:
                continue

            target_depth = 0
            cursor = target
            while cursor.parent is not None:
                target_depth += 1
                cursor = cursor.parent
            advisories.append(
                {
                    "code": "proof_should_be_statement_sibling",
                    "node_id": event.id,
                    "target_id": event.proves,
                    "current_parent_id": proof_parent_id,
                    "expected_parent_id": target_parent_id,
                    "suggested_depth": target_depth,
                }
            )
        return advisories

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
                "introduced in the opening annotation block. If this candidate ends "
                "after a complete statement or proof, keep the candidate and retry "
                "with cutoff_kind='clean_boundary' and no continuation_node_id. "
                "Otherwise roll back before the later-starting unit."
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
            "Call exactly once. Returns a separately nested COMMITTABLE SOURCE and "
            "READ-ONLY CONTEXT. Only committable_raw.content may appear in cleaned_text."
        ),
        "input_schema": {"type": "object", "properties": {}},
        "meta": {"anthropic/maxResultSizeChars": 500000},
    },
    {
        "name": "inspect_tree",
        "description": (
            "Inspect one existing tree node, its ancestors, and a paginated slice "
            "of its direct children. Use when tree_context omits an older branch."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "node_id": {"type": "string"},
                "child_offset": {"type": "integer", "minimum": 0},
                "child_limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 100,
                },
            },
            "required": ["node_id"],
        },
    },
    {
        "name": "submit_clean",
        "description": (
            "Submit cleaned markdown with annotations. Returns validation info, "
            "cutoff diagnostics, proposed_tree, advisories, and commit_ready."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "cleaned_text": {
                    "type": "string",
                    "description": (
                        "Cleaned markdown from committable_raw.content up to the "
                        "cutoff. Never include any read_only_context content."
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
        "name": "adjust_depths",
        "description": (
            "Transactionally edit only the annotation depths of nodes created by "
            "the pending valid submission. Returns the complete updated batch tree "
            "and commit_ready status."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "edits": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "properties": {
                            "node_id": {"type": "string"},
                            "depth": {
                                "type": "integer",
                                "minimum": 1,
                                "maximum": 32,
                            },
                        },
                        "required": ["node_id", "depth"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["edits"],
        },
    },
    {
        "name": "commit_batch",
        "description": (
            "Approve the displayed proposed tree, persist the pending clean batch, "
            "and finalize its validated cutoff."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
]
