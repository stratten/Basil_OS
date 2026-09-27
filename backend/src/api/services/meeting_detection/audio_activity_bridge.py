"""WebSocket bridge for probing the client's meeting-app audio activity.

Mirrors ``api.services.capture.shared.window_capture_bridge`` exactly in shape:
send a request over the active client WebSocket(s), then await an
``asyncio.Future`` that the client resolves by POSTing back to
``/audio-activity/probe-response``.

Unlike a window capture, the probe is cheap (a couple of CoreAudio HAL reads on
the client) and is expected to return quickly, so the timeout is short.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any, Dict, List

from api.services.websocket_connection_manager import active_connections

logger = logging.getLogger(__name__)

# Pending probe requests keyed by request_id -> response Future.
pending_audio_probe_requests: dict[str, asyncio.Future[Dict[str, Any]]] = {}

# Probes are mechanical and fast; keep the wait tight so a slow/absent client
# never stalls the detection loop.
_PROBE_TIMEOUT_SECONDS = 3.0


async def request_swift_audio_probe(excluded_bundle_ids: List[str]) -> Dict[str, Any]:
    """Ask the client which non-excluded processes are active meetings.

    Args:
        excluded_bundle_ids: Bundle identifiers the client should ignore while
            probing CoreAudio ``IsRunningInput`` + ``IsRunningOutput``.

    Returns:
        Dict with ``success`` plus, on success, ``active_meeting_apps`` (list of
        ``{name, bundle_id, pid}``) and ``current_calendar_event`` (or ``None``).
    """
    try:
        if not active_connections:
            return {
                "success": False,
                "message": "No frontend connection available for audio probe",
                "probe_method": "websocket_no_connection",
                "active_meeting_apps": [],
                "current_calendar_event": None,
            }

        request_id = str(uuid.uuid4())
        timestamp = int(time.time() * 1000)

        response_future: asyncio.Future[Dict[str, Any]] = asyncio.Future()
        pending_audio_probe_requests[request_id] = response_future

        probe_request = {
            "event_type": "audio_activity_probe",
            "request_id": request_id,
            "timestamp": timestamp,
            "excluded_bundle_ids": excluded_bundle_ids,
        }

        successful_sends = 0
        for connection in active_connections:
            try:
                await connection.send_json(probe_request)
                successful_sends += 1
            except Exception as exc:
                logger.error("Failed to send audio probe to WebSocket connection: %s", exc)

        if successful_sends == 0:
            pending_audio_probe_requests.pop(request_id, None)
            return {
                "success": False,
                "message": "Failed to send audio probe to frontend",
                "probe_method": "websocket_send_failed",
                "active_meeting_apps": [],
                "current_calendar_event": None,
            }

        try:
            probe_response = await asyncio.wait_for(response_future, timeout=_PROBE_TIMEOUT_SECONDS)
            pending_audio_probe_requests.pop(request_id, None)
            return probe_response
        except asyncio.TimeoutError:
            pending_audio_probe_requests.pop(request_id, None)
            logger.warning("Audio probe %s timed out after %.1fs", request_id, _PROBE_TIMEOUT_SECONDS)
            return {
                "success": False,
                "message": "Frontend audio probe timed out",
                "probe_method": "websocket_timeout",
                "active_meeting_apps": [],
                "current_calendar_event": None,
            }

    except Exception as exc:
        logger.error("Error in Swift audio probe: %s", exc, exc_info=True)
        return {
            "success": False,
            "message": f"Audio probe error: {str(exc)}",
            "probe_method": "websocket_error",
            "active_meeting_apps": [],
            "current_calendar_event": None,
        }


def deliver_audio_probe_response(response_data: dict) -> None:
    """Resolve the pending probe Future with the client's response."""
    request_id = response_data.get("request_id")

    if not request_id:
        logger.error("Audio probe response missing request_id")
        raise ValueError("Missing request_id in audio probe response")

    if request_id not in pending_audio_probe_requests:
        logger.warning("Received audio probe response for unknown request_id: %s", request_id)
        raise KeyError(f"Unknown audio probe request_id: {request_id}")

    response_future = pending_audio_probe_requests[request_id]

    if not response_future.done():
        response_future.set_result(response_data)
    else:
        logger.warning("Audio probe response received for already completed request %s", request_id)
