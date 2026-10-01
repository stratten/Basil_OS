"""Meeting lifecycle and metadata routes."""

import json
import logging
import re
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException

from api.services.meetings.meeting_recorder import MeetingMetadata, MeetingRecorder
from api.services.meetings import meeting_recording_registry, meeting_search_indexer

from .meeting_grouping import (
    clean_meeting_name as _clean_meeting_name,
    group_meetings,
    load_all_raw_meetings,
)
from .models import MeetingInfo, MeetingMetadataUpdate, MeetingResponse


logger = logging.getLogger(__name__)
router = APIRouter()
_DISCARDABLE_MEETING_ID = re.compile(r"[A-Za-z0-9-]+")


def _meeting_name_for_source(base_name: str, audio_source: str | None) -> str:
    """Apply the per-source suffix used by live recording metadata."""
    cleaned_name = _clean_meeting_name({"name": base_name, "audio_source": audio_source})
    if audio_source:
        return f"{cleaned_name} - {audio_source}"
    return cleaned_name


def _save_meeting_metadata(metadata: MeetingMetadata) -> None:
    meeting_dir = MeetingRecorder.get_meeting_directory(metadata.id)
    metadata_path = meeting_dir / "metadata.json"
    with open(metadata_path, 'w') as f:
        json.dump(metadata.to_dict(), f, indent=2)


def _load_session_sibling_metadata(session_id: str, exclude_meeting_id: str) -> List[MeetingMetadata]:
    meetings_dir = Path.home() / ".basil" / "meetings"
    siblings: List[MeetingMetadata] = []
    if not meetings_dir.exists():
        return siblings

    for sibling_dir in meetings_dir.iterdir():
        if not sibling_dir.is_dir() or sibling_dir.name == exclude_meeting_id:
            continue
        sibling_metadata = MeetingRecorder.load_metadata(sibling_dir.name)
        if sibling_metadata and sibling_metadata.session_id == session_id:
            siblings.append(sibling_metadata)
    return siblings


@router.post("/start")
async def start_meeting(meeting_info: MeetingInfo) -> Dict[str, str]:
    """
    Create a new meeting record.
    
    This endpoint creates the meeting metadata and directory structure,
    but does not start audio recording. Audio recording is handled through
    the WebSocket connection with the meeting_id parameter.
    
    Args:
        meeting_info: Meeting name, purpose, and participants
        
    Returns:
        Dictionary containing meeting_id for use in WebSocket connection
    """
    try:
        meeting_id = str(uuid.uuid4())
        
        # Create meeting directory structure
        meeting_dir = MeetingRecorder.get_meeting_directory(meeting_id)
        meeting_dir.mkdir(parents=True, exist_ok=True)
        
        # Create initial metadata
        metadata = MeetingMetadata(
            id=meeting_id,
            name=meeting_info.name,
            purpose=meeting_info.purpose,
            participants=meeting_info.participants or [],
            start_time=datetime.utcnow().isoformat() + "Z",  # Add Z suffix to indicate UTC
            audio_path=str(meeting_dir / "audio.wav"),
            transcript_path=str(meeting_dir / "transcript.json"),
            is_post_processed=False
        )
        
        # Save metadata
        metadata_path = meeting_dir / "metadata.json"
        with open(metadata_path, 'w') as f:
            json.dump(metadata.to_dict(), f, indent=2)
        
        logger.info(f"Created meeting {meeting_id}: {meeting_info.name}")
        
        return {
            "meeting_id": meeting_id,
            "status": "created"
        }
        
    except Exception as e:
        logger.error(f"Error creating meeting: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{meeting_id}")
async def update_meeting_metadata(
    meeting_id: str,
    update: MeetingMetadataUpdate,
) -> Dict[str, Any]:
    """Update editable meeting metadata for a saved meeting."""
    try:
        base_name = update.name.strip()
        if not base_name:
            raise HTTPException(status_code=400, detail="Meeting name cannot be empty")

        metadata = MeetingRecorder.load_metadata(meeting_id)
        if not metadata:
            raise HTTPException(status_code=404, detail=f"Meeting {meeting_id} not found")

        participants = update.participants or []
        metadata_to_update = [metadata]
        if metadata.session_id:
            metadata_to_update.extend(
                _load_session_sibling_metadata(metadata.session_id, exclude_meeting_id=meeting_id)
            )

        for item in metadata_to_update:
            item.name = _meeting_name_for_source(base_name, item.audio_source)
            item.purpose = update.purpose
            item.participants = participants
            _save_meeting_metadata(item)
            meeting_search_indexer.reindex(item.id)

        logger.info(
            "Updated meeting metadata for %s (session members=%s): name=%s",
            meeting_id,
            len(metadata_to_update),
            base_name,
        )

        return {
            "status": "updated",
            "meeting": metadata.to_dict()
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating meeting metadata for {meeting_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{meeting_id}/stop")
async def stop_meeting(meeting_id: str) -> Dict[str, Any]:
    """
    Finalize a meeting recording.
    
    This endpoint updates the meeting metadata with end time and duration.
    The actual audio file closure is handled by the WebSocket disconnection.
    
    Args:
        meeting_id: Meeting UUID
        
    Returns:
        Meeting metadata including duration and file paths
    """
    try:
        # Load existing metadata
        metadata = MeetingRecorder.load_metadata(meeting_id)
        if not metadata:
            raise HTTPException(status_code=404, detail=f"Meeting {meeting_id} not found")
        
        # Update end time if not already set
        if not metadata.end_time:
            metadata.end_time = datetime.utcnow().isoformat() + "Z"  # Add Z suffix to indicate UTC
            
            # Calculate duration if we have both start and end times
            if metadata.start_time:
                start = datetime.fromisoformat(metadata.start_time)
                end = datetime.fromisoformat(metadata.end_time)
                metadata.duration_seconds = (end - start).total_seconds()
            
            # Save updated metadata
            meeting_dir = MeetingRecorder.get_meeting_directory(meeting_id)
            metadata_path = meeting_dir / "metadata.json"
            with open(metadata_path, 'w') as f:
                json.dump(metadata.to_dict(), f, indent=2)
        
        logger.info(f"Stopped meeting {meeting_id}: duration={metadata.duration_seconds:.1f}s")
        
        return {
            "status": "stopped",
            "meeting": metadata.to_dict()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error stopping meeting {meeting_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("")
async def list_meetings(limit: int = 50, offset: int = 0) -> List[MeetingResponse]:
    """
    List all meetings.
    
    Args:
        limit: Maximum number of meetings to return
        offset: Number of meetings to skip
        
    Returns:
        List of meeting metadata
    """
    try:
        meetings = group_meetings(load_all_raw_meetings())
        # Apply pagination (group_meetings already sorts newest-first).
        return meetings[offset:offset + limit]
        
    except Exception as e:
        logger.error(f"Error listing meetings: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{meeting_id}")
async def get_meeting(meeting_id: str) -> Dict[str, Any]:
    """
    Get meeting metadata and transcript.
    
    Args:
        meeting_id: Meeting UUID
        
    Returns:
        Meeting metadata and transcript data
    """
    try:
        # Load metadata
        metadata = MeetingRecorder.load_metadata(meeting_id)
        if not metadata:
            raise HTTPException(status_code=404, detail=f"Meeting {meeting_id} not found")
        
        # Load transcript
        transcript = MeetingRecorder.load_transcript(meeting_id)
        
        return {
            "metadata": metadata.to_dict(),
            "transcript": transcript
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting meeting {meeting_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{meeting_id}")
async def delete_meeting(meeting_id: str) -> Dict[str, str]:
    """
    Delete a meeting and all its files.
    
    Args:
        meeting_id: Meeting UUID
        
    Returns:
        Success message
    """
    try:
        meeting_dir = MeetingRecorder.get_meeting_directory(meeting_id)
        
        if not meeting_dir.exists():
            raise HTTPException(status_code=404, detail=f"Meeting {meeting_id} not found")
        
        # If this meeting is part of a session, cascade the delete to its siblings
        # (the mic + system-audio members) so the whole grouped meeting is removed.
        deleted_ids: List[str] = []
        metadata = MeetingRecorder.load_metadata(meeting_id)
        session_id = metadata.session_id if metadata else None
        if session_id:
            meetings_dir = Path.home() / ".basil" / "meetings"
            for sibling_dir in meetings_dir.iterdir():
                if not sibling_dir.is_dir() or sibling_dir.name == meeting_id:
                    continue
                sibling_metadata_path = sibling_dir / "metadata.json"
                if not sibling_metadata_path.exists():
                    continue
                try:
                    with open(sibling_metadata_path, 'r') as f:
                        sibling_metadata = json.load(f)
                    if sibling_metadata.get("session_id") == session_id:
                        shutil.rmtree(sibling_dir)
                        deleted_ids.append(sibling_dir.name)
                except Exception as e:
                    logger.warning(f"Failed to delete session sibling {sibling_dir.name}: {e}")
        
        # Delete the target meeting directory
        shutil.rmtree(meeting_dir)
        deleted_ids.append(meeting_id)

        # Drop every removed id from the transcript search index (cascade parity).
        for deleted_id in deleted_ids:
            meeting_search_indexer.remove(deleted_id)
        
        logger.info(f"Deleted meeting {meeting_id} (removed: {deleted_ids})")
        
        return {"status": "deleted", "meeting_id": meeting_id}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting meeting {meeting_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{meeting_id}/discard-recording")
async def discard_meeting_recording(meeting_id: str) -> Dict[str, str]:
    """Cancel a recording part: abandon its live recorder, delete its files, and refuse any reconnect for it."""
    if not _DISCARDABLE_MEETING_ID.fullmatch(meeting_id):
        raise HTTPException(status_code=400, detail="Invalid meeting id")
    found = meeting_recording_registry.discard(meeting_id, MeetingRecorder.get_meeting_directory(meeting_id))
    meeting_search_indexer.remove(meeting_id)
    return {"status": "discarded" if found else "not_found", "meeting_id": meeting_id}
