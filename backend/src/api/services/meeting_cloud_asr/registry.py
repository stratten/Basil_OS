"""Process-wide view of cloud transcription sessions, published as one aggregate status frame on change."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, Optional

from .models import (
    CLOUD_STATUS_EVENT_TYPE,
    STATE_CONNECTING,
    STATE_FALLBACK,
    STATE_OFF,
    STATE_STREAMING,
)

logger = logging.getLogger(__name__)

Broadcaster = Callable[[Dict[str, Any]], Awaitable[Any]]


@dataclass(frozen=True)
class SessionStatus:
    state: str
    provider: str
    tier: str
    reason: Optional[str] = None


class CloudStatusRegistry:
    def __init__(self, broadcaster: Optional[Broadcaster] = None) -> None:
        self._broadcaster = broadcaster
        self._sessions: Dict[int, SessionStatus] = {}
        self._last_published: Optional[Dict[str, Any]] = None

    def aggregate(self) -> Dict[str, Any]:
        statuses = list(self._sessions.values())
        for state in (STATE_STREAMING, STATE_CONNECTING, STATE_FALLBACK):
            matching = [status for status in statuses if status.state == state]
            if matching:
                first = matching[0]
                return {
                    "event_type": CLOUD_STATUS_EVENT_TYPE,
                    "state": state,
                    "provider": first.provider,
                    "tier": first.tier,
                    "reason": first.reason,
                }
        return {"event_type": CLOUD_STATUS_EVENT_TYPE, "state": STATE_OFF, "provider": None, "tier": None, "reason": None}

    async def update(self, key: int, status: Optional[SessionStatus]) -> None:
        if status is None:
            self._sessions.pop(key, None)
        else:
            self._sessions[key] = status
        await self._publish_if_changed()

    async def _publish_if_changed(self) -> None:
        frame = self.aggregate()
        if frame == self._last_published:
            return
        self._last_published = frame
        broadcaster = self._broadcaster
        if broadcaster is None:
            from api.services.websocket_connection_manager import broadcast_json_text

            broadcaster = broadcast_json_text
        try:
            await broadcaster(frame)
        except Exception as error:
            logger.warning("Could not publish cloud transcription status: %s", error)


cloud_status_registry = CloudStatusRegistry()
