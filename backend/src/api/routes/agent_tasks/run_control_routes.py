"""Pause, resume, and send notes to an agent run while it works."""

import asyncio
import json
import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from api.services.agent_processing.lifecycle.execution_graph.agent_loop_connection import RESUME_MODEL_SWITCH_KEY
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

CONNECTION_RESUME_INSTRUCTION = (
    "The run was interrupted because the network connection to the model was lost; the user did not pause it. "
    "The connection is back and the user has resumed the run. Everything above happened and is saved, so continue "
    "from where you left off without redoing completed work."
)
MODEL_SWITCH_RESUME_INSTRUCTION = (
    "The run was interrupted because the network connection to the previous model was lost, and the user chose to "
    "continue it with a different model. You are that different model, picking up the same task. The conversation "
    "above is what already happened; its tool results are real and saved. Before repeating anything with side "
    "effects (sending messages, writing or deleting files), check the current state with a tool first. Continue "
    "from where the run stopped without redoing completed work."
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
    # Only for a run paused by a lost connection: continue it with this model instead of the one it was using.
    model_id: Optional[str] = Field(None, max_length=200)

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


def _paused_for_connection_loss(agent_task_record: Any) -> bool:
    data = getattr(agent_task_record, "result_data", None)
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except ValueError:
            return False
    return isinstance(data, dict) and bool(data.get("paused_for_connection_loss"))


async def _validated_switch_model(model_id: Optional[str]) -> Optional[str]:
    """The model the user chose to continue with, or None to keep the current one. Rejects a model that is not available, before anything about the paused run changes."""
    chosen = (model_id or "").strip()
    if not chosen:
        return None
    from api.services.reasoning_model_catalog import is_reasoning_model_available

    if not await is_reasoning_model_available(chosen):
        raise HTTPException(status_code=422, detail="That model is not available to continue with.")
    return chosen


@router.post("/sessions/{agent_task_id}/resume", response_model=RunControlResponse, summary="Resume Run")
async def resume_session(agent_task_id: str, request: Request, body: ResumeRunRequest) -> RunControlResponse:
    submission_service = _submission_service_or_raise(request)
    agent_task_record = await _get_agent_task_or_raise(agent_task_id)
    if agent_task_record.status != "paused":
        raise HTTPException(status_code=409, detail="Only a paused run can be resumed.")
    if agent_task_id in _resuming_agent_task_ids:
        raise HTTPException(status_code=409, detail="This run is already resuming.")
    connection_lost = _paused_for_connection_loss(agent_task_record)
    if body.model_id and not connection_lost:
        raise HTTPException(status_code=422, detail="Only a run paused by a lost connection can continue with a different model.")
    switch_model_id = await _validated_switch_model(body.model_id)
    note = note_with_references(body.note or "", body.reference_paths)
    _resuming_agent_task_ids.add(agent_task_id)
    try:
        await resolve_latest_waiting_user_interaction(
            agent_task_id,
            kinds=("pause", "connection_lost"),
            status="resolved",
            response=(
                "\n\n".join(part for part in (f"Continued with a different model: {switch_model_id}.", note) if part)
                if switch_model_id
                else note or None
            ),
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
        task = asyncio.create_task(
            _resume_in_background(
                coordinator,
                submission_service,
                agent_task_id,
                note,
                connection_lost=connection_lost,
                switch_model_id=switch_model_id,
            )
        )
    except Exception:
        _resuming_agent_task_ids.discard(agent_task_id)
        raise
    _background_resumes.add(task)
    task.add_done_callback(_background_resumes.discard)
    logger.info("▶️ Resuming %s", agent_task_id)
    return RunControlResponse(success=True, status="resuming")


def _resume_instruction(*, connection_lost: bool, switch_model_id: Optional[str]) -> str:
    if switch_model_id:
        return MODEL_SWITCH_RESUME_INSTRUCTION
    return CONNECTION_RESUME_INSTRUCTION if connection_lost else RESUME_INSTRUCTION


async def _resume_in_background(
    coordinator,
    submission_service,
    agent_task_id: str,
    note: str,
    *,
    connection_lost: bool = False,
    switch_model_id: Optional[str] = None,
) -> None:
    instruction = _resume_instruction(connection_lost=connection_lost, switch_model_id=switch_model_id)
    user_response = instruction + (f"\n\nThey added: {note}" if note else "")
    try:
        resume_context = _resume_context(switch_model_id)
        extra = {"context": resume_context} if resume_context else {}
        await coordinator.resume_workflow(agent_task_id=agent_task_id, user_response=user_response, **extra)
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


def _resume_context(switch_model_id: Optional[str]) -> Optional[dict[str, Any]]:
    if not switch_model_id:
        return None
    return {"context": {"model_id": switch_model_id, RESUME_MODEL_SWITCH_KEY: True}}


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
