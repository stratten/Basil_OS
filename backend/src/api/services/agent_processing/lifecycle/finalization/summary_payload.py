"""Summary and payload assembly for agent task finalization."""

from __future__ import annotations

import traceback
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from .file_result_extraction import extract_files_from_steps
from .evaluation import compose_outcome_intro, default_outcome_reason


# Minimum length of recovered narrative content that counts as "substantive" when
# deciding whether an evaluator objection should be overridden. Shared by the
# context-only follow-up override and the plausibility-doubt override.
SUBSTANTIVE_CONTENT_MIN_CHARS = 300


@dataclass
class StepMetrics:
    completed: int
    total: int
    duration_ms: Optional[int]


@dataclass
class ContextOnlyOverrideResult:
    success: bool
    outcome: str
    outcome_reason: str


def is_non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and len(value.strip()) > 0


def compose_summary(
    success: bool,
    app_context: Optional[str],
    files: List[Dict[str, str]],
    steps_completed: int,
    steps_total: int,
    content_messages: Optional[List[str]] = None,
    outcome: str = "success",
    outcome_reason: Optional[str] = None,
) -> str:
    """
    Compose user-facing summary by combining narrative content with structured metadata.

    CRITICAL:
    - Always show actual content/results if available
    - ALWAYS append structured metadata (app, files, steps) at the end
    """
    parts: List[str] = []

    # PART 1: Include ALL content from messages - NO FILTERING
    if content_messages:
        # Join all messages together, no filtering, no marker removal
        content = "\n\n".join([msg.strip() for msg in content_messages if msg and msg.strip()])

        if content:
            outcome_intro = compose_outcome_intro(outcome, outcome_reason)
            if outcome_intro:
                content = f"{outcome_intro}\n\n{content}"
            elif not success and steps_total > 0:
                content = (
                    "Partial result: I was not able to fully complete the request.\n\n"
                    f"{content}"
                )
            parts.append(content)

    # PART 2: ALWAYS append structured metadata
    metadata_lines: List[str] = []

    # Show app context if meaningful
    if is_non_empty_string(app_context):
        metadata_lines.append(f"• Active app at request: {app_context}")

    # Show file info if there are files
    if files:
        first = files[0]
        metadata_lines.append(f"• File: {first.get('name', '')}")
        if is_non_empty_string(first.get("full_path")):
            metadata_lines.append(f"• Path: {first['full_path']}")

    # Show step progress if there were actual steps
    if steps_total > 0:
        metadata_lines.append(f"• Steps: {steps_completed}/{steps_total} completed")

    if metadata_lines:
        # Use double newlines to ensure markdown renders each bullet on its own line
        parts.append("\n\n".join(metadata_lines))

    # Combine narrative + metadata, or just metadata if no narrative
    if parts:
        return "\n\n".join(parts)
    return f"Workflow {'completed' if success else 'failed'}."


def derive_step_metrics(
    metrics: Optional[Dict[str, Any]],
    steps: List[Dict[str, Any]],
) -> StepMetrics:
    if metrics and isinstance(metrics, dict):
        return StepMetrics(
            completed=int(metrics.get("steps_completed") or 0),
            total=int(metrics.get("steps_total") or (len(steps) if steps else 0)),
            duration_ms=int(metrics.get("duration_ms") or 0),
        )

    return StepMetrics(
        total=len(steps) if steps else 0,
        completed=sum(1 for s in (steps or []) if (
            s.get("success") is True
            or s.get("status") in ("success", "completed")
        )),
        duration_ms=None,
    )


def merge_file_results(
    steps: List[Dict[str, Any]],
) -> List[Dict[str, str]]:
    files_from_steps = extract_files_from_steps(steps or [])

    files: List[Dict[str, str]] = []
    seen: set[Tuple[str, str]] = set()

    for entry in files_from_steps:
        name = entry.get("name") or ""
        full_path = entry.get("full_path") or ""
        key = (name, full_path)
        if key not in seen:
            files.append({
                "name": name,
                "full_path": full_path,
                "operation": entry.get("operation") or "",
                **({"source_path": entry["source_path"]} if entry.get("source_path") else {}),
                **({"kind": entry["kind"]} if entry.get("kind") else {}),
            })
            seen.add(key)

    return files


def merge_read_file_artifacts(
    files: List[Dict[str, str]],
    read_file_artifacts: Optional[List[Dict[str, str]]],
) -> List[Dict[str, str]]:
    """Append operation='read' entries (deduped by name+full_path); existing entries win."""
    if not read_file_artifacts:
        return files

    merged = list(files)
    seen: set[Tuple[str, str]] = {
        (entry.get("name") or "", entry.get("full_path") or "")
        for entry in merged
    }

    for artifact in read_file_artifacts:
        if not isinstance(artifact, dict):
            continue
        full_path = artifact.get("full_path") or artifact.get("path") or ""
        name = artifact.get("name") or ""
        if not is_non_empty_string(name) or not is_non_empty_string(full_path):
            continue
        key = (name.strip(), full_path.strip())
        if key in seen:
            continue
        merged.append({
            "name": key[0],
            "full_path": key[1],
            "operation": "read",
        })
        seen.add(key)

    return merged


async def recover_standardized_messages_from_database(
    agent_task_id: Optional[str],
    standardized_messages: Optional[List[str]],
) -> Optional[List[str]]:
    """Retrieve accumulated output when the agent did not pass enough content."""
    if not agent_task_id or (standardized_messages and len("\n".join(standardized_messages or [])) >= 100):
        return standardized_messages

    print(
        "🔍 FINALIZER: standardized_messages insufficient "
        f"({len(standardized_messages or [])} items), querying database for accumulated output"
    )
    try:
        # Query the canonical SQLite service directly, matching the pattern used
        # by async_finalizer.py.
        from api.dependencies import get_sqlite_knowledge_service
        knowledge_service = get_sqlite_knowledge_service()

        # Query the agent_task record to get accumulated output
        voice_cmd = await knowledge_service.agent_task_service.get_agent_task(agent_task_id)
        if voice_cmd:
            # AgentTask is a dataclass, access result_data field which contains execution results
            result_data = voice_cmd.result_data or {}

            # Check for accumulated_output in result_data (stored by agent execution)
            if isinstance(result_data, dict):
                data_field = result_data.get("data", {})
                if isinstance(data_field, dict):
                    accumulated_output = data_field.get("accumulated_output", "")

                    if accumulated_output and len(accumulated_output.strip()) > 100:
                        print(
                            "✅ FINALIZER: Retrieved "
                            f"{len(accumulated_output)} chars from database result_data.data.accumulated_output"
                        )
                        # Use the accumulated output as standardized_messages
                        return [accumulated_output]
                    print("⚠️ FINALIZER: Database query successful but no substantial accumulated_output found")
                else:
                    print(f"⚠️ FINALIZER: result_data.data is not a dict: {type(data_field)}")
            else:
                print(f"⚠️ FINALIZER: result_data is not a dict: {type(result_data)}")
        else:
            print(f"⚠️ FINALIZER: No agent_task found in database for agent_task_id: {agent_task_id}")
    except Exception as db_err:
        print(f"⚠️ FINALIZER: Failed to query database for accumulated output: {db_err}")
        print(f"⚠️ FINALIZER: Traceback: {traceback.format_exc()}")
        # Continue with whatever we have
    return standardized_messages


def collect_validation_issues(
    *,
    files: List[Dict[str, str]],
) -> List[str]:
    validation_issues: List[str] = []
    for f in files:
        if not is_non_empty_string(f.get("name")):
            validation_issues.append("A file entry is missing name.")
        # Only require full_path for create/modify operations, not delete
        operation = f.get("operation", "").lower()
        if operation != "delete" and not is_non_empty_string(f.get("full_path")):
            validation_issues.append(f"A file entry for '{f.get('name', 'unknown')}' is missing full_path.")
    return validation_issues


def _step_result_payload(step: Dict[str, Any]) -> Dict[str, Any]:
    result = step.get("result")
    if isinstance(result, dict) and isinstance(result.get("result"), dict):
        return result["result"]
    if isinstance(result, dict):
        return result
    return {}


def _step_outcome_review(step: Dict[str, Any]) -> Dict[str, Any]:
    review = step.get("outcome_review")
    if isinstance(review, dict):
        return review
    result_payload = _step_result_payload(step)
    review = result_payload.get("outcome_review")
    return review if isinstance(review, dict) else {}


def _step_outcome_status(step: Dict[str, Any]) -> str:
    status = step.get("outcome_verification_status")
    if isinstance(status, str) and status.strip():
        return status.strip().lower()
    result_payload = _step_result_payload(step)
    status = result_payload.get("outcome_verification_status")
    return status.strip().lower() if isinstance(status, str) and status.strip() else "not_reported"


def _step_needs_outcome_review(step: Dict[str, Any]) -> bool:
    if step.get("needs_outcome_review") is True:
        return True
    return _step_result_payload(step).get("needs_outcome_review") is True


def collect_outcome_review_issues(steps: List[Dict[str, Any]]) -> List[str]:
    """Collect unresolved material-write review issues from structured step fields."""
    issues: List[str] = []
    unresolved_indexes: List[int] = []

    for index, step in enumerate(steps or []):
        if not isinstance(step, dict):
            continue

        review = _step_outcome_review(step)
        status = _step_outcome_status(step)
        material_write = bool(review.get("material_write", False))

        if material_write and status == "verified":
            unresolved_indexes.clear()
            issues.clear()
            continue

        if _step_needs_outcome_review(step):
            unresolved_indexes.append(index)
            summary = review.get("summary") or "Material outcome was not verified."
            issues.append(f"Step {index + 1}: {summary}")
            continue

        if status == "failed":
            unresolved_indexes.append(index)
            summary = review.get("summary") or "Material outcome verification failed."
            discrepancies = review.get("discrepancies") if isinstance(review.get("discrepancies"), list) else []
            detail = f" Discrepancies: {', '.join(str(item) for item in discrepancies)}" if discrepancies else ""
            issues.append(f"Step {index + 1}: {summary}{detail}")
            continue

        if material_write and status not in {"verified", "not_applicable"}:
            unresolved_indexes.append(index)
            summary = review.get("summary") or f"Material write has verification status '{status}'."
            issues.append(f"Step {index + 1}: {summary}")

    if not unresolved_indexes:
        return []
    return issues


def apply_context_only_followup_override(
    *,
    success: bool,
    outcome: str,
    outcome_reason: str,
    should_retry: bool,
    steps_total: int,
    steps_completed: int,
    failure_basis: str,
    standardized_messages: Optional[List[str]],
    tool_error_history: Optional[List[Dict[str, str]]],
    validation_issues: List[str],
) -> ContextOnlyOverrideResult:
    """Avoid false failures when the evaluator's own structured field says its only
    objection was an unresolved context reference, not a content or tool defect."""
    if (
        success is False
        and not should_retry
        and steps_total > 0
        and steps_completed >= steps_total
        and failure_basis == "context_ambiguity"
        and not tool_error_history
        and not validation_issues
    ):
        content = "\n".join(standardized_messages or []).strip()
        if len(content) >= SUBSTANTIVE_CONTENT_MIN_CHARS:
            print("✅ FINALIZER: Treating context-ambiguity evaluation objection as success")
            return ContextOnlyOverrideResult(
                success=True,
                outcome="success",
                outcome_reason="",
            )

    return ContextOnlyOverrideResult(
        success=success,
        outcome=outcome,
        outcome_reason=outcome_reason,
    )


def apply_plausibility_doubt_override(
    *,
    success: bool,
    outcome: str,
    outcome_reason: str,
    failure_basis: str,
    has_tool_errors: bool,
    has_failed_steps: bool,
    outcome_review_issues: List[str],
    standardized_messages: Optional[List[str]],
) -> ContextOnlyOverrideResult:
    """Prevent stale-knowledge doubt from failing a clean, substantive, tool-grounded result.

    Fires only when the evaluator's sole basis for a non-success verdict was that the
    tool-returned facts seemed implausible/unfamiliar (``model_plausibility_doubt``) while
    tool execution was clean: no tool errors, no failed steps, and no unverified/failed
    material-write reviews. In that exact case the gathered content is authoritative and the
    doubt is not admissible evidence of failure.
    """
    if (
        success is False
        and failure_basis == "model_plausibility_doubt"
        and not has_tool_errors
        and not has_failed_steps
        and not outcome_review_issues
    ):
        content = "\n".join(standardized_messages or "").strip()
        if len(content) >= SUBSTANTIVE_CONTENT_MIN_CHARS:
            print("✅ FINALIZER: Overriding plausibility-doubt failure on clean, substantive tool-grounded result")
            return ContextOnlyOverrideResult(success=True, outcome="success", outcome_reason="")

    return ContextOnlyOverrideResult(
        success=success,
        outcome=outcome,
        outcome_reason=outcome_reason,
    )


def normalize_outcome_after_content(
    *,
    outcome: str,
    success: bool,
    has_tool_errors: bool,
    has_failed_steps: bool,
    content_available: bool,
    outcome_reason: str,
) -> Tuple[str, str]:
    if success:
        outcome = "success"
    elif outcome in {"success", "completed_with_warnings"}:
        outcome = "partial" if content_available else "failure"

    if outcome != "success" and not is_non_empty_string(outcome_reason):
        outcome_reason = default_outcome_reason(
            outcome,
            has_tool_errors=has_tool_errors,
            has_failed_steps=has_failed_steps,
            has_content=content_available,
        )
    return outcome, outcome_reason


def build_result_payload(
    *,
    agent_task_id: Optional[str],
    active_app: Optional[str],
    files: List[Dict[str, str]],
    steps_completed: int,
    steps_total: int,
    duration_ms: Optional[int],
    outcome: str,
    outcome_reason: str,
    technical_reason: str,
    outcome_review_issues: Optional[List[str]] = None,
    synthesis_evidence: Optional[Dict[str, Any]] = None,
    coverage_metrics: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    payload = {
        "agent_task_id": agent_task_id,
        "app_context": active_app if is_non_empty_string(active_app) else None,
        "files": files,
        "steps": {"completed": steps_completed, "total": steps_total},
        "duration_ms": duration_ms,
        "outcome": outcome,
        "outcome_reason": outcome_reason or None,
        "technical_reason": technical_reason or None,
    }
    if outcome_review_issues:
        payload["outcome_review_issues"] = outcome_review_issues
    if synthesis_evidence:
        payload["synthesis_evidence"] = synthesis_evidence
    if coverage_metrics:
        payload["coverage"] = coverage_metrics
    return payload


def build_result_envelope(
    *,
    success: bool,
    summary_text: str,
    result_payload: Dict[str, Any],
    outcome: str,
    outcome_reason: str,
    technical_reason: str,
    self_assessment: Optional[str],
    validation_issues: List[str],
    metrics: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    # Check if this is a retry attempt by looking at metrics.
    # If metrics are provided with explicit success flag, this is likely a final attempt.
    is_final_attempt = metrics is not None and success is not None

    # If validation issues exist and this isn't a final attempt, return retry signal.
    # This gives the agent a chance to fix issues, but won't block indefinitely.
    if validation_issues and not is_final_attempt:
        return {
            "success": False,
            "summary_text": summary_text,
            "result_payload": result_payload,
            "errors": validation_issues,
            "retry_hint": (
                "Provide result_payload.files with at least one item including name and full_path parsed from "
                "STEP_COMPLETE lines or ExecutionResult context. Then call finalize_agent_task_result again."
            ),
        }

    # Final result: use actual workflow success status, include any warnings.
    result = {
        "success": bool(success),
        "summary_text": summary_text,
        "result_payload": result_payload,
        "outcome": outcome,
    }
    if outcome_reason:
        result["outcome_reason"] = outcome_reason
    if technical_reason:
        result["technical_reason"] = technical_reason

    # Include agent's self-assessment if provided (shows agent reasoning).
    if self_assessment and is_non_empty_string(self_assessment):
        result["self_assessment"] = self_assessment.strip()

    # Include validation issues as warnings in final result (informational only).
    if validation_issues:
        result["warnings"] = validation_issues

    return result
