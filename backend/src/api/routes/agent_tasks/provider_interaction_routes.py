"""Deliver a durable provider user-input interaction's answer to its live provider run (Package 4A).

This is a dedicated route, not an extension of `/sessions/{agent_task_id}/continue`,
because that route is hard-wired to `WorkflowCoordinator.resume_workflow` and
must retain its unchanged internal workflow-checkpoint behavior.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Literal, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from api.dependencies import get_agent_task_submission_service

from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.providers.interaction_repository import (
    ProviderInteractionConflictError,
)
from api.services.agent_providers.interaction_delivery import (
    ProviderInteractionDeliveryRegistry,
)
from api.services.agent_processing.lifecycle.submission.agent_task_processing.provider_interaction_coordinator import (
    validate_submitted_values,
)
from api.services.agent_processing.tools.safety.interactive_approval import (
    InteractiveApprovalManager,
)

from .execution_models import (
    PendingExecutionApprovalModel,
    PendingExecutionApprovalResponseModel,
    RecoverExecutionApprovalsRequest,
    RecoverExecutionApprovalsResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter()

_TERMINAL_AGENT_TASK_STATUSES = {"completed", "failed", "cancelled"}
_SUPPORTED_OUTCOMES = {"accept", "decline", "cancel"}
_DELEGATED_RUN_BLOCKED_STATUSES = frozenset({"settled", "failed", "cancelled", "cancelling"})


async def _notify_delegated_agent_interaction_resolved(
    *,
    knowledge_service: Any,
    delegated_agent_controller: Any | None,
    agent_task_id: str,
    interaction_id: str,
) -> None:
    delegated_agent_repository = getattr(
        knowledge_service, "delegated_agent_repository", None
    )
    if delegated_agent_repository is None:
        return
    run = await delegated_agent_repository.get_run_for_child(agent_task_id)
    if run is None:
        return
    if run["status"] in _DELEGATED_RUN_BLOCKED_STATUSES:
        raise HTTPException(
            status_code=409,
            detail=(
                f"delegated agent run for {agent_task_id!r} is {run['status']!r} "
                "and cannot accept interaction resolution"
            ),
        )
    if delegated_agent_controller is None:
        return
    refreshed = await delegated_agent_repository.get_run_for_child(agent_task_id)
    if refreshed is None:
        return
    await delegated_agent_controller.handle_provider_interaction_resolved(
        delegated_agent_run=refreshed,
        interaction_id=interaction_id,
    )


class ProviderInteractionResponseRequest(BaseModel):
    """A user's answer to one durable provider user-input interaction."""

    outcome: str = Field(description="One of 'accept', 'decline', 'cancel'")
    values: Optional[Dict[str, str]] = None


class ProviderInteractionResponseModel(BaseModel):
    """Response after delivering a provider interaction answer."""

    success: bool
    message: str


class ProviderPermissionDecisionRequest(BaseModel):
    """A user's decision for one durable `provider_permission` interaction."""

    outcome: Literal["selected", "cancel"] = Field(
        default="selected",
        description="Whether the user selected an offered option or cancelled the prompt",
    )
    selected_option_id: Optional[str] = Field(
        default=None,
        description="The offered optionId selected by the user when outcome is 'selected'",
    )


class ProviderPermissionDecisionResponseModel(BaseModel):
    """Response after delivering a provider permission decision."""

    success: bool
    message: str


class PendingProviderInteractionModel(BaseModel):
    """The safe rendering contract for one live provider user-input interaction."""

    id: str
    message: str
    fields: list[Dict[str, Any]]


class PendingProviderInteractionResponseModel(BaseModel):
    """A pending interaction is returned only while its live delivery future exists."""

    interaction: Optional[PendingProviderInteractionModel] = None


@router.get(
    "/{agent_task_id}/execution-approvals/pending",
    response_model=PendingExecutionApprovalResponseModel,
    summary="Get a live pending generic execution approval for hydration",
)
async def get_pending_execution_approval(
    agent_task_id: str,
) -> PendingExecutionApprovalResponseModel:
    """Return every live approval plus stale IDs that need explicit recovery."""
    from api.dependencies import get_sqlite_knowledge_service

    knowledge_service = get_sqlite_knowledge_service()
    agent_task_record = await knowledge_service.get_agent_task(agent_task_id)
    if agent_task_record is None:
        raise HTTPException(status_code=404, detail=f"AgentTask {agent_task_id} not found")
    if agent_task_record.status in _TERMINAL_AGENT_TASK_STATUSES:
        return PendingExecutionApprovalResponseModel()

    approvals = await (
        knowledge_service.execution_approval_repository
        .list_pending_approvals_for_agent_task(agent_task_id)
    )
    live_approvals = []
    orphaned_approval_ids = []
    for approval in approvals:
        approval_id = str(approval["id"])
        if not InteractiveApprovalManager.has_pending_future(approval_id):
            orphaned_approval_ids.append(approval_id)
            continue
        render_context = approval.get("render_context")
        if not isinstance(render_context, dict):
            render_context = {}
        risk_metadata = render_context.get("risk_metadata")
        live_approvals.append(
            PendingExecutionApprovalModel(
                approval_id=approval_id,
                agent_task_id=agent_task_id,
                command=str(approval["command"]),
                reason=str(approval["reason"]),
                risk_level=str(approval["risk_level"]),
                generalized_pattern=str(approval["generalized_pattern"]),
                execution_type=str(approval.get("execution_type") or "shell"),
                script_content=str(approval["script_content"]) if approval.get("script_content") else None,
                revision=int(approval["revision"]),
                context={
                    "cwd": render_context.get("cwd"),
                    "source": render_context.get("source"),
                    "description": render_context.get("description"),
                },
                risk_metadata=risk_metadata if isinstance(risk_metadata, dict) else None,
            )
        )
    return PendingExecutionApprovalResponseModel(
        approvals=live_approvals,
        orphaned_approval_ids=orphaned_approval_ids,
    )


@router.post(
    "/{agent_task_id}/execution-approvals/recover",
    response_model=RecoverExecutionApprovalsResponse,
    summary="Retire approvals stranded after backend interruption",
)
async def recover_orphaned_execution_approvals(
    agent_task_id: str,
    request: RecoverExecutionApprovalsRequest,
) -> RecoverExecutionApprovalsResponse:
    """Cancel named orphaned approvals without approving or executing commands."""
    from api.dependencies import get_sqlite_knowledge_service
    from api.services.conversation.conversation_agent_turn_lifecycle import (
        clear_conversation_agent_attention,
    )

    knowledge_service = get_sqlite_knowledge_service()
    agent_task_record = await knowledge_service.get_agent_task(agent_task_id)
    if agent_task_record is None:
        raise HTTPException(status_code=404, detail=f"AgentTask {agent_task_id} not found")

    requested_ids = set(request.approval_ids)
    pending_approvals = await (
        knowledge_service.execution_approval_repository
        .list_pending_approvals_for_agent_task(agent_task_id)
    )
    pending_by_id = {str(approval["id"]): approval for approval in pending_approvals}
    missing_ids = requested_ids.difference(pending_by_id)
    if missing_ids:
        raise HTTPException(
            status_code=409,
            detail=f"Execution approvals are no longer pending: {sorted(missing_ids)}",
        )

    live_ids = [
        approval_id
        for approval_id in requested_ids
        if InteractiveApprovalManager.has_pending_future(approval_id)
    ]
    if live_ids:
        raise HTTPException(
            status_code=409,
            detail=f"Execution approvals are live and cannot be recovered: {sorted(live_ids)}",
        )

    for approval_id in request.approval_ids:
        approval = pending_by_id[approval_id]
        await knowledge_service.execution_approval_repository.cancel_pending_approval(
            approval_id=approval_id,
            expected_revision=int(approval["revision"]),
        )
        await clear_conversation_agent_attention(agent_task_id, approval_id)

    remaining_approvals = await (
        knowledge_service.execution_approval_repository
        .list_pending_approvals_for_agent_task(agent_task_id)
    )
    if not remaining_approvals:
        result_data = dict(agent_task_record.result_data or {})
        result_data["approval_recovery"] = {
            "cancelled_approval_ids": request.approval_ids,
            "reason": "backend_interrupted_approval_wait",
        }
        await knowledge_service.agent_task_service.update_agent_task_status(
            agent_task_id=agent_task_id,
            status="failed",
            result_data=result_data,
        )

    return RecoverExecutionApprovalsResponse(
        cancelled_approval_ids=request.approval_ids,
    )


@router.get(
    "/{agent_task_id}/provider-interactions/pending",
    response_model=PendingProviderInteractionResponseModel,
    summary="Get a live pending provider user-input interaction for hydration",
)
async def get_pending_provider_interaction(
    agent_task_id: str,
) -> PendingProviderInteractionResponseModel:
    from api.dependencies import get_sqlite_knowledge_service

    knowledge_service = get_sqlite_knowledge_service()
    agent_task_record = await knowledge_service.get_agent_task(agent_task_id)
    if agent_task_record is None:
        raise HTTPException(status_code=404, detail=f"AgentTask {agent_task_id} not found")
    if agent_task_record.status in _TERMINAL_AGENT_TASK_STATUSES:
        return PendingProviderInteractionResponseModel()

    interaction = await (
        knowledge_service.provider_interaction_repository.get_pending_interaction_for_agent_task(
            agent_task_id
        )
    )
    if interaction is None or not ProviderInteractionDeliveryRegistry.has_pending(str(interaction["id"])):
        return PendingProviderInteractionResponseModel()

    return PendingProviderInteractionResponseModel(
        interaction=PendingProviderInteractionModel(
            id=str(interaction["id"]),
            message=str(interaction["message"]),
            fields=list(interaction["fields"]),
        )
    )


@router.post(
    "/{agent_task_id}/provider-interactions/{interaction_id}/respond",
    response_model=ProviderInteractionResponseModel,
    summary="Respond to a durable provider user-input interaction",
)
async def respond_to_provider_interaction(
    agent_task_id: str,
    interaction_id: str,
    body: ProviderInteractionResponseRequest,
    request: Request,
) -> ProviderInteractionResponseModel:
    from api.dependencies import get_sqlite_knowledge_service

    outcome = body.outcome
    if outcome not in _SUPPORTED_OUTCOMES:
        raise HTTPException(status_code=422, detail=f"unsupported outcome {outcome!r}")

    knowledge_service = get_sqlite_knowledge_service()
    interaction = await knowledge_service.provider_interaction_repository.get_interaction(interaction_id)
    if interaction is None:
        raise HTTPException(status_code=404, detail=f"provider interaction {interaction_id!r} not found")
    if interaction["agent_task_id"] != agent_task_id:
        raise HTTPException(
            status_code=404,
            detail=(
                f"provider interaction {interaction_id!r} does not belong to "
                f"agent task {agent_task_id!r}"
            ),
        )
    if interaction["status"] != "pending":
        raise HTTPException(
            status_code=409,
            detail=(
                f"provider interaction {interaction_id!r} is no longer pending "
                f"(status={interaction['status']!r})"
            ),
        )

    agent_task_record = await knowledge_service.get_agent_task(agent_task_id)
    if agent_task_record is None:
        raise HTTPException(status_code=404, detail=f"AgentTask {agent_task_id} not found")
    if agent_task_record.status in _TERMINAL_AGENT_TASK_STATUSES:
        raise HTTPException(
            status_code=409,
            detail=f"AgentTask {agent_task_id} is terminal and cannot receive a provider interaction answer",
        )

    clean_values: Optional[Dict[str, str]] = None
    if outcome == "accept":
        try:
            clean_values = validate_submitted_values(interaction["fields"], body.values)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    if not ProviderInteractionDeliveryRegistry.claim(interaction_id):
        raise HTTPException(
            status_code=409,
            detail=(
                f"provider interaction {interaction_id!r} could not be delivered "
                "(stale or already resolved)"
            ),
        )

    try:
        expected_revision = int(interaction["revision"])
        if outcome == "accept":
            await knowledge_service.provider_interaction_repository.mark_answered(
                interaction_id=interaction_id,
                expected_revision=expected_revision,
                submitted_values=clean_values or {},
            )
        elif outcome == "decline":
            await knowledge_service.provider_interaction_repository.mark_declined(
                interaction_id=interaction_id,
                expected_revision=expected_revision,
            )
        else:
            await knowledge_service.provider_interaction_repository.mark_cancelled(
                interaction_id=interaction_id,
                expected_revision=expected_revision,
            )
    except ProviderInteractionConflictError as exc:
        ProviderInteractionDeliveryRegistry.release_claim(interaction_id)
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception:
        ProviderInteractionDeliveryRegistry.release_claim(interaction_id)
        raise

    try:
        submission_service = get_agent_task_submission_service(request)
    except HTTPException:
        submission_service = None
    orchestrator = getattr(submission_service, "agent_task_orchestrator", None)
    delegated_agent_controller = (
        getattr(orchestrator, "delegated_agent_controller", None) if orchestrator is not None else None
    )
    await _notify_delegated_agent_interaction_resolved(
        knowledge_service=knowledge_service,
        delegated_agent_controller=delegated_agent_controller,
        agent_task_id=agent_task_id,
        interaction_id=interaction_id,
    )

    delivered = ProviderInteractionDeliveryRegistry.deliver_claimed(interaction_id, outcome, clean_values)
    if not delivered:
        raise HTTPException(
            status_code=409,
            detail=f"provider interaction {interaction_id!r} was persisted but its live run ended before delivery",
        )

    return ProviderInteractionResponseModel(success=True, message="Provider interaction answer delivered.")


@router.post(
    "/{agent_task_id}/provider-interactions/{interaction_id}/permission-decision",
    response_model=ProviderPermissionDecisionResponseModel,
    summary="Decide a durable provider_permission interaction",
)
async def decide_provider_permission_interaction(
    agent_task_id: str,
    interaction_id: str,
    body: ProviderPermissionDecisionRequest,
    request: Request,
) -> ProviderPermissionDecisionResponseModel:
    from api.dependencies import get_sqlite_knowledge_service

    knowledge_service = get_sqlite_knowledge_service()
    interaction = await knowledge_service.provider_interaction_repository.get_interaction(interaction_id)
    if interaction is None:
        raise HTTPException(status_code=404, detail=f"provider interaction {interaction_id!r} not found")
    if interaction["agent_task_id"] != agent_task_id:
        raise HTTPException(
            status_code=404,
            detail=(
                f"provider interaction {interaction_id!r} does not belong to "
                f"agent task {agent_task_id!r}"
            ),
        )
    if interaction["interaction_kind"] != "provider_permission":
        raise HTTPException(
            status_code=422,
            detail=f"provider interaction {interaction_id!r} is not a provider_permission interaction",
        )
    if interaction["status"] != "pending":
        raise HTTPException(
            status_code=409,
            detail=(
                f"provider interaction {interaction_id!r} is no longer pending "
                f"(status={interaction['status']!r})"
            ),
        )

    agent_task_record = await knowledge_service.get_agent_task(agent_task_id)
    if agent_task_record is None:
        raise HTTPException(status_code=404, detail=f"AgentTask {agent_task_id} not found")
    if agent_task_record.status in _TERMINAL_AGENT_TASK_STATUSES:
        raise HTTPException(
            status_code=409,
            detail=f"AgentTask {agent_task_id} is terminal and cannot receive a permission decision",
        )

    if not ProviderInteractionDeliveryRegistry.claim(interaction_id):
        raise HTTPException(
            status_code=409,
            detail=(
                f"provider interaction {interaction_id!r} could not be delivered "
                "(stale or already resolved)"
            ),
        )

    try:
        if body.outcome == "cancel":
            if body.selected_option_id is not None:
                raise HTTPException(
                    status_code=422,
                    detail="selected_option_id must be omitted when outcome is 'cancel'",
                )
            await knowledge_service.provider_interaction_repository.cancel_permission_interaction(
                interaction_id=interaction_id,
                provider_run_id=str(interaction["provider_run_id"]),
                agent_task_id=agent_task_id,
                expected_revision=int(interaction["revision"]),
            )
            delivery_outcome = "cancel"
            delivery_values = None
        else:
            if body.selected_option_id is None or not body.selected_option_id.strip():
                raise HTTPException(
                    status_code=422,
                    detail="selected_option_id is required when outcome is 'selected'",
                )
            resolved = await knowledge_service.provider_interaction_repository.resolve_permission_interaction(
                interaction_id=interaction_id,
                provider_run_id=str(interaction["provider_run_id"]),
                agent_task_id=agent_task_id,
                expected_revision=int(interaction["revision"]),
                selected_option_id=body.selected_option_id,
            )
            selected_option_id = str(resolved["submitted_values"]["selected_option_id"])
            delivery_outcome = "selected"
            delivery_values = {"optionId": selected_option_id}
    except ProviderInteractionConflictError as exc:
        ProviderInteractionDeliveryRegistry.release_claim(interaction_id)
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except HTTPException:
        ProviderInteractionDeliveryRegistry.release_claim(interaction_id)
        raise
    except Exception:
        ProviderInteractionDeliveryRegistry.release_claim(interaction_id)
        raise

    try:
        submission_service = get_agent_task_submission_service(request)
    except HTTPException:
        submission_service = None
    orchestrator = getattr(submission_service, "agent_task_orchestrator", None)
    delegated_agent_controller = (
        getattr(orchestrator, "delegated_agent_controller", None) if orchestrator is not None else None
    )
    await _notify_delegated_agent_interaction_resolved(
        knowledge_service=knowledge_service,
        delegated_agent_controller=delegated_agent_controller,
        agent_task_id=agent_task_id,
        interaction_id=interaction_id,
    )

    delivered = ProviderInteractionDeliveryRegistry.deliver_claimed(
        interaction_id, delivery_outcome, delivery_values
    )
    if not delivered:
        raise HTTPException(
            status_code=409,
            detail=f"provider interaction {interaction_id!r} was persisted but its live run ended before delivery",
        )

    message = (
        "Provider permission prompt cancelled."
        if body.outcome == "cancel"
        else "Provider permission decision delivered."
    )
    return ProviderPermissionDecisionResponseModel(success=True, message=message)


__all__ = ["router"]
