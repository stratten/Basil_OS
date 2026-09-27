"""WebSocket bridge for requesting Swift window captures."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any, Dict, List, Optional

from api.services.websocket_connection_manager import active_connections

logger = logging.getLogger(__name__)

# Dictionary to store pending capture requests with their response futures
pending_capture_requests: dict[str, asyncio.Future[Dict[str, Any]]] = {}


async def request_swift_window_capture(
    capture_reason: str = "agent_task",
    *,
    excluded_bundle_ids: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Internal function to trigger Swift WindowCaptureService capture.

    Args:
        capture_reason: The reason for the capture (e.g., "agent_task", "automatic activity capture")

    Returns:
        Dict with capture results including file path
    """
    try:
        if capture_reason == "agent_task":
            logger.info("🎯 Immediate Swift capture triggered by wake word detection")
        elif capture_reason == "automatic activity capture":
            logger.info("📸 Automatic activity capture triggered by scheduler")
        else:
            logger.info(f"🔄 Swift capture triggered: {capture_reason}")

        # Check if any WebSocket connections are available
        if not active_connections:
            logger.warning("⚠️ No active WebSocket connections - cannot request Swift capture")
            return {
                "success": False,
                "message": "No frontend connection available for Swift capture",
                "capture_method": "websocket_no_connection",
                "has_image": False
            }

        # Generate unique request ID for tracking this capture request
        request_id = str(uuid.uuid4())
        timestamp = int(time.time() * 1000)

        # Create a future to wait for the capture response
        response_future: asyncio.Future[Dict[str, Any]] = asyncio.Future()
        pending_capture_requests[request_id] = response_future

        # Prepare WebSocket message to request capture from frontend
        if capture_reason == "automatic activity capture":
            message = "Automatic activity capture scheduled"
        else:
            message = "Immediate window capture requested for agent_task"

        capture_request = {
            "event_type": "capture_request",
            "request_id": request_id,
            "capture_type": "window_immediate",
            "timestamp": timestamp,
            "message": message,
            "capture_reason": capture_reason,
        }
        if capture_reason == "automatic activity capture" and excluded_bundle_ids is not None:
            capture_request["capture_policy"] = {
                "excluded_bundle_ids": excluded_bundle_ids,
            }

        logger.info(f"📤 Sending capture request to {len(active_connections)} WebSocket connections: {request_id}")

        # Send the capture request to all connected clients
        successful_sends = 0
        for connection in active_connections:
            try:
                await connection.send_json(capture_request)
                successful_sends += 1
                logger.info("✅ Sent capture request to WebSocket connection")
            except Exception as e:
                logger.error(f"❌ Failed to send capture request to WebSocket connection: {e}")

        if successful_sends == 0:
            # Clean up the pending request
            pending_capture_requests.pop(request_id, None)
            logger.error("❌ Failed to send capture request to any WebSocket connections")
            return {
                "success": False,
                "message": "Failed to send capture request to frontend",
                "capture_method": "websocket_send_failed",
                "has_image": False
            }

        logger.info(f"📤 Successfully sent capture request to {successful_sends}/{len(active_connections)} connections")

        # Wait for the response with a timeout
        try:
            # Wait up to 5 seconds for the frontend to respond
            capture_response = await asyncio.wait_for(response_future, timeout=5.0)

            # Clean up the pending request
            pending_capture_requests.pop(request_id, None)

            logger.info(f"✅ Received capture response for request {request_id}")
            return capture_response

        except asyncio.TimeoutError:
            # Clean up the pending request
            pending_capture_requests.pop(request_id, None)
            logger.warning(f"⏰ Capture request {request_id} timed out after 5 seconds")
            return {
                "success": False,
                "message": "Frontend capture request timed out",
                "capture_method": "websocket_timeout",
                "has_image": False,
                "timeout_duration": 5.0
            }

    except Exception as e:
        logger.error(f"❌ Error in Swift window capture: {e}", exc_info=True)
        return {
            "success": False,
            "message": f"Swift capture error: {str(e)}",
            "capture_method": "websocket_error",
            "has_image": False
        }


async def trigger_automatic_activity_capture(
    excluded_bundle_ids: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Trigger Swift WindowCaptureService for automatic activity capture.

    This function is called by the automatic activity capture service and returns
    a dictionary instead of a JSONResponse for easier processing.
    """
    return await request_swift_window_capture(
        "automatic activity capture",
        excluded_bundle_ids=excluded_bundle_ids,
    )


def deliver_capture_response(response_data: dict) -> None:
    """Deliver a Swift capture response to the waiting capture request."""
    request_id = response_data.get("request_id")

    if not request_id:
        logger.error("❌ Capture response missing request_id")
        raise ValueError("Missing request_id in capture response")

    if request_id not in pending_capture_requests:
        logger.warning(f"⚠️ Received capture response for unknown request_id: {request_id}")
        raise KeyError(f"Unknown capture request_id: {request_id}")

    # Get the future for this request
    response_future = pending_capture_requests[request_id]

    # Set the result to fulfill the waiting endpoint
    if not response_future.done():
        response_future.set_result(response_data)
        logger.info(f"✅ Capture response delivered for request {request_id}")
    else:
        logger.warning(f"⚠️ Capture response received for already completed request {request_id}")
