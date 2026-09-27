"""Session continuation and checkpoint routes for agent-task execution."""

import logging
import time
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from api.services.agent_processing.lifecycle.runtime.workflow_coordinator import WorkflowCoordinator

from .execution_models import (
    CheckpointStatusResponse,
    ContinueSessionRequest,
    ContinueSessionResponseModel,
)

logger = logging.getLogger(__name__)

router = APIRouter()
TERMINAL_AGENT_TASK_STATUSES = {"cancelled", "completed", "failed"}


class CancelSessionRequest(BaseModel):
    reason: Optional[str] = None


class CancelSessionResponse(BaseModel):
    success: bool
    message: str
    finalized_via_agent: bool
    agent_task_id: str


async def _get_agent_task_or_raise(agent_task_id: str):
    """Load an agent task or return the route's canonical not-found response."""
    from api.dependencies import get_sqlite_knowledge_service

    knowledge_service = get_sqlite_knowledge_service()
    agent_task_record = await knowledge_service.agent_task_service.get_agent_task(agent_task_id)
    if agent_task_record is None:
        raise HTTPException(status_code=404, detail=f"AgentTask {agent_task_id} not found")
    return agent_task_record


@router.get("/sessions/{agent_task_id}/checkpoint-status", response_model=CheckpointStatusResponse, summary="Check Checkpoint Status")
async def get_checkpoint_status(
    agent_task_id: str,
    request: Request
) -> CheckpointStatusResponse:
    """
    Check if a resumable checkpoint exists for an agent task.
    
    This endpoint checks LangGraph's checkpoint store to determine if an agent task
    can be resumed from a checkpoint (via Continue) or must be retried from scratch.
    
    Args:
        agent_task_id: The agent task ID to check
        
    Returns:
        CheckpointStatusResponse indicating if checkpoint exists and can be resumed
    """
    try:
        # Use the submission service as websocket manager for agent-task workflow events.
        agent_task_submission_service = getattr(request.app.state, "agent_task_submission_service", None)
        if agent_task_submission_service is None:
            logger.error("❌ AgentTaskSubmissionService not available in app state")
            raise HTTPException(status_code=503, detail="Agent task submission service not available")
        
        coordinator = WorkflowCoordinator(websocket_manager=agent_task_submission_service)
        
        agent_task_record = await _get_agent_task_or_raise(agent_task_id)
        has_checkpoint = await coordinator.checkpoint_workflow_service.has_checkpoint(agent_task_id)
        is_terminal = agent_task_record.status in TERMINAL_AGENT_TASK_STATUSES
        can_resume = has_checkpoint and not is_terminal
        
        logger.info(
            "🔍 Checkpoint status for %s: has_checkpoint=%s can_resume=%s",
            agent_task_id,
            has_checkpoint,
            can_resume,
        )
        
        return CheckpointStatusResponse(
            agent_task_id=agent_task_id,
            has_checkpoint=has_checkpoint,
            can_resume=can_resume,
            message=(
                "Task is terminal and cannot be resumed"
                if is_terminal
                else "Checkpoint found - can resume"
                if has_checkpoint
                else "No checkpoint - must retry from scratch"
            ),
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Failed to check checkpoint status: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to check checkpoint status: {str(e)}")


@router.post("/sessions/{agent_task_id}/continue")
async def continue_session(
    agent_task_id: str,
    request: Request,
    body: ContinueSessionRequest
):
    """
    Continue a workflow that's awaiting user input at a checkpoint.
    
    This resumes the agent from where it paused, injecting the user's response.
    
    Args:
        agent_task_id: The agent task ID to continue
        body: Contains user_response and optional metadata
        
    Returns:
        ContinueSessionResponseModel with result or indication of more input needed
    """
    try:
        # Use user_input (Swift's field) with fallback to user_response (backwards compat)
        user_response = body.user_input or body.user_response or ""
        
        logger.info(f"🔄 Continue session request for agent_task_id: {agent_task_id}")
        logger.info(f"   User response: {user_response}")
        
        # Use the submission service as websocket manager for agent-task workflow events.
        agent_task_submission_service = getattr(request.app.state, "agent_task_submission_service", None)
        if agent_task_submission_service is None:
            logger.error("❌ AgentTaskSubmissionService not available in app state")
            raise HTTPException(status_code=503, detail="Agent task submission service not available")

        agent_task_record = await _get_agent_task_or_raise(agent_task_id)
        if agent_task_record.status in TERMINAL_AGENT_TASK_STATUSES:
            raise HTTPException(
                status_code=409,
                detail=f"AgentTask {agent_task_id} is terminal and cannot be resumed",
            )

        agent_task_orchestrator = getattr(
            agent_task_submission_service,
            "agent_task_orchestrator",
            None,
        )
        authorized_provider_delegation_submission_service = getattr(
            agent_task_orchestrator,
            "authorized_provider_delegation_submission_service",
            None,
        )
        coordinator = WorkflowCoordinator(
            websocket_manager=agent_task_submission_service,
            agent_task_submission_service=authorized_provider_delegation_submission_service,
        )
        
        # Resume the workflow with user's response
        result = await coordinator.resume_workflow(
            agent_task_id=agent_task_id,
            user_response=user_response
        )
        
        # Check if result indicates more input is needed (another checkpoint)
        # WorkflowExecutionResult doesn't have 'summary' - check tool_execution_results for checkpoint status
        requires_more = False
        if result.execution_results:
            last_result = result.execution_results[-1] if result.execution_results else {}
            if isinstance(last_result, dict):
                requires_more = last_result.get("status") == "awaiting_user_input"
        
        # Extract result message from the workflow result
        result_message = None
        if hasattr(result, 'final_envelope') and result.final_envelope:
            result_payload = result.final_envelope.get('result_payload', {})
            result_message = result_payload.get('message') or result_payload.get('result')
        if not result_message:
            # Fallback to building a summary from execution results
            result_message = f"Completed {result.todos_completed} tasks" if result.overall_success else result.error_message or "Workflow completed"
        
        logger.info(f"✅ Session continued. Requires more input: {requires_more}")
        
        return ContinueSessionResponseModel(
            success=True,
            message="Session continued successfully",
            session=None,  # We don't have a full session object to return
            requires_more_input=requires_more,
            result=result_message
        )
        
    except HTTPException:
        raise
    except ValueError as e:
        # Checkpoint not found
        logger.warning(f"⚠️ Cannot continue session: {e}")
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"❌ Failed to continue session: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to continue session: {str(e)}")


@router.post("/sessions/{agent_task_id}/cancel", response_model=CancelSessionResponse, summary="Cancel Session")
async def cancel_session(
    agent_task_id: str,
    request: Request,
    body: CancelSessionRequest,
) -> CancelSessionResponse:
    """
    Cancel an in-progress agent-task session.

    Cancellation is terminal: it preempts active runtime work where possible and
    persists each active task in the requested chain as `cancelled`. Retained
    checkpoints are never resumed from this route.

    Args:
        agent_task_id: The agent task to cancel.
        body: Optional `reason` string for logging / audit.

    Returns:
        CancelSessionResponse describing what code path was taken.
    """
    reason = (body.reason or "").strip()
    route_started_at = time.perf_counter()
    logger.info(
        "🛑 Cancel session request task=%s reason=%r request_received=%.6f",
        agent_task_id,
        reason,
        route_started_at,
    )

    agent_task_submission_service = getattr(request.app.state, "agent_task_submission_service", None)
    if agent_task_submission_service is None:
        logger.error("❌ AgentTaskSubmissionService not available in app state")
        raise HTTPException(status_code=503, detail="Agent task submission service not available")

    try:
        cancellation = await agent_task_submission_service.cancel_agent_task_durably(
            agent_task_id=agent_task_id,
            reason=reason or "user_cancelled",
        )
        durable_at = time.perf_counter()
        response_at = time.perf_counter()
        preemption_at = cancellation.get("preemption_completed_at", route_started_at)
        durable_at = cancellation.get("durable_completed_at", durable_at)
        cleanup_at = cancellation.get("cleanup_completed_at", durable_at)
        logger.info(
            "🛑 Durable cancellation completed root=%s tasks=%s preemption_ms=%.1f "
            "durable_ms=%.1f cleanup_ms=%.1f total_ms=%.1f",
            cancellation["root_task_id"],
            cancellation["cancelled_task_ids"],
            (preemption_at - route_started_at) * 1000,
            (durable_at - preemption_at) * 1000,
            (cleanup_at - durable_at) * 1000,
            (response_at - route_started_at) * 1000,
        )
        return CancelSessionResponse(
            success=True,
            message="Session cancelled.",
            finalized_via_agent=False,
            agent_task_id=cancellation["root_task_id"],
        )
    except KeyError:
        raise HTTPException(status_code=404, detail=f"AgentTask {agent_task_id} not found")
    except Exception as e:
        logger.error(f"❌ Failed to cancel agent_task {agent_task_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to cancel session: {str(e)}")
