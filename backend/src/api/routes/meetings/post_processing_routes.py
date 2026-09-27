"""Meeting post-processing routes."""

import json
import logging
from datetime import datetime
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

from api.services.meetings.meeting_recorder import MeetingRecorder
from api.services.whisper_live_core.post_processing.meeting_transcript_upgrade_ledger import (
    finalize_recorded_window_upgrades,
    record_window_upgrade,
)
from api.services.whisper_live_core.post_processing.transcript_merger import (
    validate_audio_file_for_post_processing,
)

from .models import PostProcessingConfig, RetranscribeWindowConfig
from .state import active_post_processing


logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/{meeting_id}/retranscribe-window")
async def retranscribe_window(meeting_id: str, config: RetranscribeWindowConfig) -> Dict[str, Any]:
    """Re-transcribe a closed ``[start, end)`` window of a meeting's audio.

    Returns absolute-timeline segments for the window. Intended for incremental,
    mid-recording upgrades: it reads the still-growing ``audio.wav`` directly
    (``config.live``). The client splices the returned segments into the live
    transcript immediately, while the backend records the successful range in a
    durable sidecar ledger for replay after recording stops. The finalized-file
    guard (``validate_audio_file_for_post_processing``) is deliberately skipped
    because the file is expected to be mid-recording.
    """
    from api.services.whisper_live_core.post_processing.windowed_retranscription import (
        transcribe_window,
    )

    meeting_dir = MeetingRecorder.get_meeting_directory(meeting_id)
    audio_path = meeting_dir / "audio.wav"
    if not audio_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Audio file not found for meeting {meeting_id}",
        )

    if config.end_seconds <= config.start_seconds:
        raise HTTPException(
            status_code=422,
            detail="end_seconds must be greater than start_seconds",
        )

    try:
        segments = await transcribe_window(
            meeting_id,
            config.start_seconds,
            config.end_seconds,
            config.model,
            audio_path=audio_path,
            live=config.live,
        )
        record_window_upgrade(
            meeting_dir,
            config.start_seconds,
            config.end_seconds,
            segments,
        )
    except Exception as e:
        logger.error(
            "Error re-transcribing window for meeting %s [%.2f, %.2f): %s",
            meeting_id, config.start_seconds, config.end_seconds, e, exc_info=True,
        )
        raise HTTPException(status_code=500, detail=str(e))

    return {
        "meeting_id": meeting_id,
        "start_seconds": config.start_seconds,
        "end_seconds": config.end_seconds,
        "segments": segments,
    }


@router.post("/{meeting_id}/complete-windowed-retranscription")
async def complete_windowed_retranscription(meeting_id: str) -> Dict[str, str]:
    """Persist successful on-stop completion of iterative retranscription.

    Individual live windows are intentionally not enough to mark a meeting as
    post-processed: recording may continue and later audio can remain unupgraded.
    The client calls this only after its final on-stop window for this track
    succeeds. Requiring ``end_time`` prevents an in-recording cadence request
    from being reported as complete.
    """
    meeting_dir = MeetingRecorder.get_meeting_directory(meeting_id)
    metadata = MeetingRecorder.load_metadata(meeting_id)
    if metadata is None:
        raise HTTPException(status_code=404, detail=f"Meeting not found: {meeting_id}")
    if metadata.end_time is None:
        raise HTTPException(
            status_code=409,
            detail="Cannot complete iterative retranscription while recording is active",
        )

    finalize_recorded_window_upgrades(meeting_id)
    metadata.is_post_processed = True
    metadata_path = meeting_dir / "metadata.json"
    with open(metadata_path, "w") as f:
        json.dump(metadata.to_dict(), f, indent=2)

    from api.services.meetings import meeting_search_indexer
    meeting_search_indexer.reindex(meeting_id)

    return {"meeting_id": meeting_id, "status": "complete"}


@router.post("/{meeting_id}/post-process")
async def start_post_processing(meeting_id: str, config: PostProcessingConfig) -> Dict[str, str]:
    """
    Start post-processing a meeting recording.
    
    Args:
        meeting_id: Meeting UUID
        config: Post-processing configuration
        
    Returns:
        WebSocket URL for progress updates
    """
    try:
        # Verify meeting exists
        meeting_dir = MeetingRecorder.get_meeting_directory(meeting_id)
        audio_path = meeting_dir / "audio.wav"
        
        if not audio_path.exists():
            raise HTTPException(
                status_code=404, 
                detail=f"Audio file not found for meeting {meeting_id}"
            )
        try:
            validate_audio_file_for_post_processing(audio_path)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        
        # Check if already processing. Completed/error/disconnected entries are
        # retained briefly for diagnostics and can be replaced by a new request.
        existing_job = active_post_processing.get(meeting_id)
        if existing_job and existing_job.get("status") in {"queued", "processing"}:
            raise HTTPException(
                status_code=409,
                detail=f"Meeting {meeting_id} is already being post-processed"
            )
        
        # Create post-processing entry
        active_post_processing[meeting_id] = {
            "model": config.model,
            "operation": config.operation,
            "status": "queued",
            "progress": 0.0,
            "last_progress": None,
            "last_error": None,
            "websocket_connected": False,
            "started_at": datetime.utcnow().isoformat() + "Z"
        }
        
        logger.info(f"Queued post-processing for meeting {meeting_id} with model {config.model}")
        
        # Return WebSocket URL for progress updates
        from api.main import app
        ws_port = app.state.port if hasattr(app.state, 'port') else 8000
        ws_url = f"ws://localhost:{ws_port}/meetings/{meeting_id}/post-process/status"
        
        return {
            "status": "queued",
            "websocket_url": ws_url
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error starting post-processing for meeting {meeting_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.websocket("/{meeting_id}/post-process/status")
async def post_processing_status(websocket: WebSocket, meeting_id: str):
    """
    WebSocket endpoint for streaming post-processing progress.
    
    Args:
        websocket: WebSocket connection
        meeting_id: Meeting UUID
    """
    await websocket.accept()
    
    try:
        # Verify meeting exists
        meeting_dir = MeetingRecorder.get_meeting_directory(meeting_id)
        audio_path = meeting_dir / "audio.wav"
        
        if not audio_path.exists():
            await websocket.send_json({
                "type": "error",
                "message": f"Audio file not found for meeting {meeting_id}"
            })
            await websocket.close()
            return
        try:
            validate_audio_file_for_post_processing(audio_path)
        except ValueError as exc:
            await websocket.send_json({
                "type": "error",
                "message": str(exc)
            })
            await websocket.close()
            return
        
        # Check if post-processing was requested
        if meeting_id not in active_post_processing:
            await websocket.send_json({
                "type": "error",
                "message": f"No post-processing job found for meeting {meeting_id}"
            })
            await websocket.close()
            return
        
        # Import post-processing module
        from api.services.whisper_live_core.post_processing.meeting_processor import MeetingProcessor
        
        # Get job config from active job
        model_name = active_post_processing[meeting_id]["model"]
        operation = active_post_processing[meeting_id].get("operation", "transcribe")
        
        # Create processor
        processor = MeetingProcessor(meeting_id, model_name)
        
        # Update status to processing
        active_post_processing[meeting_id]["status"] = "processing"
        active_post_processing[meeting_id]["websocket_connected"] = True
        
        # Start post-processing with progress callback
        async def progress_callback(progress_data: Dict[str, Any]):
            """Send progress updates via WebSocket."""
            payload = {
                "type": "progress",
                **progress_data
            }
            progress = progress_data.get("overall_progress", 0.0)
            stage = progress_data.get("stage", "")
            message = progress_data.get("message", "")

            active_post_processing[meeting_id].update({
                "progress": progress,
                "last_progress": payload,
                "last_progress_at": datetime.utcnow().isoformat() + "Z",
                "stage": stage,
                "message": message,
            })
            logger.info(
                "Post-processing progress for %s: stage=%s progress=%.3f message=%s",
                meeting_id,
                stage,
                progress,
                message,
            )

            try:
                # Send to client
                await websocket.send_json(payload)
            except Exception as e:
                active_post_processing[meeting_id]["websocket_connected"] = False
                active_post_processing[meeting_id]["last_send_error"] = str(e)
                logger.error(f"Error sending progress update: {e}", exc_info=True)
        
        # Run post-processing based on operation type
        try:
            if operation == "both":
                logger.info(f"Running full post-processing (transcription + diarization) for meeting {meeting_id}")
                result = await processor.process_both(progress_callback)
            elif operation == "transcribe":
                logger.info(f"Running transcription only for meeting {meeting_id}")
                result = await processor.transcribe_only(progress_callback)
            elif operation == "diarize":
                logger.info(f"Running diarization only for meeting {meeting_id}")
                result = await processor.diarize_only(progress_callback)
            else:
                raise ValueError(f"Unknown operation: {operation}")
            
            completion_payload = {
                "type": "complete",
                "overall_progress": 1.0,
                "transcript": result
            }
            active_post_processing[meeting_id].update({
                "status": "complete",
                "progress": 1.0,
                "last_progress": completion_payload,
                "completed_at": datetime.utcnow().isoformat() + "Z",
            })

            # Send completion message
            await websocket.send_json(completion_payload)

            # Update metadata to mark as post-processed
            metadata = MeetingRecorder.load_metadata(meeting_id)
            if metadata:
                metadata.is_post_processed = True
                metadata_path = meeting_dir / "metadata.json"
                with open(metadata_path, 'w') as f:
                    json.dump(metadata.to_dict(), f, indent=2)

            # Re-index the upgraded transcript so search reflects the diarized/
            # re-transcribed text. Best-effort; indexer swallows its own errors.
            from api.services.meetings import meeting_search_indexer
            meeting_search_indexer.reindex(meeting_id)
            
            logger.info(f"Post-processing completed for meeting {meeting_id}")
            
        except Exception as e:
            logger.error(f"Error during post-processing: {e}", exc_info=True)
            error_payload = {
                "type": "error",
                "message": str(e)
            }
            active_post_processing[meeting_id].update({
                "status": "error",
                "last_error": str(e),
                "last_progress": error_payload,
                "error_at": datetime.utcnow().isoformat() + "Z",
            })
            try:
                await websocket.send_json(error_payload)
            except Exception as send_error:
                active_post_processing[meeting_id]["websocket_connected"] = False
                active_post_processing[meeting_id]["last_send_error"] = str(send_error)
                logger.error(f"Error sending post-processing failure: {send_error}", exc_info=True)
        finally:
            # Clean up successful jobs. Error/disconnect state is retained so
            # subsequent diagnostics can see the last known progress.
            if active_post_processing.get(meeting_id, {}).get("status") == "complete":
                del active_post_processing[meeting_id]
        
    except WebSocketDisconnect:
        logger.info(f"Client disconnected from post-processing status for meeting {meeting_id}")
        if meeting_id in active_post_processing:
            active_post_processing[meeting_id].update({
                "status": "client_disconnected",
                "websocket_connected": False,
                "disconnected_at": datetime.utcnow().isoformat() + "Z",
            })
    except Exception as e:
        logger.error(f"Error in post-processing WebSocket: {e}", exc_info=True)
        try:
            await websocket.send_json({
                "type": "error",
                "message": str(e)
            })
        except:
            pass
        if meeting_id in active_post_processing:
            active_post_processing[meeting_id].update({
                "status": "websocket_error",
                "last_error": str(e),
                "websocket_connected": False,
                "error_at": datetime.utcnow().isoformat() + "Z",
            })
