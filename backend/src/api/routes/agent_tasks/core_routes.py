"""Core agent task routes."""

import asyncio
import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from api.core.knowledge.sqlite.sqlite_knowledge_service import SQLiteKnowledgeService
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.infrastructure.connection import (
    get_sync_connection,
)
from api.core.security.backend_request_guard import current_credential_type
from api.dependencies import get_agent_task_submission_service, get_sqlite_knowledge_service
from api.services.agent_processing.lifecycle.submission import AgentTaskSubmissionService
from api.services.skills.skill_service import get_skill_service
from api.services.skills.skill_context_builder import build_context_for_completed_tasks
from api.services.skills.skill_evaluator import (
    CompletedTask,
    SkillEvaluator,
)
from api.services.skills.skill_store import SkillBackpressureError

from .revision_routes import router as revision_router
from .models import (
    AgentTaskClarificationRequest,
    AgentTaskClarificationResponse,
    AgentTaskProcessingResponse,
    AgentTaskRequest,
    DeleteAgentTaskResponse,
    RetryAgentTaskRequest,
)
from api.services.agent_processing.tools.direct_application_interactions.local_web_preview.local_preview_authorization import (
    build_local_preview_feedback_context,
    resolve_task_owned_preview_artifact,
    validate_preview_screenshot_path,
    validate_preview_url,
)
from .utils import build_retry_context

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/agent-tasks", tags=["Agent Tasks"])

# Hold references to detached fast-lane tasks so they are not garbage-collected
# before completion (asyncio only keeps weak references to bare ensure_future
# tasks) -- same hazard/fix as async_finalizer.py's _PENDING_VERIFICATIONS.
_PENDING_FAST_LANE_TASKS: set = set()


class SaveAgentTaskAsSkillRequest(BaseModel):
    title: Optional[str] = None
    body: Optional[str] = None
    when_to_use: Optional[str] = None
    triggers: List[str] = Field(default_factory=list)
    preview_only: bool = False
    enhances_skill_slug: Optional[str] = None


class SaveAgentTaskAsSkillResponse(BaseModel):
    slug: Optional[str] = None
    title: str
    body: str
    when_to_use: str
    triggers: List[str]
    saved: bool
    enhances_skill_slug: Optional[str] = None


class AgentTaskFeedbackRequest(BaseModel):
    user_rating: int = Field(ge=-1, le=1, description="-1 thumbs down, 0 neutral, 1 thumbs up")
    user_feedback: Optional[str] = None


class AgentTaskFeedbackResponse(BaseModel):
    agent_task_id: str
    user_rating: int
    user_feedback: Optional[str] = None


def _select_skill_evaluator_model_id() -> str:
    """Use the configured skill model, falling back to the active reasoning model."""
    from api.core.preferences.preferences_io import load_preferences

    preferences = load_preferences()
    memory_intelligence = getattr(preferences, "memory_intelligence", None)
    skill_model = getattr(memory_intelligence, "skill_processing_model", None)
    return skill_model or preferences.models.reasoning_model


async def _resolve_local_preview_feedback_context(
    payload: AgentTaskRequest,
    knowledge_service: SQLiteKnowledgeService,
) -> Optional[Dict[str, Any]]:
    feedback = payload.local_preview_feedback
    if feedback is None:
        return None
    if not payload.root_task_id or not payload.previous_task_id:
        raise HTTPException(
            status_code=422,
            detail="local_preview_feedback requires an existing root_task_id and previous_task_id.",
        )
    artifact = await resolve_task_owned_preview_artifact(
        knowledge_service=knowledge_service,
        requested_agent_task_id=payload.root_task_id,
        artifact_id=feedback.source_artifact_id,
    )
    preview_url = validate_preview_url(feedback.mode, feedback.preview_url, artifact_local_path=artifact.local_path)
    screenshot = validate_preview_screenshot_path(feedback.screenshot_path)
    context = build_local_preview_feedback_context(
        artifact=artifact,
        mode=feedback.mode,
        preview_url=preview_url,
        location_status=feedback.location_status,
        screenshot=screenshot,
        console_evidence=feedback.console_evidence,
        session_id=feedback.session_id,
        session_status=feedback.session_status,
    )
    existing_reference_paths = [
        path
        for path in payload.reference_paths or []
        if path != feedback.screenshot_path
    ]
    if screenshot.get("status") == "available" and "path" in screenshot:
        payload.reference_paths = [*existing_reference_paths, screenshot["path"]]
    else:
        payload.reference_paths = existing_reference_paths or None
    return context


@router.post("/process", response_model=None, summary="Process AgentTask")
async def process_agent_task(
    payload: AgentTaskRequest,
    service: AgentTaskSubmissionService = Depends(get_agent_task_submission_service),
    knowledge_service: SQLiteKnowledgeService = Depends(get_sqlite_knowledge_service),
    credential_type: Optional[str] = Depends(current_credential_type),
) -> AgentTaskProcessingResponse:
    """
    Process a agent_task through the complete pipeline.
    This bypasses wake word detection and directly processes the agent task.
    Used for clarification submissions and direct agent_task processing.

    Current first-time tasks resolve to multi_step_workflow and use the
    event-driven direct processing path. Discussion follow-ups return a direct
    text response without entering the full tool pipeline.
    """
    try:
        if not payload.agent_task.strip():
            raise HTTPException(status_code=400, detail="AgentTask cannot be empty")

        if payload.approval_policy_override and credential_type != "host":
            raise HTTPException(status_code=403, detail="approval_policy_override requires the host credential.")

        logger.info(f"Testing agent-task processing with: '{payload.agent_task}'")

        preview_feedback_context = await _resolve_local_preview_feedback_context(payload, knowledge_service)

        operation_type = "multi_step_workflow" if preview_feedback_context else await service.determine_operation_type(
            payload.agent_task, payload.clarification_agent_task,
            root_task_id=payload.root_task_id,
            model_id=payload.model_id,
        )

        # Fast-lane follow-ups bypass the full agent pipeline. Dispatched
        # fire-and-forget (matching multi_step_workflow's event-driven shape)
        # so the HTTP response returns immediately and the streamed answer +
        # terminal agent_task_result arrive over the WebSocket -- the
        # frontend already ignores this response body (TextFollowUp.tsx
        # calls processAgentTask(...).catch(...) with no .then()).
        if operation_type == "discussion" and payload.root_task_id:
            fast_lane_agent_task_id = payload.agent_task_id or str(uuid.uuid4())
            fast_lane_task = asyncio.ensure_future(
                service.handle_discussion_followup(
                    agent_task=payload.agent_task,
                    root_task_id=payload.root_task_id,
                    previous_task_id=payload.previous_task_id,
                    agent_task_id=fast_lane_agent_task_id,
                    model_id=payload.model_id,
                )
            )
            _PENDING_FAST_LANE_TASKS.add(fast_lane_task)
            fast_lane_task.add_done_callback(_PENDING_FAST_LANE_TASKS.discard)
            return AgentTaskProcessingResponse(
                success=True,
                operation="discussion",
                confidence=1.0,
                reasoning="Fast-lane follow-up accepted; answer streams over the WebSocket",
                message="AgentTask received and being processed...",
                processing_time=0.0,
                agent_task_id=fast_lane_agent_task_id,
            )

        logger.info(f"Operation '{operation_type}' will return complete response")
        result = await service.process_agent_task_direct(
            agent_task=payload.agent_task,
            display_prompt_markdown=payload.display_prompt_markdown,
            clarification_agent_task=payload.clarification_agent_task,
            agent_task_id=payload.agent_task_id,
            root_task_id=payload.root_task_id,
            previous_task_id=payload.previous_task_id,
            reference_paths=payload.reference_paths,
            model_id=payload.model_id,
            approval_policy_override=payload.approval_policy_override,
            local_preview_feedback=preview_feedback_context,
        )

        # Extract response data
        success = result.get("success", False)
        operation = result.get("operation")
        confidence = result.get("confidence")
        message = result.get("message", "AgentTask processed")
        processing_time = result.get("processing_time")

        return AgentTaskProcessingResponse(
            success=success,
            operation=operation or "unknown",
            confidence=confidence or 0.0,
            reasoning=result.get("reasoning", ""),
            message=message,
            processing_time=processing_time or 0.0,
            agent_task_id=result.get("agent_task_id")  # Return the agent_task_id from the service response
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error testing agent-task processing: {e}", exc_info=True)
        # Return error as JSON (streaming check will always be False for error case)
        return AgentTaskProcessingResponse(
            success=False,
            operation="error",
            confidence=0.0,
            reasoning=f"Error occurred during processing: {str(e)}",
            message="AgentTask processing test failed",
            processing_time=0.0,
            agent_task_id=None  # No agent_task_id for error responses
        )


@router.post("/{agent_task_id}/clarifications", response_model=AgentTaskClarificationResponse, summary="Add Clarification to Existing AgentTask")
async def add_clarification(
    agent_task_id: str,
    payload: AgentTaskClarificationRequest,
    service: AgentTaskSubmissionService = Depends(get_agent_task_submission_service)
) -> AgentTaskClarificationResponse:
    """
    Add clarification to an existing agent_task.
    This preserves the original agent-task context (OCR, window data, etc.) and processes
    the clarification in the context of the original agent task.
    """
    try:
        if not payload.clarification_text.strip():
            raise HTTPException(status_code=400, detail="Clarification text cannot be empty")

        payload.agent_task_id = payload.agent_task_id or agent_task_id

        logger.info(f"Adding clarification to agent task {payload.agent_task_id}: '{payload.clarification_text}'")

        # Use the orchestrator's add_clarification method instead of creating a new agent task
        result = await service.add_clarification(
            agent_task_id=payload.agent_task_id,
            clarification_text=payload.clarification_text
        )

        return AgentTaskClarificationResponse(
            success=result.get("success", False),
            agent_task_id=payload.agent_task_id,
            message=result.get("message", "Clarification processed"),
            error=result.get("error")
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error adding clarification: {e}", exc_info=True)
        return AgentTaskClarificationResponse(
            success=False,
            agent_task_id=payload.agent_task_id,
            message="Failed to process clarification",
            error=str(e)
        )


@router.post("/{agent_task_id}/save-as-skill", response_model=SaveAgentTaskAsSkillResponse)
async def save_agent_task_as_skill(
    agent_task_id: str,
    request: SaveAgentTaskAsSkillRequest,
    knowledge_service: SQLiteKnowledgeService = Depends(get_sqlite_knowledge_service),
) -> SaveAgentTaskAsSkillResponse:
    """Preview or save a completed agent task as a reusable markdown skill."""
    agent_task_record = await knowledge_service.agent_task_service.get_agent_task(agent_task_id)
    if not agent_task_record:
        raise HTTPException(status_code=404, detail=f"AgentTask {agent_task_id} not found")
    if agent_task_record.status != "completed":
        raise HTTPException(status_code=400, detail="Only completed agent tasks can be saved as skills.")

    result_data = agent_task_record.result_data or {}
    tool_execution_results = result_data.get("tool_execution_results") or []
    first_tool_result = tool_execution_results[0] if tool_execution_results else {}

    if request.preview_only:
        final_envelope = result_data.get("final_envelope")
        result_summary = final_envelope.get("summary_text") if isinstance(final_envelope, dict) else None
        completed_task = CompletedTask(
            id=agent_task_id,
            title=agent_task_record.title,
            original_prompt=agent_task_record.original_prompt,
            transcribed_prompt=agent_task_record.transcribed_prompt,
            result_summary=result_summary or getattr(agent_task_record, "result_preview", None),
            execution_timeline=agent_task_record.execution_timeline or [],
            intermediate_step_summaries=first_tool_result.get("intermediate_step_summaries") or [],
            completed_at=getattr(agent_task_record, "updated_at", None),
        )
        try:
            candidate = await SkillEvaluator(
                model_id=_select_skill_evaluator_model_id()
            ).evaluate_completed_task(
                completed_task,
                existing_context=build_context_for_completed_tasks(completed_task),
            )
        except Exception as exc:
            logger.exception("Skill preview generation failed for agent task %s", agent_task_id)
            raise HTTPException(
                status_code=502,
                detail=f"Failed to generate a skill preview: {exc}",
            ) from exc

        if not candidate:
            raise HTTPException(
                status_code=422,
                detail="This task does not contain enough reusable procedure to save as a skill.",
            )

        return SaveAgentTaskAsSkillResponse(
            title=candidate.title,
            body=candidate.procedure_markdown,
            when_to_use=candidate.when_to_use,
            triggers=candidate.triggers,
            saved=False,
            enhances_skill_slug=candidate.enhances_skill_slug,
        )

    if not request.title or not request.body or not request.when_to_use:
        raise HTTPException(
            status_code=400,
            detail="A skill preview must be generated before saving.",
        )

    try:
        skill = get_skill_service().save_skill(
            title=request.title,
            body=request.body,
            when_to_use=request.when_to_use,
            triggers=request.triggers,
            source_task_ids=[agent_task_id],
            slug=request.enhances_skill_slug,
            creation_origin_key=(
                None
                if request.enhances_skill_slug
                else f"agent-task:{agent_task_id}"
            ),
        )
    except SkillBackpressureError as exc:
        raise HTTPException(
            status_code=413,
            detail={
                "message": str(exc),
                "slug": exc.slug,
                "cap_bytes": exc.cap_bytes,
                "attempted_bytes": exc.attempted_bytes,
            },
        ) from exc
    except Exception as exc:
        logger.exception("Skill save failed for agent task %s", agent_task_id)
        raise HTTPException(status_code=500, detail=f"Failed to save skill: {exc}") from exc

    return SaveAgentTaskAsSkillResponse(
        slug=skill.slug,
        title=str(skill.metadata.get("title") or request.title),
        body=skill.body,
        when_to_use=str(skill.metadata.get("when_to_use") or request.when_to_use),
        triggers=[
            str(trigger)
            for trigger in skill.metadata.get("triggers", [])
            if isinstance(trigger, str)
        ],
        saved=True,
        enhances_skill_slug=request.enhances_skill_slug,
    )


@router.post("/{agent_task_id}/feedback", response_model=AgentTaskFeedbackResponse)
async def update_agent_task_feedback(
    agent_task_id: str,
    request: AgentTaskFeedbackRequest,
    knowledge_service: SQLiteKnowledgeService = Depends(get_sqlite_knowledge_service),
) -> AgentTaskFeedbackResponse:
    """Store user feedback for a completed agent task."""
    agent_task_record = await knowledge_service.agent_task_service.get_agent_task(agent_task_id)
    if not agent_task_record:
        raise HTTPException(status_code=404, detail=f"AgentTask {agent_task_id} not found")

    connection = get_sync_connection(
        knowledge_service.db_path, operation_name="agent_task_feedback_update"
    )
    try:
        connection.execute(
            """
            UPDATE agent_tasks
            SET user_rating = ?, user_feedback = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                request.user_rating,
                request.user_feedback,
                datetime.now().isoformat(),
                agent_task_id,
            ),
        )
        connection.commit()
    finally:
        connection.close()

    return AgentTaskFeedbackResponse(
        agent_task_id=agent_task_id,
        user_rating=request.user_rating,
        user_feedback=request.user_feedback,
    )


@router.get("/examples", response_model=Dict[str, Any], summary="Get Example tasks")
async def get_agent_task_examples() -> Dict[str, Any]:
    """
    Get examples of agent_tasks that can be processed by the system.
    Useful for testing and user guidance.
    """
    try:
        examples = {
            "screen_capture": [
                "take a screenshot",
                "capture the screen",
                "save what's on my screen"
            ],
            "text_extraction": [
                "read this text",
                "extract the text from the screen",
                "what does this say"
            ],
            "suggestions": [
                "help me draft a response",
                "give me suggestions",
                "what should I say"
            ],
            "conversation_analysis": [
                "analyze this conversation",
                "summarize this discussion",
                "what are the key points"
            ],
            "voice_suggestions": [
                "help me respond verbally",
                "suggest what to say",
                "give me talking points"
            ],
            "knowledge_queries": [
                "what do you know about this topic",
                "search my knowledge base",
                "find information about"
            ],
            "activity_queries": [
                "what did I work on yesterday",
                "show me my recent activity",
                "what have I been doing"
            ]
        }

        return {
            "examples": examples,
            "usage": "Use these as examples for the /process endpoint",
            "note": "AgentTasks are processed using natural language understanding"
        }
    except Exception as e:
        logger.error(f"Error getting agent-task examples: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Error retrieving agent-task examples")


router.include_router(revision_router)


async def _retire_pending_execution_approval_for_retry(
    knowledge_service: SQLiteKnowledgeService,
    agent_task_id: str,
) -> None:
    """Cancel an obsolete approval before the same task ID re-enters routing."""
    from api.services.agent_processing.tools.safety.execution_approval_retirement import (
        retire_pending_execution_approvals,
    )

    await retire_pending_execution_approvals(
        knowledge_service.execution_approval_repository,
        [agent_task_id],
    )


@router.post("/{agent_task_id}/retry", response_model=AgentTaskProcessingResponse, summary="Retry AgentTask")
async def retry_agent_task(
    agent_task_id: str,
    request: Optional[RetryAgentTaskRequest] = None,
    knowledge_service: SQLiteKnowledgeService = Depends(get_sqlite_knowledge_service),
    service: AgentTaskSubmissionService = Depends(get_agent_task_submission_service)
) -> AgentTaskProcessingResponse:
    """
    Retry a agent_task by re-initiating it with the original context.

    This endpoint:
    1. Retrieves the stored agent-task context (original_prompt, screen_text, screen_capture_path)
    2. Normalizes the stored agent task into a retryable baseline
    3. Re-initiates the agent-task processing pipeline with the same context

    Use this for agent tasks that failed due to transient errors (network issues, timeouts).
    For agent tasks with checkpoints, use the continue endpoint instead.
    """
    try:
        # Get the stored agent task from database
        agent_task_record = await knowledge_service.agent_task_service.get_agent_task(agent_task_id)

        if not agent_task_record:
            raise HTTPException(status_code=404, detail=f"AgentTask {agent_task_id} not found")

        logger.info(f"🔄 Retrying agent task {agent_task_id} from status '{agent_task_record.status}': '{agent_task_record.original_prompt[:50]}...'")
        retry_context = build_retry_context(agent_task_record)
        retry_result_data = {
            "retry_context": retry_context,
            "previous_attempts": [
                *(agent_task_record.result_data or {}).get("previous_attempts", []),
                retry_context,
            ],
            "retry_started_at": datetime.utcnow().isoformat(),
        }

        model_override = (request or RetryAgentTaskRequest()).model_id
        updated_accumulated_artifacts: Optional[Dict[str, Any]] = None
        if model_override:
            updated_accumulated_artifacts = {
                **(agent_task_record.accumulated_artifacts or {}),
                "model_id": model_override,
            }

        if agent_task_record.status != "failed":
            if agent_task_record.status in {"routing", "processing", "awaiting_user_input", "capturing"}:
                try:
                    await service.cancel_current_agent_task(agent_task_id=agent_task_id)
                except Exception as cancel_err:
                    logger.debug(f"Retry reset cancel returned for {agent_task_id}: {cancel_err}")

            reset_result_data = {
                **(agent_task_record.result_data or {}),
                "retry_reset": {
                    "previous_status": agent_task_record.status,
                    "reset_at": datetime.utcnow().isoformat(),
                },
            }
            await knowledge_service.agent_task_service.update_agent_task_status(
                agent_task_id=agent_task_id,
                status="failed",
                result_data=reset_result_data,
            )

        await _retire_pending_execution_approval_for_retry(
            knowledge_service,
            agent_task_id,
        )

        # Update status back to "routing" to re-trigger the processing pipeline
        # This will cause the orchestrator's event system to automatically:
        # 1. Re-route the agent task (uses stored screen_text and screen_capture_path)
        # 2. Re-process the agent task with the same context
        # The stored screen_text and screen_capture_path are already in the database
        # and will be used by _build_routing_request during processing
        await knowledge_service.agent_task_service.clear_agent_task_execution_timeline(agent_task_id)
        await knowledge_service.agent_task_service.update_agent_task_status(
            agent_task_id=agent_task_id,
            status="routing",
            result_data=retry_result_data,
            accumulated_artifacts=updated_accumulated_artifacts,
        )

        logger.info(f"✅ Retry initiated - agent task {agent_task_id} status updated to 'routing'")

        # Return success response - actual processing happens asynchronously via events
        # WebSocket events will update the frontend with progress
        return AgentTaskProcessingResponse(
            success=True,
            operation="multi_step_workflow",
            confidence=1.0,
            reasoning="AgentTask retry initiated - processing will resume with stored context",
            message="Retry initiated successfully",
            processing_time=0.0,
            agent_task_id=agent_task_id
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrying agent_task: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error retrying agent_task: {str(e)}")


@router.delete("/{agent_task_id}", response_model=DeleteAgentTaskResponse, summary="Delete AgentTask")
async def delete_agent_task(
    agent_task_id: str,
    cascade: bool = Query(True, description="Also delete all follow-up agent tasks in the chain"),
    knowledge_service: SQLiteKnowledgeService = Depends(get_sqlite_knowledge_service),
    service: AgentTaskSubmissionService = Depends(get_agent_task_submission_service)
) -> DeleteAgentTaskResponse:
    """
    Delete a agent_task by ID.
    Also stops any active processing for this agent task before deletion.
    By default, also deletes all follow-up agent tasks in the chain (cascade=True).
    """
    try:
        # First, cancel any active processing for this agent task
        try:
            await service.cancel_current_agent_task(agent_task_id=agent_task_id)
            logger.info(f"Canceled active processing for agent task {agent_task_id}")
        except Exception as cancel_err:
            # Non-fatal - agent task might not be actively processing
            logger.debug(f"Cancel processing returned: {cancel_err}")

        # Then delete from database
        success = await knowledge_service.agent_task_service.delete_agent_task(
            agent_task_id=agent_task_id,
            cascade=cascade
        )

        if not success:
            raise HTTPException(status_code=404, detail=f"AgentTask {agent_task_id} not found")

        logger.info(f"Deleted agent_task {agent_task_id} (cascade={cascade})")

        return DeleteAgentTaskResponse(
            success=True,
            message="AgentTask deleted successfully"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting agent_task: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error deleting agent_task: {str(e)}")
