"""Meeting analysis routes."""

import json
import logging
from datetime import datetime
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

from api.services.meetings.meeting_recorder import MeetingRecorder

from .models import MeetingAnalysisConfig, ProposalOutcomeUpdate
from .state import active_analysis


logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/{meeting_id}/analyze")
async def start_meeting_analysis(meeting_id: str, config: MeetingAnalysisConfig) -> Dict[str, str]:
    """
    Start AI-powered analysis of a meeting recording.
    
    Args:
        meeting_id: Meeting UUID
        config: Analysis configuration (modes, model, custom instructions)
        
    Returns:
        WebSocket URL for progress updates
    """
    try:
        # Verify meeting exists and has transcript
        meeting_dir = MeetingRecorder.get_meeting_directory(meeting_id)
        transcript_path = meeting_dir / "transcript.json"
        
        if not transcript_path.exists():
            raise HTTPException(
                status_code=404,
                detail=f"Transcript not found for meeting {meeting_id}. Run post-processing first."
            )
        
        # Validate analysis modes
        if not config.analysis_modes:
            raise HTTPException(
                status_code=400,
                detail="At least one analysis mode must be selected"
            )
        
        # Check if already analyzing
        if meeting_id in active_analysis:
            raise HTTPException(
                status_code=409,
                detail=f"Meeting {meeting_id} is already being analyzed"
            )
        
        # Create analysis entry
        active_analysis[meeting_id] = {
            "model_id": config.model_id,
            "modes": config.analysis_modes,
            "custom_instructions": config.custom_instructions,
            "status": "queued",
            "progress": 0.0,
            "started_at": datetime.utcnow().isoformat() + "Z"
        }
        
        logger.info(
            f"Queued analysis for meeting {meeting_id}: "
            f"modes={config.analysis_modes}, model={config.model_id or 'default'}"
        )
        
        # Return WebSocket URL for progress updates
        from api.main import app
        ws_port = app.state.port if hasattr(app.state, 'port') else 8000
        ws_url = f"ws://localhost:{ws_port}/meetings/{meeting_id}/analyze/status"
        
        return {
            "status": "queued",
            "websocket_url": ws_url
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error starting analysis for meeting {meeting_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.websocket("/{meeting_id}/analyze/status")
async def meeting_analysis_status(websocket: WebSocket, meeting_id: str):
    """
    WebSocket endpoint for streaming meeting analysis progress.
    
    Args:
        websocket: WebSocket connection
        meeting_id: Meeting UUID
    """
    await websocket.accept()
    
    try:
        # Verify meeting exists and has transcript
        meeting_dir = MeetingRecorder.get_meeting_directory(meeting_id)
        transcript_path = meeting_dir / "transcript.json"
        
        if not transcript_path.exists():
            await websocket.send_json({
                "type": "error",
                "message": f"Transcript not found for meeting {meeting_id}"
            })
            await websocket.close()
            return
        
        # Check if analysis was requested
        if meeting_id not in active_analysis:
            await websocket.send_json({
                "type": "error",
                "message": f"No analysis job found for meeting {meeting_id}"
            })
            await websocket.close()
            return
        
        # Import analysis module
        from api.services.whisper_live_core.post_processing.meeting_analyzer import MeetingAnalyzer
        
        # Get job config
        job_config = active_analysis[meeting_id]
        model_id = job_config["model_id"]
        modes = job_config["modes"]
        custom_instructions = job_config.get("custom_instructions")
        
        # Create analyzer
        analyzer = MeetingAnalyzer(meeting_id, model_id)
        
        # Update status to processing
        active_analysis[meeting_id]["status"] = "processing"
        
        # Start analysis with progress callback
        async def progress_callback(progress_data: Dict[str, Any]):
            """Send progress updates via WebSocket."""
            try:
                # Update active job progress
                active_analysis[meeting_id]["progress"] = progress_data.get("overall_progress", 0.0)
                
                # Send to client
                await websocket.send_json({
                    "type": "progress",
                    **progress_data
                })
            except Exception as e:
                logger.error(f"Error sending analysis progress update: {e}")
        
        # Run analysis
        try:
            result = await analyzer.analyze(
                modes=modes,
                custom_instructions=custom_instructions,
                progress_callback=progress_callback
            )
            
            # Send completion message with full results. Include the saved
            # analysis filename so the client can persist per-proposal outcomes
            # against the same file it will later reopen from history.
            await websocket.send_json({
                "type": "complete",
                "overall_progress": 1.0,
                "analysis": result.to_dict(),
                "filename": analyzer.saved_analysis_filename
            })
            
            logger.info(f"Analysis completed for meeting {meeting_id}")
            
        except Exception as e:
            logger.error(f"Error during analysis: {e}", exc_info=True)
            await websocket.send_json({
                "type": "error",
                "message": str(e)
            })
        finally:
            # Clean up active job
            if meeting_id in active_analysis:
                del active_analysis[meeting_id]
    
    except WebSocketDisconnect:
        logger.info(f"Client disconnected from analysis status for meeting {meeting_id}")
        # Clean up active job
        if meeting_id in active_analysis:
            del active_analysis[meeting_id]
    except Exception as e:
        logger.error(f"Error in analysis WebSocket: {e}", exc_info=True)
        try:
            await websocket.send_json({
                "type": "error",
                "message": str(e)
            })
        except:
            pass
        # Clean up active job
        if meeting_id in active_analysis:
            del active_analysis[meeting_id]


@router.get("/{meeting_id}/analyses")
async def list_meeting_analyses(meeting_id: str) -> List[Dict[str, Any]]:
    """
    Get list of all analyses for a meeting.
    
    Args:
        meeting_id: Meeting UUID
        
    Returns:
        List of analysis metadata entries
    """
    try:
        metadata = MeetingRecorder.load_metadata(meeting_id)
        if not metadata:
            raise HTTPException(status_code=404, detail=f"Meeting {meeting_id} not found")
        
        return metadata.analyses or []
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing analyses for meeting {meeting_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{meeting_id}/analyses/{filename}")
async def get_meeting_analysis(meeting_id: str, filename: str) -> Dict[str, Any]:
    """
    Get a specific analysis by filename.
    
    Args:
        meeting_id: Meeting UUID
        filename: Analysis filename (e.g., analysis_20241226_123045.json)
        
    Returns:
        Analysis data
    """
    try:
        meeting_dir = MeetingRecorder.get_meeting_directory(meeting_id)
        analysis_path = meeting_dir / filename
        
        if not analysis_path.exists():
            raise HTTPException(status_code=404, detail=f"Analysis {filename} not found for meeting {meeting_id}")
        
        with open(analysis_path, 'r') as f:
            return json.load(f)
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting analysis {filename} for meeting {meeting_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{meeting_id}/analyses/{filename}")
async def delete_meeting_analysis(meeting_id: str, filename: str) -> Dict[str, str]:
    """
    Delete a specific analysis.
    
    Args:
        meeting_id: Meeting UUID
        filename: Analysis filename to delete
        
    Returns:
        Success message
    """
    try:
        meeting_dir = MeetingRecorder.get_meeting_directory(meeting_id)
        analysis_path = meeting_dir / filename
        
        # Delete file if it exists
        if analysis_path.exists():
            analysis_path.unlink()
            logger.info(f"Deleted analysis file: {analysis_path}")
        
        # Update metadata to remove the entry
        metadata = MeetingRecorder.load_metadata(meeting_id)
        if metadata and metadata.analyses:
            original_count = len(metadata.analyses)
            metadata.analyses = [a for a in metadata.analyses if a["filename"] != filename]
            
            # Save updated metadata
            metadata_path = meeting_dir / "metadata.json"
            with open(metadata_path, 'w') as f:
                json.dump(metadata.to_dict(), f, indent=2)
            
            logger.info(f"Removed analysis entry from metadata (removed {original_count - len(metadata.analyses)} entries)")
        
        return {"status": "deleted", "filename": filename}
        
    except Exception as e:
        logger.error(f"Error deleting analysis {filename} for meeting {meeting_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{meeting_id}/analyses/{filename}/proposals/{proposal_id}")
async def update_meeting_analysis_proposal(
    meeting_id: str,
    filename: str,
    proposal_id: str,
    update: ProposalOutcomeUpdate,
) -> Dict[str, Any]:
    """
    Persist a single suggested-action proposal's outcome to its analysis file.

    Args:
        meeting_id: Meeting UUID
        filename: Analysis filename (analysis_YYYYMMDD_HHMMSS.json)
        proposal_id: Stable backend id of the proposal
        update: New execution status and (optional) delegated agent task id

    Returns:
        The updated proposal dict
    """
    from .analysis_proposal_store import update_proposal_outcome

    try:
        return update_proposal_outcome(
            meeting_id,
            filename,
            proposal_id,
            update.execution_status,
            update.submitted_agent_task_id,
            update.todo_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(
            f"Error updating proposal {proposal_id} in {filename} for meeting {meeting_id}: {e}",
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail=str(e))
