"""HTTP routes for mechanical meeting detection.

Holds the client->backend probe-response endpoint (resolves the audio-probe
Future) plus, later, the start/stop/status control endpoints. Kept separate
from ambient suggestions: no shared store, record, or capability list.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api.core.preferences.preferences_io import load_preferences
from api.services.meeting_detection.audio_activity_bridge import (
    deliver_audio_probe_response,
)
from api.services.meeting_detection.calendar_event_bridge import (
    deliver_calendar_probe_response,
)
from api.services.meeting_detection.runtime import get_meeting_detection_runtime

logger = logging.getLogger(__name__)

# Probe response endpoint lives under /audio-activity (mirrors /capture); the
# start/stop/status controls live under /meeting-detection (mirrors ambient).
router = APIRouter(tags=["meeting-detection"])


class ProbeResponseAck(BaseModel):
    """Acknowledgment for a delivered meeting-detection probe response."""
    status: str
    message: str


class MeetingDetectionOperationResponse(BaseModel):
    success: bool
    message: str


class CalendarEventIgnoreRequest(BaseModel):
    event_id: str


@router.post("/audio-activity/probe-response", response_model=ProbeResponseAck)
async def handle_audio_probe_response(response_data: dict) -> ProbeResponseAck:
    """Receive the client's audio-activity probe result and resolve the Future."""
    try:
        deliver_audio_probe_response(response_data)
        return ProbeResponseAck(status="success", message="Audio probe response received")
    except (ValueError, KeyError) as exc:
        # Unknown/duplicate request_id is benign (e.g. a probe that already timed
        # out); ack rather than 500 so the client doesn't retry pointlessly.
        logger.warning("Audio probe response not matched: %s", exc)
        return ProbeResponseAck(status="ignored", message=str(exc))
    except Exception as exc:
        logger.error("Error handling audio probe response: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error handling audio probe response: {str(exc)}")


@router.post("/meeting-detection/calendar-probe-response", response_model=ProbeResponseAck)
async def handle_calendar_probe_response(response_data: dict) -> ProbeResponseAck:
    """Receive the client's calendar probe result and resolve the Future."""
    try:
        deliver_calendar_probe_response(response_data)
        return ProbeResponseAck(status="success", message="Calendar probe response received")
    except (ValueError, KeyError) as exc:
        logger.warning("Calendar probe response not matched: %s", exc)
        return ProbeResponseAck(status="ignored", message=str(exc))
    except Exception as exc:
        logger.error("Error handling calendar probe response: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error handling calendar probe response: {str(exc)}")


def _get_runtime_or_raise():
    runtime = get_meeting_detection_runtime()
    if runtime is None:
        raise HTTPException(status_code=503, detail="Meeting detection runtime is not initialized")
    return runtime


async def _start_from_preferences() -> MeetingDetectionOperationResponse:
    preferences = load_preferences()
    if not preferences.meeting_detection.enabled:
        raise HTTPException(status_code=409, detail="Meeting Detection is disabled in Settings")
    runtime = _get_runtime_or_raise()
    await runtime.apply_settings(preferences.meeting_detection)
    await runtime.start()
    return MeetingDetectionOperationResponse(success=True, message="Meeting detection started")


async def _stop_runtime() -> MeetingDetectionOperationResponse:
    runtime = _get_runtime_or_raise()
    await runtime.stop()
    return MeetingDetectionOperationResponse(success=True, message="Meeting detection stopped")


@router.post("/meeting-detection/start", response_model=MeetingDetectionOperationResponse)
async def start_meeting_detection() -> MeetingDetectionOperationResponse:
    """Start the meeting-detection runtime if enabled in settings."""
    return await _start_from_preferences()


@router.post("/meeting-detection/stop", response_model=MeetingDetectionOperationResponse)
async def stop_meeting_detection() -> MeetingDetectionOperationResponse:
    """Stop the meeting-detection runtime without disabling the feature."""
    return await _stop_runtime()


@router.post("/meeting-detection/toggle", response_model=MeetingDetectionOperationResponse)
async def toggle_meeting_detection() -> MeetingDetectionOperationResponse:
    """Toggle the meeting-detection runtime running state."""
    runtime = _get_runtime_or_raise()
    if runtime.is_running():
        return await _stop_runtime()
    return await _start_from_preferences()


@router.get("/meeting-detection/status")
async def get_meeting_detection_status() -> Dict[str, Any]:
    """Return runtime status for meeting detection."""
    runtime = get_meeting_detection_runtime()
    if runtime is None:
        return {"initialized": False, "enabled": False, "is_running": False}
    return runtime.get_status()


@router.post("/meeting-detection/calendar-event/ignore", response_model=MeetingDetectionOperationResponse)
async def ignore_meeting_detection_calendar_event(
    request: CalendarEventIgnoreRequest,
) -> MeetingDetectionOperationResponse:
    """Suppress future prompts for a specific calendar event."""
    event_id = request.event_id.strip()
    if not event_id:
        raise HTTPException(status_code=400, detail="event_id is required")
    runtime = _get_runtime_or_raise()
    runtime.ignore_calendar_event(event_id)
    return MeetingDetectionOperationResponse(
        success=True,
        message="Calendar event ignored for meeting detection",
    )
