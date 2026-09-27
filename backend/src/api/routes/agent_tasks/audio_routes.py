"""Agent-task audio routes for audio file processing and refinement."""

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
from typing import Dict, Any, Optional, List
import asyncio
import logging
import uuid
import json

from api.dependencies import get_agent_task_submission_service, resolve_transcription_service
from api.services.agent_processing.lifecycle.submission import AgentTaskSubmissionService
from api.services.transcription.backends.parakeet_components import (
    PARAKEET_PROGRESS_CALLBACK_CONTEXT_KEY,
    ParakeetTranscriptionProgress,
)

logger = logging.getLogger(__name__)

# Included by the agent-tasks router under /api/v1/agent-tasks.
router = APIRouter(tags=["agent-task-audio"])

# Response Models

class AgentTaskAudioResponse(BaseModel):
    """Response model for agent-task audio processing endpoint."""
    success: bool
    message: str
    transcription: str
    processing_result: Optional[Dict[str, Any]] = None
    processed: bool
    method: str = "swift_audio_capture_service"

class ExecutionResultSummary(BaseModel):
    """Summary of workflow execution result."""
    success: bool
    todos_completed: int
    workflow_summary: str

class AgentTaskRefinementResponse(BaseModel):
    """Response model for agent-task refinement endpoint."""
    success: bool
    message: str
    transcription: str
    refinement_agent_task_id: str
    root_task_id: str
    execution_result: ExecutionResultSummary
    processed: bool
    refinement_iteration: int

# Endpoints

@router.post("/process-audio", response_model=AgentTaskAudioResponse)
async def process_agent_task_audio(
    audio_file: UploadFile = File(..., description="Audio recording to transcribe and process as agent_task"),
    agent_task_id: Optional[str] = Form(None, description="Pre-generated AgentTask ID from frontend (for multi-agent support)"),
    root_task_id: Optional[str] = Form(None, description="Explicit root task ID if this is a follow-up in a chain"),
    previous_task_id: Optional[str] = Form(None, description="Immediate predecessor task ID if this is a follow-up"),
    reference_paths: Optional[str] = Form(None, description="JSON array of file/folder paths for context"),
    model_id: Optional[str] = Form(None, description="Optional reasoning-model override for this AgentTask"),
    service: AgentTaskSubmissionService = Depends(get_agent_task_submission_service)
) -> AgentTaskAudioResponse:
    """
    Process audio for agent task through the proven file-based transcription pipeline.
    
    This endpoint provides a reliable alternative to FFmpeg-based audio capture by accepting
    audio files from the frontend Swift AudioCaptureService. It mirrors the assistant-session
    pattern for maximum reliability.
    
    Args:
        audio_file: WAV audio file captured by Swift AudioCaptureService
        agent_task_id: Optional pre-generated AgentTask ID (for multi-agent support, frontend generates UUID)
        model_id: Optional reasoning-model override selected in the capture widget
        service: Voice listener service dependency
        
    Returns:
        AgentTaskAudioResponse: Processing result with success status and any relevant data
        
    Raises:
        HTTPException: If audio processing fails
    """
    # Resolve wake-word service / orchestration once so all branches below can
    # cooperate with the backend lifecycle gate. The orchestration owns the
    # gate that prevents new wake captures during capture/transcription handoff.
    wake_word_service = getattr(service, "wake_word_service", None)
    orchestration = getattr(wake_word_service, "agent_task_orchestration_service", None) \
        if wake_word_service is not None else None

    # Take ownership of the wake-capture key the orchestration acquired when
    # the wake word fired. We acquire our own transcription key first so the
    # gate never becomes idle in the brief window between capture-end and
    # transcription-start (which previously let wake detection reopen).
    transcription_key: Optional[str] = None
    inherited_capture_key: Optional[str] = None
    transcription_lifecycle_active = False
    if orchestration is not None:
        try:
            transcription_key = f"transcription:{agent_task_id or uuid.uuid4()}"
            orchestration.acquire_lifecycle(transcription_key, source="audio_route_entry")
            transcription_lifecycle_active = True
            if hasattr(orchestration, "consume_active_wake_capture_key"):
                inherited_capture_key = orchestration.consume_active_wake_capture_key()
            if inherited_capture_key:
                orchestration.release_lifecycle(
                    inherited_capture_key, "transferred_to_transcription"
                )
        except Exception as gate_exc:
            logger.warning(f"[AGENT_TASK_AUDIO] Lifecycle gate setup failed: {gate_exc}")

    def _release_transcription_lifecycle(reason: str) -> None:
        """Release our transcription key if still held (idempotent)."""
        nonlocal transcription_lifecycle_active
        if (
            orchestration is not None
            and transcription_lifecycle_active
            and transcription_key
        ):
            try:
                orchestration.release_lifecycle(transcription_key, reason)
            except Exception as release_exc:
                logger.debug(
                    f"[AGENT_TASK_AUDIO] Lifecycle release '{reason}' failed: {release_exc}"
                )
            transcription_lifecycle_active = False

    def _clear_agent_task_capture_state(reason: str) -> None:
        """Clear legacy capture flags once frontend-visible transcription is delivered."""
        try:
            if wake_word_service and hasattr(wake_word_service, "_hotkey_client_owned_capture"):
                wake_word_service._hotkey_client_owned_capture = False
            if wake_word_service:
                wake_word_service._is_capturing_agent_task = False
                wake_word_service._agent_task_cancelled = False
        except Exception as cleanup_exc:
            logger.debug(
                f"[AGENT_TASK_AUDIO] Capture state cleanup '{reason}' failed: {cleanup_exc}"
            )

    try:
        logger.info(f"[AGENT_TASK_AUDIO] Processing audio file: {audio_file.filename}, content_type: {audio_file.content_type}")
        
        # Validate audio file
        if not audio_file.content_type or not audio_file.content_type.startswith('audio/'):
            _release_transcription_lifecycle("invalid_content_type")
            raise HTTPException(
                status_code=400,
                detail="Invalid file type. Must be an audio file."
            )
        
        # Read audio data
        audio_data = await audio_file.read()
        
        if len(audio_data) < 44:  # Minimum size for a valid WAV header
            _release_transcription_lifecycle("audio_too_small")
            raise HTTPException(
                status_code=400,
                detail="Invalid audio file: File too small to be valid audio"
            )
        
        logger.info(f"[AGENT_TASK_AUDIO] Received {len(audio_data)} bytes of audio data")
        
        # Prepare context information for agent-task processing
        context_info = {
            'source': 'agent_task',
            'notes': 'Agent task captured via Swift AudioCaptureService (dual capture approach)',
            'original_filename': audio_file.filename or 'agent_task.wav',
            'capture_method': 'swift_frontend_reliable',
            'file_size': len(audio_data),
            'content_type': audio_file.content_type
        }
        loop = asyncio.get_running_loop()

        def _broadcast_parakeet_progress(progress: ParakeetTranscriptionProgress) -> None:
            if not agent_task_id:
                logger.info(
                    "[AGENT_TASK_AUDIO] Parakeet progress without agent_task_id: %s",
                    progress.to_payload(),
                )
                return

            async def _send_progress() -> None:
                progress_event: Dict[str, Any] = {
                    "event_type": "agent_task_progress",
                    "agent_task_id": agent_task_id,
                    "step": "Transcribing request",
                    "status": "running",
                    "details": progress.message,
                    "progress": progress.to_payload(),
                }
                if root_task_id:
                    progress_event["root_task_id"] = root_task_id
                if previous_task_id:
                    progress_event["previous_task_id"] = previous_task_id
                await service.broadcast(progress_event)

            loop.call_soon_threadsafe(lambda: asyncio.create_task(_send_progress()))

        context_info[PARAKEET_PROGRESS_CALLBACK_CONTEXT_KEY] = _broadcast_parakeet_progress
        
        logger.info(f"[AGENT_TASK_AUDIO] Processing audio with context: {context_info}")

        # Hard cancellation guard: if user explicitly cancelled, drop immediately
        # Accept post-completion uploads (normal case) to avoid losing final audio
        try:
            is_cancelled = bool(getattr(wake_word_service, "_agent_task_cancelled", False))
            if is_cancelled:
                logger.info("[AGENT_TASK_AUDIO] Dropping audio due to explicit cancel request")
                _release_transcription_lifecycle("cancelled_by_user")
                return AgentTaskAudioResponse(
                    success=False,
                    message="Agent task was cancelled",
                    transcription="",
                    processed=False,
                    method="swift_audio_capture_service"
                )
        except Exception:
            pass
        
        # Resolve the correct transcription service based on current preferences
        transcription_service = resolve_transcription_service()
        
        if not transcription_service:
            raise HTTPException(
                status_code=500,
                detail="Transcription service not available"
            )
        
        # Transcribe the audio using the file-based approach
        logger.info("[AGENT_TASK_AUDIO] Starting transcription via proven file-based pipeline...")
        
        # Use the transcribe method with audio bytes directly
        transcribed_text = await transcription_service.transcribe(
            audio_data,
            context_info=context_info
        )
        
        if not transcribed_text or not transcribed_text.strip():
            logger.warning("[AGENT_TASK_AUDIO] No transcription result - audio may be empty or unclear")
            # Broadcast a provisional-failure event so the result widget can
            # remove the pre-generated agent_task_id row that was installed
            # the moment capture handed off to the result widget. Without
            # this the row sits as "Processing..." and React keeps polling
            # an ID that will never be persisted, producing the 404 storm
            # observed in the logs.
            if agent_task_id:
                try:
                    failure_event = {
                        "event_type": "agent_task_provisional_failed",
                        "agent_task_id": agent_task_id,
                        "reason": "no_speech",
                        "message": "No speech detected in audio recording.",
                    }
                    if root_task_id:
                        failure_event["root_task_id"] = root_task_id
                    if previous_task_id:
                        failure_event["previous_task_id"] = previous_task_id
                    await service.broadcast(failure_event)
                except Exception as broadcast_exc:
                    logger.warning(
                        f"[AGENT_TASK_AUDIO] Failed to broadcast provisional-failure for "
                        f"{agent_task_id}: {broadcast_exc}"
                    )
            # No task will be persisted; release transcription lifecycle so
            # the gate can become idle and wake detection can resume.
            _release_transcription_lifecycle("no_speech_detected")
            _clear_agent_task_capture_state("no_speech_detected")
            return AgentTaskAudioResponse(
                success=False,
                message="No speech detected in audio recording. Please try again.",
                transcription="",
                processed=False
            )
        
        logger.info(f"[AGENT_TASK_AUDIO] Transcription successful: '{transcribed_text.strip()}'")
        
        # Broadcast transcription immediately so the frontend shows the user's
        # agent task text before the slow OCR / routing pipeline begins.
        if agent_task_id:
            try:
                early_msg = {
                    "event_type": "agent_task_progress",
                    "agent_task_id": agent_task_id,
                    "step": "Analyzing request",
                    "status": "started",
                    "details": transcribed_text.strip()
                }
                if root_task_id:
                    early_msg["root_task_id"] = root_task_id
                if previous_task_id:
                    early_msg["previous_task_id"] = previous_task_id
                await service.broadcast(early_msg)

                context_msg = {
                    "event_type": "agent_task_progress",
                    "agent_task_id": agent_task_id,
                    "step": "Reading screen context",
                    "status": "started",
                }
                if root_task_id:
                    context_msg["root_task_id"] = root_task_id
                if previous_task_id:
                    context_msg["previous_task_id"] = previous_task_id
                await service.broadcast(context_msg)
                logger.info(f"[AGENT_TASK_AUDIO] Early progress broadcasts sent for agent task {agent_task_id}")
            except Exception as e:
                logger.warning(f"[AGENT_TASK_AUDIO] Failed to send early progress broadcast: {e}")

        # The capture/transcription gate should end once the frontend has the
        # transcribed task text. OCR, routing, and agent execution must not
        # prevent the next capture from starting.
        _release_transcription_lifecycle("transcription_broadcasted")
        _clear_agent_task_capture_state("transcription_broadcasted")
        
        # Log if this is a follow-up agent task in a chain
        if root_task_id:
            logger.info(f"[AGENT_TASK_AUDIO] 🔗 Processing as follow-up task (root: {root_task_id}, previous: {previous_task_id})")
        
        # Process the transcribed text through the agent-task pipeline
        logger.info(f"[AGENT_TASK_AUDIO] Processing transcribed text through agent-task pipeline...")
        
        # Check if we have pre-captured screenshot data from wake word detection
        screenshot_data = service.get_current_screenshot_data()
        if screenshot_data and screenshot_data.get('success'):
            logger.info(f"📸 [AGENT_TASK_AUDIO] Using pre-captured screenshot from wake word detection (app: {screenshot_data.get('app_name', 'Unknown')})")
        else:
            logger.info(f"📸 [AGENT_TASK_AUDIO] No pre-captured screenshot available, will capture during processing")
        
        # Parse reference_paths JSON if provided
        parsed_reference_paths: Optional[List[str]] = None
        if reference_paths:
            try:
                parsed_reference_paths = json.loads(reference_paths)
                logger.info(f"[AGENT_TASK_AUDIO] 📂 Parsed {len(parsed_reference_paths)} reference paths")
            except json.JSONDecodeError as e:
                logger.warning(f"[AGENT_TASK_AUDIO] Failed to parse reference_paths JSON: {e}")
        
        # Use the existing agent-task processing pipeline
        # This is the same path that the original FFmpeg-based capture would take
        # Log if frontend provided a pre-generated agent_task_id
        if agent_task_id:
            logger.info(f"[AGENT_TASK_AUDIO] 🆔 Using frontend-provided agent_task_id: {agent_task_id}")
        
        result = await service.process_agent_task_direct(
            agent_task=transcribed_text.strip(),
            clarification_agent_task=None,  # No clarification for initial processing
            agent_task_id=agent_task_id,  # Use frontend-provided ID or let service generate one
            root_task_id=root_task_id,
            previous_task_id=previous_task_id,
            reference_paths=parsed_reference_paths,  # Pass dropped file/folder paths for context
            model_id=model_id
        )
        
        logger.info(f"[AGENT_TASK_AUDIO] Agent-task processing completed: {result.get('success', False)}")
        
        # Safety release in case the early frontend handoff path was skipped.
        _release_transcription_lifecycle("agent_task_processing_returned")

        # Capture state cleanup is idempotent and may already have run after
        # the frontend transcription broadcast.
        _clear_agent_task_capture_state("agent_task_processing_returned")
        
        return AgentTaskAudioResponse(
            success=True,
            message="Agent task processed successfully via file-based transcription",
            transcription=transcribed_text.strip(),
            processing_result=result,
            processed=True,
            method="swift_audio_capture_service"
        )
        
    except HTTPException:
        # FastAPI 4xx/5xx response: release the transcription lifecycle so
        # the gate can recover. Re-raise to let FastAPI return the response.
        _release_transcription_lifecycle("http_exception")
        raise
    except Exception as e:
        logger.error(f"[AGENT_TASK_AUDIO] Error processing agent-task audio: {e}", exc_info=True)
        _release_transcription_lifecycle("unhandled_exception")
        raise HTTPException(
            status_code=500,
            detail=f"Error processing agent-task audio: {str(e)}"
        )

@router.post("/{root_task_id}/refine-audio", response_model=AgentTaskRefinementResponse)
async def refine_agent_task_audio(
    root_task_id: str,
    audio_file: UploadFile = File(..., description="Audio recording containing refinement agent tasks"),
    app_name: Optional[str] = Form(None, description="Current active application"),
    window_title: Optional[str] = Form(None, description="Current window title"),
    screen_text: Optional[str] = Form(None, description="Current screen context"),
    service: AgentTaskSubmissionService = Depends(get_agent_task_submission_service)
) -> AgentTaskRefinementResponse:
    """
    Refine a previous agent_task by processing new audio agent tasks.
    
    This endpoint enables iterative agent-task refinement by:
    1. Transcribing the refinement audio agent task
    2. Retrieving the original agent-task context and parameters
    3. Using LLM analysis to determine parameter modifications
    4. Re-executing the workflow with refined parameters
    5. Tracking refinement relationships in clarifications
    
    Args:
        root_task_id: ID of the root task to refine
        audio_file: WAV audio file containing refinement agent task
        app_name: Current active application (optional)
        window_title: Current window title (optional)
        screen_text: Current screen context (optional)
        service: Voice listener service dependency
        
    Returns:
        AgentTaskRefinementResponse: Refinement processing result with success status and execution data
        
    Raises:
        HTTPException: If refinement processing fails
    """
    try:
        logger.info(f"[AGENT_TASK_REFINEMENT] Processing refinement for task {root_task_id}")
        
        # Import refinement service here to avoid circular imports
        from api.services.agent_processing.lifecycle.submission.agent_task_processing import AgentTaskRefinementService
        
        # Resolve the correct transcription service based on current preferences
        transcription_service = resolve_transcription_service()
        
        # Read and validate audio file
        if not audio_file.filename.lower().endswith(('.wav', '.mp3', '.m4a')):
            raise HTTPException(
                status_code=400,
                detail="Audio file must be in WAV, MP3, or M4A format"
            )
        
        # Read audio data
        audio_data = await audio_file.read()
        if len(audio_data) == 0:
            raise HTTPException(status_code=400, detail="Audio file is empty")
        
        logger.info(f"[AGENT_TASK_REFINEMENT] Processing audio file: {audio_file.filename} ({len(audio_data)} bytes)")
        
        # Transcribe refinement agent task
        context_info = {
            "source": "agent_task_refinement",
            "app_name": app_name,
            "window_title": window_title
        }
        loop = asyncio.get_running_loop()

        def _log_parakeet_progress(progress: ParakeetTranscriptionProgress) -> None:
            loop.call_soon_threadsafe(
                lambda: logger.info(
                    "[AGENT_TASK_REFINEMENT] Parakeet progress: %s",
                    progress.to_payload(),
                )
            )

        context_info[PARAKEET_PROGRESS_CALLBACK_CONTEXT_KEY] = _log_parakeet_progress
        
        refinement_text = await transcription_service.transcribe(
            audio_data,
            context_info=context_info
        )
        
        if not refinement_text or not refinement_text.strip():
            logger.warning("[AGENT_TASK_REFINEMENT] No transcription result - audio may be empty or unclear")
            # Return minimal response for error case - use placeholder values for required fields
            return AgentTaskRefinementResponse(
                success=False,
                message="No speech detected in refinement audio. Please try again.",
                transcription="",
                refinement_agent_task_id="",
                root_task_id=root_task_id,
                execution_result=ExecutionResultSummary(
                    success=False,
                    todos_completed=0,
                    workflow_summary="No audio detected"
                ),
                processed=False,
                refinement_iteration=0
            )
        
        logger.info(f"[AGENT_TASK_REFINEMENT] Transcription successful: '{refinement_text.strip()}'")
        
        # Initialize refinement service
        refinement_service = AgentTaskRefinementService(
            agent_task_service=service.agent_task_orchestrator.db_service,
            llm_service=service.agent_task_orchestrator.llm_service,
        )
        
        # Process refinement request
        refinement_result = await refinement_service.process_refinement_request(
            root_task_id=root_task_id,
            refinement_request=refinement_text.strip(),
            app_name=app_name,
            window_title=window_title,
            screen_text=screen_text
        )
        
        # Generate new agent task ID for the refinement
        refinement_agent_task_id = str(uuid.uuid4())
        
        # Create clarification entry linking refinement to parent
        await refinement_service.create_refinement_clarification(
            root_task_id=root_task_id,
            refinement_agent_task_id=refinement_agent_task_id,
            refinement_request=refinement_text.strip(),
            execution_status="processing"
        )
        
        # Execute the refined workflow
        refined_context = refinement_result["execution_context"]
        refined_context["websocket_manager"] = service
        refined_context["available_services"] = getattr(service.agent_task_orchestrator, "basil_services", {})
        
        # Use the workflow coordinator to execute the refined agent task
        from api.services.agent_processing.lifecycle.runtime.workflow_coordinator import WorkflowCoordinator
        
        workflow_coordinator = WorkflowCoordinator(websocket_manager=service)
        
        # Execute the refined workflow
        execution_result = await workflow_coordinator.execute_complete_workflow(
            user_agent_task=f"Refinement: {refinement_text.strip()}",
            context=refined_context,
            agent_task_id=refinement_agent_task_id,
            use_tools_execution=True  # Use enhanced tool-based execution
        )
        
        # Store the refinement agent task in database (initial record)
        await service.agent_task_orchestrator.db_service.store_agent_task(
            agent_task_id=refinement_agent_task_id,
            original_prompt=f"Refinement: {refinement_text.strip()}",
            transcribed_prompt=f"Refinement: {refinement_text.strip()}",
            app_name=app_name or refinement_result["original_prompt"].app_name,
            window_title=window_title or refinement_result["original_prompt"].window_title,
            screen_text=screen_text or refinement_result["original_prompt"].screen_text,
            screen_capture_path=None,
            confidence_score=1.0,  # High confidence for refinements
            status="completed" if execution_result.success else "failed"
        )
        
        # Update with operation parameters and result data
        await service.agent_task_orchestrator.db_service.update_agent_task_status(
            agent_task_id=refinement_agent_task_id,
            status="completed" if execution_result.success else "failed",
            operation_parameters=refinement_result["refined_operation_params"],
            result_data={
                "success": execution_result.success,
                "operation_type": "agent_task_refinement",
                "data": {
                    "workflow_result": str(execution_result),
                    "root_task_id": root_task_id,
                    "refinement_metadata": refinement_result["refinement_metadata"]
                }
            }
        )
        
        # Update refinement clarification with completion status
        await refinement_service.create_refinement_clarification(
            root_task_id=root_task_id,
            refinement_agent_task_id=refinement_agent_task_id,
            refinement_request=refinement_text.strip(),
            execution_status="completed" if execution_result.success else "failed"
        )
        
        logger.info(f"[AGENT_TASK_REFINEMENT] Refinement processing completed: {execution_result.success}")
        
        return AgentTaskRefinementResponse(
            success=True,
            message="Agent task refinement processed successfully",
            transcription=refinement_text.strip(),
            refinement_agent_task_id=refinement_agent_task_id,
            root_task_id=root_task_id,
            execution_result=ExecutionResultSummary(
                success=execution_result.success,
                todos_completed=len(execution_result.execution_results) if execution_result.execution_results else 0,
                workflow_summary=execution_result.original_prompt
            ),
            processed=True,
            refinement_iteration=refinement_result["refinement_metadata"]["refinement_iteration"]
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[AGENT_TASK_REFINEMENT] Error processing refinement: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Error processing agent-task refinement: {str(e)}"
        )

