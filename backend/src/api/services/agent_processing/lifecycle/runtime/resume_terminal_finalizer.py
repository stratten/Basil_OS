"""Terminal finalization for genuinely-completed checkpoint-resumed workflows.

The initial run rail (``AgentTaskProcessingService.perform_processing`` ->
``AgentTaskWorkflowResultService.execute_multi_step_workflow``) always performs the
post-graph terminal handling: it broadcasts the ``agent_task_result`` event and
persists the terminal status/result_data. The checkpoint-resume rail
(``WorkflowCheckpointWorkflowService.resume_workflow``) runs the same LangGraph app
but historically dropped that terminal handling, leaving completed resumed runs
frozen at ``awaiting_user_input`` in the DB and stuck "working" in the UI.

This module converges the resume rail onto the initial rail's shared terminal
handling (``finalize_workflow_output`` + ``commit_terminal_outcome``) so a resumed
run that reaches genuine completion is persisted and broadcast identically. It is
invoked only from the resume success path, after the graph has produced a final
state and did not raise another checkpoint request.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


async def finalize_resumed_workflow(
    agent_task_id: str,
    final_state: Optional[Dict[str, Any]],
    websocket_manager: Any,
) -> None:
    """Persist and broadcast the terminal outcome of a genuinely-completed resumed run.

    Loads the authoritative agent-task record, reshapes ``final_state`` into the dict
    that ``build_workflow_result_data`` consumes on the initial rail, then runs the
    shared ``finalize_workflow_output`` (normalize + single broadcast) and
    ``commit_terminal_outcome`` (persist completed/failed + result message).

    Absent a ``final_envelope`` the shared derivation yields ``success == False``, so
    the run is persisted ``failed`` rather than falsely ``completed`` -- mirroring the
    initial rail's missing-finalizer handling.
    """
    if not final_state:
        logger.info("↩️ finalize_resumed_workflow: no final_state; nothing to finalize for %s", agent_task_id)
        return

    from api.dependencies import get_sqlite_knowledge_service
    from ..submission.agent_task_processing.agent_task_workflow_result_service import (
        AgentTaskWorkflowResultService,
    )

    ks = get_sqlite_knowledge_service()
    agent_task_record = await ks.get_agent_task(agent_task_id)
    if not agent_task_record:
        logger.warning("⚠️ finalize_resumed_workflow: agent task %s not found; skipping finalization", agent_task_id)
        return
    if getattr(agent_task_record, "status", None) == "canceled":
        logger.info(
            "↩️ finalize_resumed_workflow: agent task %s was canceled; skipping terminal finalization",
            agent_task_id,
        )
        return

    tool_results = final_state.get("tool_execution_results", []) or []
    todos_completed = len([r for r in tool_results if isinstance(r, dict) and r.get("success", False)])
    todos_failed = len([r for r in tool_results if not (isinstance(r, dict) and r.get("success", True))])
    overall_success = todos_completed > 0 or todos_failed == 0

    final_envelope = final_state.get("final_envelope")
    summary_text = ""
    if isinstance(final_envelope, dict):
        summary_text = final_envelope.get("summary_text", "")

    curated_result: Dict[str, Any] = {
        "tool_execution_results": tool_results,
        "final_envelope": final_envelope,
        "overall_success": overall_success,
        "todos_completed": todos_completed,
        "total_todos": len(tool_results),
        "workflow_result": summary_text,
    }

    request = SimpleNamespace(
        agent_task=agent_task_record.original_prompt or agent_task_record.transcribed_prompt or "",
        agent_task_id=agent_task_id,
        root_task_id=agent_task_record.root_task_id,
        previous_task_id=agent_task_record.previous_task_id,
    )

    wrs = AgentTaskWorkflowResultService(db_service=ks, websocket_manager=websocket_manager)
    operation_result = await wrs.finalize_workflow_output(curated_result, request)
    await wrs.commit_terminal_outcome(
        agent_task_id=agent_task_id,
        agent_task_record=agent_task_record,
        operation="multi_step_workflow",
        operation_result=operation_result,
    )
    logger.info(
        "✅ finalize_resumed_workflow: committed terminal outcome for %s (success=%s)",
        agent_task_id,
        getattr(operation_result, "success", None),
    )


__all__ = ["finalize_resumed_workflow"]
