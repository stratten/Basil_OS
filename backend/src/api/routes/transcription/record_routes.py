"""Record-specific transcription endpoints."""

import logging
import os
import asyncio
from pathlib import Path
from typing import Optional

import Levenshtein
from fastapi import APIRouter, Body, HTTPException, Query
from fastapi.responses import FileResponse

from api.services.transcription.backends.parakeet_components import (
    PARAKEET_PROGRESS_CALLBACK_CONTEXT_KEY,
    ParakeetTranscriptionProgress,
)
from api.services.transcription.processing.transcription_model_override import (
    InvalidTranscriptionModelOverride,
    resolve_retranscription_transcription_service,
)
from api.services.websocket_events import send_transcription_status

from .dependencies import transcription_repository
from .models import (
    RetranscribeRequest,
    RetranscribeResponse,
    TranscriptionDeleteResponse,
    TranscriptionFeedbackResponse,
    TranscriptionUpdateResponse,
)


logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/transcription/feedback/{transcription_id}", response_model=TranscriptionFeedbackResponse)
async def add_transcription_feedback(
    transcription_id: str,
    rating: Optional[int] = Query(None, ge=1, le=5),
    feedback: Optional[str] = Query(None),
    action_taken: Optional[str] = Query(None)
) -> TranscriptionFeedbackResponse:
    """
    Add user feedback for a transcription.
    
    Args:
        transcription_id: ID of the transcription
        rating: User rating (1-5)
        feedback: User feedback text
        action_taken: What action the user took with the transcription
        
    Returns:
        Success status
    """
    try:
        # Get the transcription
        transcription = await transcription_repository.get_transcription(transcription_id)
        if not transcription:
            return TranscriptionFeedbackResponse(
                success=False,
                error=f"Transcription with ID {transcription_id} not found"
            )
        
        # Update the feedback fields
        if rating is not None:
            transcription.user_rating = rating
        if feedback is not None:
            transcription.user_feedback = feedback
        if action_taken is not None:
            transcription.action_taken = action_taken
        
        # Save the updated transcription
        await transcription_repository.save_transcription(transcription)
        
        return TranscriptionFeedbackResponse(
            success=True,
            message="Feedback saved successfully"
        )
    except Exception as e:
        logger.error(f"Error adding transcription feedback: {e}")
        return TranscriptionFeedbackResponse(
            success=False,
            error=str(e)
        )


@router.post("/transcription/update/{transcription_id}", response_model=TranscriptionUpdateResponse)
async def update_transcription_text(
    transcription_id: str,
    edited_text: str = Body(...),
    original_text: Optional[str] = Body(None)
) -> TranscriptionUpdateResponse:
    """
    Update a transcription with user-edited text.
    
    Args:
        transcription_id: ID of the transcription to update
        edited_text: The edited text provided by the user
        original_text: The original text (for calculating edit distance)
        
    Returns:
        Success status and updated transcription
    """
    try:
        # Get the transcription
        transcription = await transcription_repository.get_transcription(transcription_id)
        if not transcription:
            return TranscriptionUpdateResponse(
                success=False,
                error=f"Transcription with ID {transcription_id} not found"
            )
        
        # Calculate edit distance if original text is provided
        edit_distance = None
        if original_text:
            edit_distance = Levenshtein.distance(original_text, edited_text)
        elif transcription.transcription_text:
            edit_distance = Levenshtein.distance(transcription.transcription_text, edited_text)
        
        # Update the transcription
        transcription.edited_text = edited_text
        transcription.was_edited = True
        transcription.edit_distance = edit_distance
        
        # Save the updated transcription
        await transcription_repository.save_transcription(transcription)
        
        return TranscriptionUpdateResponse(
            success=True,
            message="Transcription updated successfully",
            transcription=transcription.to_dict()
        )
    except Exception as e:
        logger.error(f"Error updating transcription: {e}")
        return TranscriptionUpdateResponse(
            success=False,
            error=str(e)
        )


@router.get("/transcription/audio/{transcription_id}", response_class=FileResponse)
async def get_audio_file(transcription_id: str) -> FileResponse:
    """
    Get the audio file for a transcription.
    
    Args:
        transcription_id: ID of the transcription
        
    Returns:
        The audio file as a streaming response
    """
    try:
        # Get the transcription
        transcription = await transcription_repository.get_transcription(transcription_id)
        if not transcription:
            raise HTTPException(
                status_code=404,
                detail=f"Transcription with ID {transcription_id} not found"
            )
        
        # Check if the audio file exists
        audio_path = Path(transcription.audio_file_path)
        if not audio_path.exists():
            raise HTTPException(
                status_code=404,
                detail=f"Audio file not found at {audio_path}"
            )
        
        # Return the audio file
        return FileResponse(
            path=audio_path,
            media_type="audio/wav",
            filename=f"transcription_{transcription_id}.wav"
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving audio file: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Error retrieving audio file: {str(e)}"
        )


@router.delete("/transcription/{transcription_id}", response_model=TranscriptionDeleteResponse)
async def delete_transcription(transcription_id: str) -> TranscriptionDeleteResponse:
    """
    Delete a transcription and its associated audio file.
    
    Args:
        transcription_id: ID of the transcription to delete
        
    Returns:
        Success status
    """
    try:
        # Get the transcription to find the audio file path
        transcription = await transcription_repository.get_transcription(transcription_id)
        if not transcription:
            return TranscriptionDeleteResponse(
                success=False,
                error=f"Transcription with ID {transcription_id} not found"
            )
        
        # Delete the audio file if it exists
        audio_path = Path(transcription.audio_file_path)
        if audio_path.exists():
            try:
                os.remove(audio_path)
                logger.info(f"Deleted audio file: {audio_path}")
            except Exception as e:
                logger.warning(f"Failed to delete audio file {audio_path}: {e}")
                # Continue with database deletion even if file deletion fails
        
        # Delete the transcription from the database
        deleted = await transcription_repository.delete_transcription(transcription_id)
        
        if deleted:
            return TranscriptionDeleteResponse(
                success=True,
                message=f"Transcription {transcription_id} deleted successfully"
            )
        else:
            return TranscriptionDeleteResponse(
                success=False,
                error="Failed to delete transcription from database"
            )
            
    except Exception as e:
        logger.error(f"Error deleting transcription {transcription_id}: {e}")
        return TranscriptionDeleteResponse(
            success=False,
            error=str(e)
        )


@router.post("/transcription/{transcription_id}/retranscribe", response_model=RetranscribeResponse)
async def retranscribe(
    transcription_id: str,
    request: Optional[RetranscribeRequest] = None,
) -> RetranscribeResponse:
    """
    Re-transcribe an existing audio file with the selected model.

    Persistence is delegated to the transcription service's lifecycle
    helper, which flips the existing row through pending -> completed
    (or pending -> failed on error) and updates transcription_text,
    model_name, timestamp, and processing_time_ms accordingly. This
    route only:

      * validates that the row and its audio file still exist,
      * kicks off the transcribe call with the retranscription context,
      * clears prior edit-tracking columns so the stale edited_text
        doesn't linger next to a fresh transcription.

    Args:
        transcription_id: ID of the transcription to re-process.

    Returns:
        The new transcription text.
    """
    try:
        transcription = await transcription_repository.get_transcription(transcription_id)
        if not transcription:
            return RetranscribeResponse(
                success=False,
                error=f"Transcription with ID {transcription_id} not found",
            )

        audio_path = Path(transcription.audio_file_path)
        if not audio_path.exists():
            return RetranscribeResponse(
                success=False,
                error="Audio file not found. Cannot retranscribe.",
            )

        model_override_id = request.model_id if request else None
        try:
            transcription_service = resolve_retranscription_transcription_service(
                model_override_id
            )
        except InvalidTranscriptionModelOverride as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        logger.info("Loading transcription model for retranscription...")
        transcription_service.load_model()
        if not transcription_service.is_model_loaded():
            raise ValueError("Transcription model failed to load for retranscription.")

        context_info = {
            "source": "retranscription",
            "existing_audio_path": str(audio_path),
            "transcription_id": transcription_id,
            "app_name": transcription.app_name,
            "window_title": transcription.window_title,
            "task_category": transcription.task_category,
            "language": transcription.language,
        }

        logger.info(f"Retranscribing {transcription_id} from {audio_path}")
        await send_transcription_status("started")
        loop = asyncio.get_running_loop()

        def _broadcast_parakeet_progress(progress: ParakeetTranscriptionProgress) -> None:
            loop.call_soon_threadsafe(
                lambda: asyncio.create_task(
                    send_transcription_status(
                        "transcription_progress",
                        progress.to_payload(),
                    )
                )
            )

        context_info[PARAKEET_PROGRESS_CALLBACK_CONTEXT_KEY] = _broadcast_parakeet_progress

        new_text = await transcription_service.transcribe(b"", context_info)

        await send_transcription_status("completed", new_text)
        await transcription_repository.reset_edit_tracking(transcription_id)

        logger.info(f"Retranscription complete for {transcription_id}")

        return RetranscribeResponse(
            success=True,
            text=new_text,
            message="Retranscription completed successfully",
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retranscribing {transcription_id}: {e}")
        return RetranscribeResponse(
            success=False,
            error=str(e),
        )
