"""WebSocket bridge for probing the client's joinable calendar events.

This is intentionally separate from audio probing and Activity Capture. The
backend owns meeting-detection policy, while the client performs the OS-specific
EventKit read and posts the result back to resolve the pending Future.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any, Dict

from api.services.websocket_connection_manager import active_connections

logger = logging.getLogger(__name__)

pending_calendar_probe_requests: dict[str, asyncio.Future[Dict[str, Any]]] = {}

_PROBE_TIMEOUT_SECONDS = 3.0


async def request_swift_calendar_probe(window_start_iso: str, window_end_iso: str) -> Dict[str, Any]:
    """Ask the client for joinable calendar events in the requested window."""
    try:
        if not active_connections:
            return {
                "success": False,
                "message": "No frontend connection available for calendar probe",
                "probe_method": "websocket_no_connection",
                "joinable_events": [],
            }

        request_id = str(uuid.uuid4())
        timestamp = int(time.time() * 1000)

        response_future: asyncio.Future[Dict[str, Any]] = asyncio.Future()
        pending_calendar_probe_requests[request_id] = response_future

        probe_request = {
            "event_type": "meeting_calendar_probe",
            "request_id": request_id,
            "timestamp": timestamp,
            "window_start": window_start_iso,
            "window_end": window_end_iso,
        }

        successful_sends = 0
        for connection in active_connections:
            try:
                await connection.send_json(probe_request)
                successful_sends += 1
            except Exception as exc:
                logger.error("Failed to send calendar probe to WebSocket connection: %s", exc)

        if successful_sends == 0:
            pending_calendar_probe_requests.pop(request_id, None)
            return {
                "success": False,
                "message": "Failed to send calendar probe to frontend",
                "probe_method": "websocket_send_failed",
                "joinable_events": [],
            }

        try:
            probe_response = await asyncio.wait_for(response_future, timeout=_PROBE_TIMEOUT_SECONDS)
            pending_calendar_probe_requests.pop(request_id, None)
            return probe_response
        except asyncio.TimeoutError:
            pending_calendar_probe_requests.pop(request_id, None)
            logger.warning("Calendar probe %s timed out after %.1fs", request_id, _PROBE_TIMEOUT_SECONDS)
            return {
                "success": False,
                "message": "Frontend calendar probe timed out",
                "probe_method": "websocket_timeout",
                "joinable_events": [],
            }

    except Exception as exc:
        logger.error("Error in Swift calendar probe: %s", exc, exc_info=True)
        return {
            "success": False,
            "message": f"Calendar probe error: {str(exc)}",
            "probe_method": "websocket_error",
            "joinable_events": [],
        }


def deliver_calendar_probe_response(response_data: dict) -> None:
    """Resolve the pending calendar probe Future with the client's response."""
    request_id = response_data.get("request_id")

    if not request_id:
        logger.error("Calendar probe response missing request_id")
        raise ValueError("Missing request_id in calendar probe response")

    if request_id not in pending_calendar_probe_requests:
        logger.warning("Received calendar probe response for unknown request_id: %s", request_id)
        raise KeyError(f"Unknown calendar probe request_id: {request_id}")

    response_future = pending_calendar_probe_requests[request_id]

    if not response_future.done():
        response_future.set_result(response_data)
    else:
        logger.warning("Calendar probe response received for already completed request %s", request_id)
