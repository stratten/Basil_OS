"""Routes for the per-task auto-approve switch.

Reading the switch is open to the task windows. Changing it needs the host credential, which only the native app holds, so an agent that can reach the local API cannot turn it on for itself. Turning it on also asks the user for a native confirmation, the same way raising the global approval mode does.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from api.core.logging.api_logger import api_logger
from api.core.security.backend_request_guard import require_host_credential
from api.core.security.execution_approval_risk import require_risk_confirmation, task_auto_approve_risk
from api.services.agent_processing.tools.safety import ExecutionApprovalService
from api.services.agent_processing.tools.safety.task_auto_approve import (
    is_task_auto_approve_enabled,
    set_task_auto_approve,
)

from .execution_approval_routes import get_approval_service

logger = logging.getLogger(__name__)
decision_logger = api_logger.getChild("command_approval")

MAX_ROOT_TASK_ID_CHARS = 200

router = APIRouter()


class TaskAutoApproveRequest(BaseModel):
    enabled: bool


class TaskAutoApproveResponse(BaseModel):
    enabled: bool
    approved_waiting: int = 0


def _clean_root_task_id(root_task_id: str) -> str:
    cleaned = root_task_id.strip()
    if not cleaned or len(cleaned) > MAX_ROOT_TASK_ID_CHARS:
        raise HTTPException(status_code=400, detail="A task id is required.")
    return cleaned


@router.get("/auto-approve/{root_task_id}", response_model=TaskAutoApproveResponse)
async def get_task_auto_approve(root_task_id: str) -> TaskAutoApproveResponse:
    return TaskAutoApproveResponse(enabled=is_task_auto_approve_enabled(_clean_root_task_id(root_task_id)))


@router.post(
    "/auto-approve/{root_task_id}",
    response_model=TaskAutoApproveResponse,
    dependencies=[Depends(require_host_credential)],
)
async def set_task_auto_approve_route(
    root_task_id: str,
    payload: TaskAutoApproveRequest,
    http_request: Request,
    approval_service: ExecutionApprovalService = Depends(get_approval_service),
) -> TaskAutoApproveResponse:
    task_id = _clean_root_task_id(root_task_id)
    already_enabled = is_task_auto_approve_enabled(task_id)
    if payload.enabled and not already_enabled:
        require_risk_confirmation(http_request, task_auto_approve_risk())
    if not set_task_auto_approve(task_id, payload.enabled):
        raise HTTPException(status_code=400, detail="A task id is required.")
    decision_logger.info("Auto-approve %s for task %s", "turned on" if payload.enabled else "turned off", task_id)
    approved_waiting = 0
    if payload.enabled and not already_enabled:
        # The user most likely turned it on because a card was holding the task up, so the cards already waiting are approved too.
        approved_waiting = await approval_service.approve_waiting_for_task(task_id)
    return TaskAutoApproveResponse(enabled=payload.enabled, approved_waiting=approved_waiting)
