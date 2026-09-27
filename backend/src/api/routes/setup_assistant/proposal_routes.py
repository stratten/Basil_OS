"""Proposal approval endpoints for the setup assistant."""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request

from api.dependencies import get_model_service
from api.routes.setup_assistant.agent_routes import setup_agent_service
from api.routes.setup_assistant.models import (
    SetupActionExecutionResponse,
    SetupToolApprovalState,
)
from api.services.setup_assistant.action_execution_service import SetupAssistantActionExecutionService


router = APIRouter(prefix="/proposals", tags=["Setup Assistant"])


@router.post("/{proposal_id}/approve", response_model=SetupActionExecutionResponse)
async def approve_setup_proposal(
    proposal_id: str,
    request: Request,
) -> SetupActionExecutionResponse:
    """Approve and execute one setup proposal through the backend-owned executor."""

    proposal = setup_agent_service.get_pending_setup_proposal(proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="Setup proposal was not found.")

    approved_proposal = proposal.model_copy(
        update={"approval_state": SetupToolApprovalState.approved}
    )
    setup_agent_service.proposal_store.update_setup_proposal_state(
        proposal_id,
        SetupToolApprovalState.approved,
    )

    try:
        model_service = get_model_service()
        download_manager = getattr(request.app.state, "download_manager", None)

        async def refresh_connection_tools(connection_id: str) -> Dict[str, Any]:
            from api.routes.connections.routes import refresh_tools

            connection = await refresh_tools(connection_id, request)
            return connection.model_dump(mode="json")

        results = await SetupAssistantActionExecutionService(
            download_manager=download_manager,
            model_service=model_service,
            connection_refresher=refresh_connection_tools,
        ).execute_approved_setup_actions(actions=[], tool_calls=[approved_proposal])
        return SetupActionExecutionResponse(results=results)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/{proposal_id}/decline")
async def decline_setup_proposal(proposal_id: str) -> Dict[str, str]:
    """Decline one pending setup proposal."""

    updated = setup_agent_service.proposal_store.update_setup_proposal_state(
        proposal_id,
        SetupToolApprovalState.skipped,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="Setup proposal was not found.")
    return {"proposal_id": proposal_id, "approval_state": SetupToolApprovalState.skipped.value}


@router.post("/{proposal_id}/defer")
async def defer_setup_proposal(proposal_id: str) -> Dict[str, str]:
    """Defer one pending setup proposal."""

    updated = setup_agent_service.proposal_store.update_setup_proposal_state(
        proposal_id,
        SetupToolApprovalState.deferred,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="Setup proposal was not found.")
    return {"proposal_id": proposal_id, "approval_state": SetupToolApprovalState.deferred.value}

