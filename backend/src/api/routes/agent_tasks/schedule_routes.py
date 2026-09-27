"""Scheduled agent task route modules."""

import logging
from typing import List

from fastapi import APIRouter, HTTPException, Query

from api.dependencies import get_sqlite_knowledge_service
from api.services.scheduled_agent_tasks.scheduled_agent_task_service import ScheduledAgentTaskService

from .models import (
    DeleteAgentTaskResponse,
    ScheduleInterpretationRequest,
    ScheduleInterpretationResponse,
    ScheduledActiveRunItem,
    ScheduledAgentTaskCreateRequest,
    ScheduledAgentTaskItem,
    ScheduledAgentTaskListResponse,
    ScheduledAgentTaskRunItem,
    ScheduledAgentTaskRunNowResponse,
    ScheduledAgentTaskUpdateRequest,
)

logger = logging.getLogger(__name__)

schedule_router = APIRouter(prefix="/api/v1/agent-task-schedules", tags=["Agent Task Schedules"])
run_router = APIRouter(prefix="/api/v1/agent-task-runs", tags=["Agent Task Runs"])


@schedule_router.get("", response_model=ScheduledAgentTaskListResponse, summary="List Scheduled Agent Tasks")
async def list_scheduled_agent_tasks(
    include_inactive: bool = Query(True, description="Include inactive scheduled agent tasks"),
) -> ScheduledAgentTaskListResponse:
    """List scheduled agent task jobs shown in scheduled-sidebar mode."""
    try:
        service = ScheduledAgentTaskService()
        agent_tasks = await service.list_scheduled_agent_tasks(include_inactive=include_inactive)
        return ScheduledAgentTaskListResponse(agent_tasks=[ScheduledAgentTaskItem(**item) for item in agent_tasks])
    except Exception as e:
        logger.error(f"Error listing scheduled agent tasks: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error listing scheduled agent tasks: {str(e)}")


@schedule_router.get("/{scheduled_agent_task_id}", response_model=ScheduledAgentTaskItem, summary="Get Scheduled Agent Task")
async def get_scheduled_agent_task(
    scheduled_agent_task_id: str,
) -> ScheduledAgentTaskItem:
    try:
        service = ScheduledAgentTaskService()
        scheduled_agent_task = await service.get_scheduled_agent_task(scheduled_agent_task_id)
        if not scheduled_agent_task:
            raise HTTPException(status_code=404, detail=f"Scheduled agent task {scheduled_agent_task_id} not found")
        return ScheduledAgentTaskItem(**scheduled_agent_task)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting scheduled agent task {scheduled_agent_task_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error getting scheduled agent task: {str(e)}")


@schedule_router.post("", response_model=ScheduledAgentTaskItem, summary="Create Scheduled Agent Task")
async def create_scheduled_agent_task(
    payload: ScheduledAgentTaskCreateRequest,
) -> ScheduledAgentTaskItem:
    try:
        if not payload.agent_task_text.strip():
            raise HTTPException(status_code=400, detail="agent_task_text cannot be empty")
        if not payload.title.strip():
            raise HTTPException(status_code=400, detail="title cannot be empty")

        service = ScheduledAgentTaskService()
        created = await service.create_scheduled_agent_task(
            title=payload.title.strip(),
            agent_task_text=payload.agent_task_text.strip(),
            schedule_type=payload.schedule_type,
            schedule_config=payload.schedule_config,
            timezone_name=payload.timezone,
            source_type=payload.source_type,
            is_active=payload.is_active,
            reference_paths=payload.reference_paths,
        )
        return ScheduledAgentTaskItem(**created)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating scheduled agent task: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error creating scheduled agent task: {str(e)}")


@schedule_router.patch("/{scheduled_agent_task_id}", response_model=ScheduledAgentTaskItem, summary="Update Scheduled Agent Task")
async def update_scheduled_agent_task(
    scheduled_agent_task_id: str,
    payload: ScheduledAgentTaskUpdateRequest,
) -> ScheduledAgentTaskItem:
    try:
        service = ScheduledAgentTaskService()
        updates = payload.model_dump(exclude_none=True)
        updated = await service.update_scheduled_agent_task(scheduled_agent_task_id, updates)
        if not updated:
            raise HTTPException(status_code=404, detail=f"Scheduled agent task {scheduled_agent_task_id} not found")
        return ScheduledAgentTaskItem(**updated)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating scheduled agent task {scheduled_agent_task_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error updating scheduled agent task: {str(e)}")


@schedule_router.delete("/{scheduled_agent_task_id}", response_model=DeleteAgentTaskResponse, summary="Delete Scheduled Agent Task")
async def delete_scheduled_agent_task(
    scheduled_agent_task_id: str,
) -> DeleteAgentTaskResponse:
    try:
        service = ScheduledAgentTaskService()
        deleted = await service.delete_scheduled_agent_task(scheduled_agent_task_id)
        if not deleted:
            raise HTTPException(status_code=404, detail=f"Scheduled agent task {scheduled_agent_task_id} not found")
        return DeleteAgentTaskResponse(success=True, message="Scheduled agent task deleted successfully")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting scheduled agent task {scheduled_agent_task_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error deleting scheduled agent task: {str(e)}")


@run_router.get(
    "/active",
    response_model=List[ScheduledActiveRunItem],
    summary="List currently in-flight scheduled agent task runs",
)
async def list_active_scheduled_runs() -> List[ScheduledActiveRunItem]:
    """Return every scheduled-agent-task run currently in ``running`` status.

    Powers cold-open hydration of the floating mini panel: the panel may
    attach (re-render, app re-launch, dismiss-and-reopen) after a run has
    already started broadcasting, so it asks "what is already running right
    now?" on mount and seeds its in-memory rows from the answer.
    """
    try:
        sqlite_service = get_sqlite_knowledge_service()
        rows = await sqlite_service.scheduled_agent_task_repository.list_active_runs()
        return [ScheduledActiveRunItem(**row) for row in rows]
    except Exception as e:
        logger.error(f"Error listing active scheduled runs: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error listing active scheduled runs: {str(e)}")


@schedule_router.get("/{scheduled_agent_task_id}/runs", response_model=List[ScheduledAgentTaskRunItem], summary="List Scheduled Agent Task Runs")
async def list_scheduled_agent_task_runs(
    scheduled_agent_task_id: str,
    limit: int = Query(100, ge=1, le=500),
) -> List[ScheduledAgentTaskRunItem]:
    try:
        service = ScheduledAgentTaskService()
        runs = await service.list_runs_for_agent_task(scheduled_agent_task_id, limit=limit)
        return [ScheduledAgentTaskRunItem(**run) for run in runs]
    except Exception as e:
        logger.error(f"Error listing runs for scheduled agent task {scheduled_agent_task_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error listing scheduled runs: {str(e)}")


@schedule_router.post("/{scheduled_agent_task_id}/run-now", response_model=ScheduledAgentTaskRunNowResponse, summary="Run Scheduled Agent Task Now")
async def run_scheduled_agent_task_now(
    scheduled_agent_task_id: str,
) -> ScheduledAgentTaskRunNowResponse:
    try:
        service = ScheduledAgentTaskService()
        run_id = await service.run_scheduled_agent_task_now(scheduled_agent_task_id)
        return ScheduledAgentTaskRunNowResponse(success=True, run_id=run_id)
    except Exception as e:
        logger.error(f"Error running scheduled agent task immediately {scheduled_agent_task_id}: {e}", exc_info=True)
        return ScheduledAgentTaskRunNowResponse(success=False, error=str(e))


@schedule_router.post("/interpret", response_model=ScheduleInterpretationResponse, summary="Interpret Scheduled Agent Task Prompt")
async def interpret_scheduled_agent_task_prompt(
    payload: ScheduleInterpretationRequest,
) -> ScheduleInterpretationResponse:
    """
    LLM-driven interpretation of a natural-language scheduled-agent-task request.
    Returns a pre-filled create payload the client can review/edit before saving,
    or a structured clarification question when the request is genuinely ambiguous.
    """
    try:
        service = ScheduledAgentTaskService()
        interpreted = await service.interpret_schedule_prompt(
            payload.prompt,
            context_id=payload.context_id,
            user_timezone=payload.user_timezone,
        )
        return ScheduleInterpretationResponse(
            success=True,
            title=interpreted["title"],
            agent_task_text=interpreted["agent_task_text"],
            schedule_type=interpreted["schedule_type"],
            schedule_config=interpreted["schedule_config"],
            timezone=interpreted["timezone"],
            source_type="smart",
            is_active=True,
            needs_user_confirmation=False,
            clarification_question=None,
            context_id=payload.context_id,
        )
    except ValueError as e:
        message = str(e)
        if message.startswith("Need clarification"):
            # Message format expected:
            # "Need clarification (context_id=<id>): <question>"
            context_id = payload.context_id
            clarification_question = "Please clarify your scheduling request."

            marker = "(context_id="
            marker_index = message.find(marker)
            if marker_index >= 0:
                after_marker = message[marker_index + len(marker):]
                end_idx = after_marker.find(")")
                if end_idx >= 0:
                    extracted_id = after_marker[:end_idx].strip()
                    if extracted_id:
                        context_id = extracted_id
            colon_idx = message.find(":")
            if colon_idx >= 0 and colon_idx + 1 < len(message):
                question = message[colon_idx + 1:].strip()
                if question:
                    clarification_question = question

            return ScheduleInterpretationResponse(
                success=False,
                source_type="smart",
                is_active=True,
                needs_user_confirmation=True,
                clarification_question=clarification_question,
                context_id=context_id,
                error=None,
            )
        logger.error(f"Validation error interpreting schedule prompt: {e}", exc_info=True)
        return ScheduleInterpretationResponse(
            success=False,
            source_type="smart",
            is_active=True,
            needs_user_confirmation=False,
            clarification_question=None,
            context_id=payload.context_id,
            error=f"Could not interpret schedule prompt: {message}",
        )
    except Exception as e:
        logger.error(f"Error interpreting schedule prompt: {e}", exc_info=True)
        return ScheduleInterpretationResponse(
            success=False,
            source_type="smart",
            is_active=True,
            needs_user_confirmation=False,
            clarification_question=None,
            context_id=payload.context_id,
            error=f"Could not interpret schedule prompt: {str(e)}",
        )
