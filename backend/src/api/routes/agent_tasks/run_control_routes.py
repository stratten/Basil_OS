"""Pause, resume, and send notes to an agent run while it works."""

import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from api.services.agent_processing.lifecycle.runtime.user_interaction_timeline import (
    resolve_latest_waiting_user_interaction,
)
from api.services.agent_processing.lifecycle.runtime.workflow_coordinator import WorkflowCoordinator
from api.services.agent_processing.shared.agent_run_control import existing_run_control, note_with_references

from .session_control_routes import _get_agent_task_or_raise

logger = logging.getLogger(__name__)

router = APIRouter()

MAX_RUN_NOTE_LENGTH = 4000
MAX_REFERENCE_PATHS = 20
MAX_REFERENCE_PATH_LENGTH = 1024
RESUME_INSTRUCTION = (
    "The user paused you and has now resumed the run. Continue the task from where you left off."
)

_resuming_agent_task_ids: set[str] = set()
_background_resumes: set[asyncio.Task] = set()


def _clean_reference_paths(paths: list[str]) -> list[str]:
    cleaned: list[str] = []
    for path in paths:
        stripped = path.strip()
        if not stripped:
            continue
        if len(stripped) > MAX_REFERENCE_PATH_LENGTH or any(ord(char) < 32 for char in stripped):
            raise ValueError("Attached paths must be single-line file or folder paths.")
        if stripped not in cleaned:
            cleaned.append(stripped)
    return cleaned


class ResumeRunRequest(BaseModel):
    note: Optional[str] = Field(None, max_length=MAX_RUN_NOTE_LENGTH)
    reference_paths: list[str] = Field(default_factory=list, max_length=MAX_REFERENCE_PATHS)

    _clean_paths = field_validator("reference_paths")(_clean_reference_paths)


class RunMessageRequest(BaseModel):
    text: str = Field(..., max_length=MAX_RUN_NOTE_LENGTH)
    reference_paths: list[str] = Field(default_factory=list, max_length=MAX_REFERENCE_PATHS)

    _clean_paths = field_validator("reference_paths")(_clean_reference_paths)


class RunControlResponse(BaseModel):
    success: bool
    status: str
    message_id: Optional[str] = None


def _submission_service_or_raise(request: Request):
    submission_service = getattr(request.app.state, "agent_task_submission_service", None)
    if submission_service is None:
        raise HTTPException(status_code=503, detail="Agent task submission service not available")
    return submission_service


@router.post("/sessions/{agent_task_id}/pause", response_model=RunControlResponse, summary="Pause Run")
async def pause_session(agent_task_id: str, request: Request) -> RunControlResponse:
    _submission_service_or_raise(request)
    agent_task_record = await _get_agent_task_or_raise(agent_task_id)
    control = existing_run_control(agent_task_id)
    if agent_task_record.status != "processing" or control is None or not control.request_pause():
        raise HTTPException(status_code=409, detail="Basil can only pause a run while it is working.")
    logger.info("⏸️ Pause requested for %s", agent_task_id)
    return RunControlResponse(success=True, status="pause_requested")


@router.post("/sessions/{agent_task_id}/resume", response_model=RunControlResponse, summary="Resume Run")
async def resume_session(agent_task_id: str, request: Request, body: ResumeRunRequest) -> RunControlResponse:
    submission_service = _submission_service_or_raise(request)
    agent_task_record = await _get_agent_task_or_raise(agent_task_id)
    if agent_task_record.status != "paused":
        raise HTTPException(status_code=409, detail="Only a paused run can be resumed.")
    if agent_task_id in _resuming_agent_task_ids:
        raise HTTPException(status_code=409, detail="This run is already resuming.")
    note = note_with_references(body.note or "", body.reference_paths)
    _resuming_agent_task_ids.add(agent_task_id)
    try:
        await resolve_latest_waiting_user_interaction(
            agent_task_id,
            kinds=("pause",),
            status="resolved",
            response=note or None,
            broadcast=getattr(submission_service, "broadcast", None),
        )
        orchestrator = getattr(submission_service, "agent_task_orchestrator", None)
        coordinator = WorkflowCoordinator(
            websocket_manager=submission_service,
            agent_task_submission_service=getattr(
                orchestrator,
                "authorized_provider_delegation_submission_service",
                None,
            ),
        )
        task = asyncio.create_task(_resume_in_background(coordinator, submission_service, agent_task_id, note))
    except Exception:
        _resuming_agent_task_ids.discard(agent_task_id)
        raise
    _background_resumes.add(task)
    task.add_done_callback(_background_resumes.discard)
    logger.info("▶️ Resuming %s", agent_task_id)
    return RunControlResponse(success=True, status="resuming")


async def _resume_in_background(coordinator, submission_service, agent_task_id: str, note: str) -> None:
    user_response = RESUME_INSTRUCTION + (f"\n\nThey added: {note}" if note else "")
    try:
        await coordinator.resume_workflow(agent_task_id=agent_task_id, user_response=user_response)
    except Exception as error:
        logger.error("❌ Could not resume %s: %s", agent_task_id, error, exc_info=True)
        message = str(error) or error.__class__.__name__
        try:
            from api.dependencies import get_sqlite_knowledge_service

            await get_sqlite_knowledge_service().update_agent_task_status_if_active(
                agent_task_id=agent_task_id,
                status="failed",
                result_data={"success": False, "error": message},
            )
        except Exception:
            logger.exception("Could not record the failed resume for %s", agent_task_id)
        broadcast = getattr(submission_service, "broadcast", None)
        if broadcast is not None:
            try:
                await broadcast({
                    "event_type": "agent_task_progress",
                    "agent_task_id": agent_task_id,
                    "status": "failed",
                    "details": f"Could not resume: {message}",
                })
            except Exception:
                logger.exception("Could not announce the failed resume for %s", agent_task_id)
    finally:
        _resuming_agent_task_ids.discard(agent_task_id)


@router.post("/sessions/{agent_task_id}/message", response_model=RunControlResponse, summary="Send Note To Run")
async def send_run_message(agent_task_id: str, request: Request, body: RunMessageRequest) -> RunControlResponse:
    _submission_service_or_raise(request)
    text = body.text.strip()
    if not text:
        raise HTTPException(status_code=422, detail="Write a note before sending it.")
    await _get_agent_task_or_raise(agent_task_id)
    control = existing_run_control(agent_task_id)
    queued = control.enqueue(note_with_references(text, body.reference_paths)) if control is not None else None
    if queued is None:
        raise HTTPException(
            status_code=409,
            detail="Basil isn't at a point where it can read notes yet. Try again in a moment.",
        )
    logger.info("📝 Queued a note for %s", agent_task_id)
    return RunControlResponse(success=True, status="queued", message_id=queued.message_id)
