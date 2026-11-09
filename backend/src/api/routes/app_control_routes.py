"""Routes the user's approval card calls to answer an agent's request to change Basil settings."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.core.models.responses import StatusResponse
from api.core.security.backend_request_guard import require_host_credential
from api.services.app_control.approval import SettingsChangeApprovalManager
from api.services.app_control.native_command_bridge import deliver_native_command_result

router = APIRouter(prefix="/app-control", tags=["app-control"])


class NativeCommandResult(BaseModel):
    request_id: str
    success: bool
    error: str | None = None


class SettingsChangeApprovalDecision(BaseModel):
    approval_id: str
    approved: bool


@router.post(
    "/settings-change/approve",
    response_model=StatusResponse,
    dependencies=[Depends(require_host_credential)],
)
async def resolve_settings_change_approval(decision: SettingsChangeApprovalDecision) -> StatusResponse:
    """Deliver the user's answer. Only the host app may call this, so an agent cannot approve its own request."""
    resolved = await SettingsChangeApprovalManager.resolve(decision.approval_id, decision.approved)
    if not resolved:
        raise HTTPException(status_code=404, detail="Approval request not found or already resolved")
    return StatusResponse(status="success", message="Settings change decision recorded")


@router.post(
    "/native-command/result",
    response_model=StatusResponse,
    dependencies=[Depends(require_host_credential)],
)
async def receive_native_command_result(result: NativeCommandResult) -> StatusResponse:
    """The Mac app reports what happened to a command. Only the host app may call this, so an agent cannot report its own success."""
    if not deliver_native_command_result(result.model_dump()):
        raise HTTPException(status_code=404, detail="Native command not found or already finished")
    return StatusResponse(status="success", message="Native command result recorded")
