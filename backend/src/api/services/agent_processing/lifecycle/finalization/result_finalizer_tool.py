"""
Result Finalizer Tool

Purpose
  Reasoning-first finalizer that classifies the user-facing outcome, assembles
  summary_text, and returns a structured result_payload from execution context.
  This is intended to be the LAST tool or function invoked in any agentic
  agent_task flow.

Design rules
  - NO brittle string parsing from tool reprs or script bodies
  - Prefer structured fields from step results; optionally accept normalized
    standardized_messages (e.g., STEP_COMPLETE) when present
  - Preserve file paths verbatim (HFS or POSIX); derive filename via basename only
  - Produce a single JSON-like dict with fixed keys; the frontend should consume
    result_payload fields directly (no text parsing)

Inputs (all plain Python types; caller validates)
  - original_prompt: str
  - agent_task_id: Optional[str]
  - active_app: Optional[str]
  - steps: List[Dict[str, Any]] where each step contains, at minimum:
      {
        "service": str,
        "method": str,
        "success": bool,
        "duration_ms": Optional[int],
        "result": Optional[Dict[str, Any]]  # service return payload (structured if available)
      }
  - standardized_messages: Optional[List[str]]
  - metrics: Optional[Dict[str, Any]] with {steps_completed:int, steps_total:int, duration_ms:int}
  - success: Optional[bool]  # mechanical fallback only; reasoning evaluator wins

Outputs
  A dict with this exact shape (keys always present):
    {
      "success": bool,
      "summary_text": str,
      "result_payload": {
        "agent_task_id": Optional[str],
        "app_context": Optional[str],
        "files": [ {"name": str, "full_path": str, "operation": Optional[str]} ],
        "steps": {"completed": int, "total": int},
        "duration_ms": Optional[int],
        "outcome": "success" | "partial" | "failure",
        "outcome_reason": Optional[str],
        "technical_reason": Optional[str]
      }
    }

Note
  This module deliberately avoids type frameworks and external dependencies. It is
  meant to be model-friendly: the LLM can be instructed to produce an object with
  exactly these keys (no prose) when invoked via a tool adapter.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from api.services.agent_processing.shared.material_outcome_brief import (
    build_material_outcome_brief,
    summarize_material_effects,
)

from ..execution_graph.context_window_budget import context_window_exceeded_reason
from .evaluation import (
    default_outcome_reason as _default_outcome_reason,
    evaluate_finalizer_with_llm,
    has_failed_steps as _has_failed_steps,
)
from .summary_payload import (
    apply_context_only_followup_override,
    apply_plausibility_doubt_override,
    build_result_envelope,
    build_result_payload,
    collect_outcome_review_issues,
    collect_validation_issues,
    compose_summary,
    derive_step_metrics,
    merge_file_results,
    merge_read_file_artifacts,
    normalize_outcome_after_content,
    recover_standardized_messages_from_database,
)


async def finalize_agent_task_result(
    original_prompt: str,
    agent_task_id: Optional[str],
    active_app: Optional[str],
    steps: List[Dict[str, Any]],
    self_assessment: Optional[str] = None,
    standardized_messages: Optional[List[str]] = None,
    metrics: Optional[Dict[str, Any]] = None,
    success: Optional[bool] = None,
    llm_model: Optional[Any] = None,
    is_local_model: bool = False,
    tool_error_history: Optional[List[Dict[str, str]]] = None,
    evaluation_context: Optional[str] = None,
    synthesis_evidence: Optional[Dict[str, Any]] = None,
    read_file_artifacts: Optional[List[Dict[str, Any]]] = None,
    stream_notifier: Optional[Any] = None,
    context_window_exceeded: Optional[Dict[str, Any]] = None,
    agent_final_answer: Optional[str] = None,
    evaluator_timeout_seconds: Optional[float] = None,
    on_verifier_reasoning: Optional[Any] = None,
) -> Dict[str, Any]:
    """Assemble summary_text and structured payload from execution context.
    
    This is the FINAL CHECKPOINT for agent execution. The agent must reflect on
    whether its results fully match the user's original intent before calling this.

    This function is intentionally strict and data-driven. It never reads free-form
    script bodies or tool reprs, and only accepts:
      - Structured step result fields; and/or
      - Normalized standardized_messages

    Args:
        original_prompt: The user's original request
        agent_task_id: Unique AgentTask identifier
        active_app: Application context at time of request
        steps: List of execution step results
        self_assessment: Agent's reflection on whether results match user intent
        standardized_messages: Normalized STEP_COMPLETE messages
        metrics: Execution metrics (steps_completed, steps_total, duration_ms)
        success: Overall success status
        evaluation_context: Backend-provided follow-up/retry context for evaluation

    Returns a dict matching the contract in the module docstring.
    """
    # INTELLIGENT SUCCESS DETERMINATION USING LLM
    # The finalizer is called by the agent as its last tool call (during execution).
    # It works entirely with what the agent passes it directly - no database queries needed.
    
    # Use the agent's output directly from what was passed as parameters
    # The agent is required by system prompt to pass complete output in raw_messages/standardized_messages
    full_agent_output = chr(10).join(standardized_messages) if standardized_messages else "(No output available)"
    
    print(f"🔍 FINALIZER: Working with {len(full_agent_output)} chars of agent output from parameters")
    
    # Every model verifies the delivered response. Local models get a shorter
    # deadline and stream their reasoning to the UI so the pass is never silent.
    mechanical_success_hint = success
    success = None
    outcome = "success"
    outcome_reason = ""
    technical_reason = ""
    llm_reasoning = ""
    should_retry = False
    failure_basis = ""
    has_tool_errors = bool(tool_error_history)
    has_failed_steps = _has_failed_steps(steps)
    material_outcome_brief = build_material_outcome_brief(steps)
    material_effect_summary = summarize_material_effects(steps)
    evaluator_ran = False
    if llm_model is not None and full_agent_output:
        from ..runtime.user_interaction_timeline import user_run_notes_context

        run_notes = await user_run_notes_context(agent_task_id)
        if run_notes:
            evaluation_context = f"{run_notes}\n\n{evaluation_context}" if evaluation_context else run_notes
        evaluation = await evaluate_finalizer_with_llm(
            llm_model=llm_model,
            original_prompt=original_prompt,
            self_assessment=self_assessment,
            full_agent_output=full_agent_output,
            steps=steps,
            tool_error_history=tool_error_history,
            evaluation_context=evaluation_context,
            material_outcome_brief=material_outcome_brief,
            agent_final_answer=agent_final_answer,
            timeout_seconds=evaluator_timeout_seconds,
            on_reasoning=on_verifier_reasoning,
        )
        if evaluation is not None:
            evaluator_ran = True
            outcome = evaluation.outcome
            success = evaluation.success
            outcome_reason = evaluation.outcome_reason
            technical_reason = evaluation.technical_reason
            llm_reasoning = evaluation.llm_reasoning
            should_retry = evaluation.should_retry
            failure_basis = evaluation.failure_basis
            if (
                evaluation.coverage_status == "incomplete"
                or evaluation.truncation_prevents_verification
            ):
                success = False
                outcome = "partial"
                outcome_reason = evaluation.outcome_reason or "The final response coverage is incomplete."
                technical_reason = evaluation.technical_reason or "Evaluator reported incomplete coverage."
    
    # Fallback: mechanical check if LLM evaluation wasn't used or failed
    if success is None:
        if isinstance(mechanical_success_hint, bool):
            success = mechanical_success_hint
        # Check if all steps are successful (either explicit success field or status="completed"/"success")
        elif steps:
            success = all(
                step.get("success") is True or 
                step.get("status") in ("completed", "success")
                for step in steps
            )
        else:
            success = True

        content_for_fallback = "\n".join(standardized_messages or "").strip()
        if success:
            outcome = "success"
        else:
            outcome = "partial" if content_for_fallback else "failure"
        outcome_reason = _default_outcome_reason(
            outcome,
            has_tool_errors=has_tool_errors,
            has_failed_steps=has_failed_steps,
            has_content=bool(content_for_fallback),
        )
        if not technical_reason and (has_tool_errors or has_failed_steps):
            technical_reason = "Mechanical fallback observed failed tool attempts before finalization."

    standardized_messages = await recover_standardized_messages_from_database(
        agent_task_id,
        standardized_messages,
    )

    step_metrics = derive_step_metrics(metrics, steps)
    steps_completed = step_metrics.completed
    steps_total = step_metrics.total
    duration_ms = step_metrics.duration_ms

    files = merge_file_results(steps)
    files = merge_read_file_artifacts(files, read_file_artifacts)

    validation_issues = collect_validation_issues(
        files=files,
    )
    outcome_review_issues = collect_outcome_review_issues(steps)

    synthesis_terminal = (synthesis_evidence or {}).get("terminal") if isinstance(synthesis_evidence, dict) else {}
    synthesis_truncated = bool(
        isinstance(synthesis_terminal, dict)
        and (
            synthesis_terminal.get("truncated")
            or synthesis_terminal.get("reason") in {"max_tokens", "length", "error", "safety", "unknown"}
        )
    )
    if synthesis_truncated:
        success = False
        outcome = "partial" if "\n".join(standardized_messages or "").strip() else "failure"
        reason = synthesis_terminal.get("reason") if isinstance(synthesis_terminal, dict) else "unknown"
        outcome_reason = (
            "The final response did not complete cleanly; Basil preserved the partial output "
            f"and marked the result incomplete (terminal reason: {reason})."
        )
        technical_reason = "Final synthesis terminal metadata prevented clean success."

    synthesis_truncation_list = (
        (synthesis_evidence or {}).get("truncation_evidence")
        if isinstance(synthesis_evidence, dict)
        else None
    )
    synthesis_coverage_truncated = bool(
        isinstance(synthesis_truncation_list, list)
        and any(
            isinstance(item, dict) and item.get("affects_coverage")
            for item in synthesis_truncation_list
        )
    )
    if synthesis_coverage_truncated and not evaluator_ran and success:
        success = False
        outcome = "partial" if "\n".join(standardized_messages or "").strip() else "failure"
        outcome_reason = (
            "The tool trace given to the final response writer was truncated to fit its "
            "input budget, so some tool results may not be reflected; Basil marked the "
            "result incomplete rather than reporting an unverified success."
        )
        technical_reason = (
            "Synthesis input truncation evidence marked tool-trace coverage as affected, "
            "and no evaluator ran to independently confirm coverage was still sufficient."
        )

    content_text = "\n".join(standardized_messages or "")
    if material_effect_summary.has_failed_effects and success and not evaluator_ran:
        success = False
        outcome = "partial" if content_text.strip() else "failure"
        outcome_reason = (
            "A requested change did not complete successfully, so the result may "
            "not fully reflect the requested outcome."
        )
        technical_reason = (
            "Material receipt evidence includes a failed requested change that "
            "the evaluator did not treat as a failure."
            if evaluator_ran
            else "No subjective evaluator ran and material receipt evidence includes "
            "a failed requested change."
        )
    elif not evaluator_ran and material_effect_summary.has_unresolved and success:
        success = False
        outcome = "partial"
        outcome_reason = (
            "The requested change could not be independently confirmed; the "
            "response distinguishes confirmed outcomes from attempted ones."
        )
        technical_reason = (
            "No subjective evaluator ran and material receipt evidence includes "
            "an unverified requested change."
        )
    elif (
        evaluator_ran
        and outcome == "partial"
        and not success
        and material_effect_summary.has_material_writes
        and not material_effect_summary.has_unresolved
        and failure_basis in {"", "none"}
    ):
        # The evaluator classified this "partial" from prose alone (for example an
        # agent-generated advisory about a secondary concern) while every tracked
        # requested change has independent receipt evidence of verification. Model
        # prose alone is not sufficient grounds to keep a verified effect partial;
        # only an unfulfilled requested effect, a failed verification, or an
        # unavailable required artifact may do that, and none is present here.
        success = True
        outcome = "success"
        outcome_reason = ""
        technical_reason = (
            "Material receipt evidence verified every tracked requested change; "
            "the evaluator's partial claim had no structured evidence of an "
            "unfulfilled effect, a failed verification, or an unavailable artifact."
        )

    requested_count, delivered_count = _detect_explicit_numbered_coverage(
        original_prompt,
        content_text,
    )
    coverage_metrics = None
    if requested_count is not None:
        coverage_metrics = {
            "requested_item_count": requested_count,
            "delivered_item_count": delivered_count,
            "coverage_status": "complete" if delivered_count >= requested_count else "incomplete",
        }
        if delivered_count < requested_count:
            success = False
            outcome = "partial" if content_text.strip() else "failure"
            outcome_reason = (
                f"The final response includes {delivered_count} of {requested_count} requested numbered items."
            )
            technical_reason = "Explicit numbered deliverable coverage was incomplete."

    doubt_override = apply_plausibility_doubt_override(
        success=success,
        outcome=outcome,
        outcome_reason=outcome_reason,
        failure_basis=failure_basis,
        has_tool_errors=has_tool_errors,
        has_failed_steps=has_failed_steps,
        outcome_review_issues=outcome_review_issues,
        standardized_messages=standardized_messages,
    )
    success = doubt_override.success
    outcome = doubt_override.outcome
    outcome_reason = doubt_override.outcome_reason

    override_result = apply_context_only_followup_override(
        success=success,
        outcome=outcome,
        outcome_reason=outcome_reason,
        should_retry=should_retry,
        steps_total=steps_total,
        steps_completed=steps_completed,
        failure_basis=failure_basis,
        standardized_messages=standardized_messages,
        tool_error_history=tool_error_history,
        validation_issues=validation_issues,
    )
    success = override_result.success
    outcome = override_result.outcome
    outcome_reason = override_result.outcome_reason

    content_available = bool("\n".join(standardized_messages or "").strip())
    if isinstance(context_window_exceeded, dict):
        success = False
        outcome = "partial" if content_available else "failure"
        outcome_reason = context_window_exceeded_reason(context_window_exceeded)
        technical_reason = (
            "The agent loop stopped on a context-window overflow after "
            f"{context_window_exceeded.get('compaction_attempts', 0)} compaction level(s)."
        )
    outcome, outcome_reason = normalize_outcome_after_content(
        outcome=outcome,
        success=success,
        has_tool_errors=has_tool_errors,
        has_failed_steps=has_failed_steps,
        content_available=content_available,
        outcome_reason=outcome_reason,
    )

    # Compose deterministic summary (even for failure we provide a textual summary)
    summary_text = compose_summary(
        success,
        active_app,
        files,
        steps_completed,
        steps_total,
        standardized_messages,
        outcome=outcome,
        outcome_reason=outcome_reason,
    )

    # User-visible text streaming is owned by the backend final-synthesis phase; the
    # finalizer no longer re-chunks summary_text for WebSocket (stream_notifier is
    # typically None on the direct path). Legacy in-tool finalization may still pass
    # a notifier for rare paths.

    # Output envelope (strict keys only)
    result_payload = build_result_payload(
        agent_task_id=agent_task_id,
        active_app=active_app,
        files=files,
        steps_completed=steps_completed,
        steps_total=steps_total,
        duration_ms=duration_ms,
        outcome=outcome,
        outcome_reason=outcome_reason,
        technical_reason=technical_reason,
        outcome_review_issues=outcome_review_issues,
        synthesis_evidence=synthesis_evidence,
        coverage_metrics=coverage_metrics,
    )

    return build_result_envelope(
        success=success,
        summary_text=summary_text,
        result_payload=result_payload,
        outcome=outcome,
        outcome_reason=outcome_reason,
        technical_reason=technical_reason,
        self_assessment=self_assessment,
        validation_issues=validation_issues,
        metrics=metrics,
    )


def _detect_explicit_numbered_coverage(
    original_prompt: str,
    content_text: str,
) -> tuple[Optional[int], int]:
    """Detect simple explicit numeric deliverable coverage in markdown output."""
    prompt = original_prompt or ""
    number_match = re.search(
        r"\b(?:all\s+)?(\d{1,3})\s+(?:personalized\s+)?(?:emails?|items?|drafts?|sections?|deliverables?)\b",
        prompt,
        flags=re.IGNORECASE,
    )
    if not number_match:
        return None, 0
    requested = int(number_match.group(1))
    headings = re.findall(r"(?m)^\s*#{1,6}\s+(\d{1,3})\.\s+", content_text or "")
    if not headings:
        headings = re.findall(r"(?m)^\s*(\d{1,3})\.\s+", content_text or "")
    delivered_numbers = {int(value) for value in headings if value.isdigit()}
    delivered = len([value for value in delivered_numbers if 1 <= value <= requested])
    return requested, delivered


# Optional adapter: simple callable signature for LangChain tool wrappers
async def tool_entry(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Adapter that unpacks a single payload dict.
    Expected keys: original_prompt, agent_task_id, active_app, steps,
                   self_assessment (optional), standardized_messages (optional), 
                   metrics (optional), success (optional), llm_model (optional),
                   is_local_model (optional).
    
    The finalizer queries the database using agent_task_id to get complete context.
    """
    return await finalize_agent_task_result(
        original_prompt=payload.get("original_prompt", ""),
        agent_task_id=payload.get("agent_task_id"),
        active_app=payload.get("active_app"),
        steps=payload.get("steps") or [],
        self_assessment=payload.get("self_assessment"),
        standardized_messages=payload.get("standardized_messages") or [],
        metrics=payload.get("metrics"),
        success=payload.get("success"),
        llm_model=payload.get("llm_model"),
        is_local_model=payload.get("is_local_model", False),
        tool_error_history=payload.get("tool_error_history"),
        evaluation_context=payload.get("evaluation_context"),
        read_file_artifacts=payload.get("read_file_artifacts"),
        stream_notifier=payload.get("stream_notifier"),
    )


