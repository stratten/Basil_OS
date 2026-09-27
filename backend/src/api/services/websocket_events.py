"""Backend-facing WebSocket event send helpers."""

from __future__ import annotations

import logging
import time
import uuid
from enum import Enum
from typing import Optional

from api.models.websocket_events import HistoryChatEvent
from api.services.websocket_connection_manager import active_connections

logger = logging.getLogger(__name__)


async def send_transcription_status(event: str, data: any = None):
    message = {
        "event": event,
        "data": data
    }
    logger.info(f"Sending transcription status: {message}")
    for connection in active_connections:
        try:
            await connection.send_json(message)
        except Exception as e:
            logger.error(f"Error sending status to client: {e}")


async def send_history_chat_event(active: bool, message: Optional[str] = None,
                                  message_type: Optional[str] = None,
                                  context: Optional[str] = None,
                                  is_loading: bool = False,
                                  message_id: Optional[str] = None,
                                  conversation_id: Optional[str] = None):
    if message_id is None:
        message_id = str(uuid.uuid4())
    if message_type is None:
        message_type = "assistant"
        logger.warning("No message_type provided, defaulting to 'assistant'")
    if message == "I couldn't find any activities matching your query.":
        logger.info(
            f"Sending 'no results found' message with message_type={message_type}, "
            f"is_loading={is_loading}"
        )
    event = HistoryChatEvent(
        event_type="history_chat_event",
        active=active,
        message=message,
        message_type=message_type,
        context=context,
        timestamp=time.time(),
        message_id=message_id,
        is_loading=is_loading,
        conversation_id=conversation_id
    )
    logger.info(
        f"Sending history chat event: active={active}, "
        f"message_type={message_type}, is_loading={is_loading}"
    )
    logger.info(f"Event data: {event.dict()}")
    logger.info("[CONNECTIONS] Active connections before send: " + ", ".join([
        f"id={id(conn)} state={getattr(conn, 'client_state', 'unknown')}" for conn in active_connections
    ]))
    for connection in active_connections:
        event_dict = event.dict()
        try:
            if isinstance(event_dict.get("event_type"), Enum):
                event_dict["event_type"] = event_dict["event_type"].value
            if message_type == "assistant" and not is_loading:
                canary_event = {
                    "event_type": "history_chat_event",
                    "data": None,
                    "timestamp": time.time(),
                    "active": active,
                    "context": context,
                    "message": message,
                    "message_type": message_type,
                    "message_id": f"canary-{message_id}",
                    "is_loading": is_loading,
                    "conversation_id": conversation_id
                }
                logger.info(
                    f"[CANARY] About to send CANARY message to connection {id(connection)}: "
                    f"{canary_event} (connection state: {getattr(connection, 'client_state', 'unknown')})"
                )
                await connection.send_json(canary_event)
                logger.info(
                    f"[CANARY] Successfully sent CANARY message to connection {id(connection)}: "
                    f"{canary_event} (connection state: {getattr(connection, 'client_state', 'unknown')})"
                )
            logger.info(
                f"[ANALYSIS] About to send analysis event to connection {id(connection)}: "
                f"{event_dict} (connection state: {getattr(connection, 'client_state', 'unknown')})"
            )
            await connection.send_json(event_dict)
            logger.info(
                f"[ANALYSIS] Successfully sent analysis event to connection {id(connection)}: "
                f"{event_dict} (connection state: {getattr(connection, 'client_state', 'unknown')})"
            )
        except Exception as e:
            logger.error(
                f"[ANALYSIS] Error sending analysis event to connection {id(connection)}: "
                f"{event_dict}; Exception: {e} "
                f"(connection state: {getattr(connection, 'client_state', 'unknown')})",
                exc_info=True,
            )

__all__ = ["send_history_chat_event", "send_transcription_status"]
