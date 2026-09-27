"""Shared capture infrastructure."""

from .activity_capture_status import ActivityCaptureStatus
from .window_capture_bridge import (
    deliver_capture_response,
    request_swift_window_capture,
    trigger_automatic_activity_capture,
)

__all__ = [
    "ActivityCaptureStatus",
    "deliver_capture_response",
    "request_swift_window_capture",
    "trigger_automatic_activity_capture",
]
