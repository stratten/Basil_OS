"""Off-critical-path outcome verification for agent tasks (P2).

The user-facing answer already streams during synthesis, and the deterministic part
of the finalizer (file merge, mechanical outcome, summary composition) is cheap. The
expensive part is the LLM outcome evaluation inside ``finalize_agent_task_result``,
which only runs for cloud models. This module builds a *provisional* envelope
synchronously (no LLM eval) so the completed result can broadcast immediately, then
runs the LLM evaluation in a detached task that patches the persisted record and
broadcasts ``agent_task_outcome_update`` so the UI resolves the outcome badge in place.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from ..finalization.result_finalizer_tool import finalize_agent_task_result

logger = logging.getLogger(__name__)

# Hold references to detached verification tasks so they are not garbage-collected
# before completion (asyncio only keeps weak references to bare create_task tasks).
_PENDING_VERIFICATIONS: Set[asyncio.Task] = set()


@dataclass
class FinalizeInputs:
    """All inputs shared by the provisional and refined finalizer calls."""

    original_prompt: str
    agent_task_id: Optional[str]
    active_app: Optional[str]
    steps: List[Dict[str, Any]]
    self_assessment: Optional[str] = None
    standardized_messages: List[str] = field(default_factory=list)
    metrics: Optional[Dict[str, Any]] = None
    tool_error_history: Optional[List[Dict[str, str]]] = None
    read_file_artifacts: Optional[List[Dict[str, Any]]] = None
    evaluation_context: Optional[str] = None
    synthesis_evidence: Optional[Dict[str, Any]] = None


def mark_verification_status(envelope: Optional[Dict[str, Any]], status: str) -> None:
    """Tag the envelope's result_payload so the UI can show pending vs resolved."""
    if isinstance(envelope, dict):
        payload = envelope.get("result_payload")
        if isinstance(payload, dict):
            payload["verification_status"] = status


async def build_provisional_envelope(inputs: FinalizeInputs) -> Optional[Dict[str, Any]]:
    """Build the fast, no-LLM finalizer envelope for immediate broadcast.

    Passing ``llm_model=None`` deterministically skips ``evaluate_finalizer_with_llm``
    (same code path local models already use), so this is cheap. Returns ``None`` only
    if the finalizer itself raises (caller then falls back to legacy recovery).
    """
    try:
        envelope = await finalize_agent_task_result(
            original_prompt=inputs.original_prompt,
            agent_task_id=inputs.agent_task_id,
            active_app=inputs.active_app,
            steps=inputs.steps,
            self_assessment=inputs.self_assessment,
            standardized_messages=inputs.standardized_messages,
            metrics=inputs.metrics,
            success=None,
            llm_model=None,
            is_local_model=True,
            tool_error_history=inputs.tool_error_history,
            read_file_artifacts=inputs.read_file_artifacts,
            evaluation_context=inputs.evaluation_context,
            synthesis_evidence=inputs.synthesis_evidence,
            stream_notifier=None,
        )
    except Exception as exc:
        logger.error("Provisional finalizer call failed: %s", exc, exc_info=True)
        return None
    mark_verification_status(envelope, "pending")
    return envelope


def schedule_outcome_verification(
    *,
    inputs: FinalizeInputs,
    llm_model: Any,
    ws_manager: Any,
    agent_task_id: Optional[str],
    root_task_id: Optional[str],
    previous_task_id: Optional[str],
    cancel_event: Any,
) -> None:
    """Run the LLM outcome evaluation off the critical path and patch the result."""
    task = asyncio.create_task(
        _run_outcome_verification(
            inputs=inputs,
            llm_model=llm_model,
            ws_manager=ws_manager,
            agent_task_id=agent_task_id,
            root_task_id=root_task_id,
            previous_task_id=previous_task_id,
            cancel_event=cancel_event,
        ),
        name=f"outcome-verification-{agent_task_id or 'unknown'}",
    )
    _PENDING_VERIFICATIONS.add(task)
    task.add_done_callback(_PENDING_VERIFICATIONS.discard)


async def _run_outcome_verification(
    *,
    inputs: FinalizeInputs,
    llm_model: Any,
    ws_manager: Any,
    agent_task_id: Optional[str],
    root_task_id: Optional[str],
    previous_task_id: Optional[str],
    cancel_event: Any,
) -> None:
    if cancel_event is not None and hasattr(cancel_event, "is_set") and cancel_event.is_set():
        return
    try:
        refined = await finalize_agent_task_result(
            original_prompt=inputs.original_prompt,
            agent_task_id=inputs.agent_task_id,
            active_app=inputs.active_app,
            steps=inputs.steps,
            self_assessment=inputs.self_assessment,
            standardized_messages=inputs.standardized_messages,
            metrics=inputs.metrics,
            success=None,
            llm_model=llm_model,
            is_local_model=False,
            tool_error_history=inputs.tool_error_history,
            read_file_artifacts=inputs.read_file_artifacts,
            evaluation_context=inputs.evaluation_context,
            synthesis_evidence=inputs.synthesis_evidence,
            stream_notifier=None,
        )
    except Exception as exc:
        logger.error("Async outcome verification failed for %s: %s", agent_task_id, exc, exc_info=True)
        return

    if not isinstance(refined, dict):
        return
    if cancel_event is not None and hasattr(cancel_event, "is_set") and cancel_event.is_set():
        return

    mark_verification_status(refined, "resolved")
    await _persist_refined_outcome(agent_task_id, refined)
    await _broadcast_outcome_update(
        ws_manager=ws_manager,
        agent_task_id=agent_task_id,
        root_task_id=root_task_id,
        previous_task_id=previous_task_id,
        refined=refined,
    )


async def _persist_refined_outcome(agent_task_id: Optional[str], refined: Dict[str, Any]) -> None:
    """Merge the refined finalizer result into the stored record without clobbering
    agent_output / execution_timeline (mirrors the merge in handle_checkpoint_request)."""
    if not agent_task_id:
        return
    try:
        from api.dependencies import get_sqlite_knowledge_service

        knowledge_service = get_sqlite_knowledge_service()
        existing_data: Dict[str, Any] = {}
        try:
            existing = await knowledge_service.agent_task_service._queries.get_agent_task(agent_task_id)
            if existing and existing.result_data:
                if isinstance(existing.result_data, dict):
                    existing_data = dict(existing.result_data)
                elif isinstance(existing.result_data, str):
                    import json as _json
                    existing_data = _json.loads(existing.result_data)
        except Exception:
            existing_data = {}

        existing_data["finalizer_result"] = refined
        summary = refined.get("summary_text")
        if summary:
            existing_data["message"] = summary

        status = "completed" if refined.get("success") else "failed"
        await knowledge_service.agent_task_service.update_agent_task_status(
            agent_task_id=agent_task_id,
            status=status,
            result_data=existing_data,
        )
        if existing and summary:
            timeline = list(existing.execution_timeline or [])
            payload = refined.get("result_payload") or {}
            updated_timeline = []
            replaced_final_summary = False
            for entry in timeline:
                if not isinstance(entry, dict) or entry.get("id") != "final_summary":
                    updated_timeline.append(entry)
                    continue
                updated_timeline.append({
                    **entry,
                    "body": summary,
                    "metadata": {
                        **(entry.get("metadata") or {}),
                        "source": "finalizer",
                        "files": payload.get("files") if isinstance(payload, dict) else [],
                        "steps": payload.get("steps") if isinstance(payload, dict) else None,
                        "outcome": payload.get("outcome") if isinstance(payload, dict) else None,
                        "outcome_reason": payload.get("outcome_reason") if isinstance(payload, dict) else None,
                        "verification_status": payload.get("verification_status") if isinstance(payload, dict) else None,
                    },
                })
                replaced_final_summary = True
            if replaced_final_summary:
                await knowledge_service.agent_task_service._mutations.update_execution_timeline(
                    agent_task_id=agent_task_id,
                    timeline=updated_timeline,
                )
    except Exception as exc:
        logger.warning("Failed to persist refined outcome for %s: %s", agent_task_id, exc)


async def _broadcast_outcome_update(
    *,
    ws_manager: Any,
    agent_task_id: Optional[str],
    root_task_id: Optional[str],
    previous_task_id: Optional[str],
    refined: Dict[str, Any],
) -> None:
    """Emit a non-terminal update the frontend applies in place. Broadcast directly
    (not via WorkflowStatusNotifier) to avoid its agent_*-prefixed timeline attachment."""
    if ws_manager is None:
        return
    payload = refined.get("result_payload") or {}
    message: Dict[str, Any] = {
        "event_type": "agent_task_outcome_update",
        "success": bool(refined.get("success")),
        "result": refined.get("summary_text", ""),
        "outcome": (payload.get("outcome") if isinstance(payload, dict) else None),
        "outcome_reason": (payload.get("outcome_reason") if isinstance(payload, dict) else None),
        "result_payload": payload,
    }
    if agent_task_id:
        message["agent_task_id"] = agent_task_id
    if root_task_id:
        message["root_task_id"] = root_task_id
    if previous_task_id:
        message["previous_task_id"] = previous_task_id
    try:
        await ws_manager.broadcast(message)
    except Exception as exc:
        logger.warning("Failed to broadcast outcome update for %s: %s", agent_task_id, exc)
