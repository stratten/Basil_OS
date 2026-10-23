"""Feedback and WebSocket broadcast helpers for wake-word agent tasks."""

import json
import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


async def _project_conversation_agent_task_progress(message_data: Dict[str, Any]) -> None:
    """Persist a live progress label when this Agent Task belongs to a Conversation turn."""
    if message_data.get("event_type", message_data.get("type")) != "agent_task_progress":
        return
    agent_task_id = message_data.get("agent_task_id")
    if not isinstance(agent_task_id, str) or not agent_task_id.strip():
        return
    timeline_entry = message_data.get("timeline_entry")
    status_text = message_data.get("step")
    if not isinstance(status_text, str) or not status_text.strip():
        if isinstance(timeline_entry, dict):
            status_text = (
                timeline_entry.get("title")
                or timeline_entry.get("summary")
                or timeline_entry.get("content")
            )
    if not isinstance(status_text, str) or not status_text.strip():
        return
    try:
        from api.services.conversation.conversation_agent_turn_lifecycle import (
            project_conversation_agent_task_progress,
        )

        await project_conversation_agent_task_progress(agent_task_id, status_text)
    except Exception:
        logger.warning(
            "Conversation progress projection failed for Agent Task %s",
            agent_task_id,
            exc_info=True,
        )


async def notify_agent_task_started(service) -> None:
    """
    Notify connected WebSocket clients that agent_task capture has started.
    This triggers the frontend to show the capture widget with real-time feedback.

    Frontend will decide if this is a follow-up agent task by checking widget state locally.
    """
    try:
        notification = {
            "event_type": "agent_task_capture_started",
            "message": "Task capture started",
            "timestamp": 0  # Simple timestamp
        }

        # Include screenshot metadata if available
        if hasattr(service, '_current_screenshot_data') and service._current_screenshot_data:
            notification["screenshot"] = {
                "success": service._current_screenshot_data.get("success", False),
                "app_name": service._current_screenshot_data.get("app_name", "Unknown"),
                "window_title": service._current_screenshot_data.get("window_title", "Unknown"),
                "capture_method": service._current_screenshot_data.get("capture_method", "unknown"),
                "has_image": service._current_screenshot_data.get("image_path") is not None
            }

            if notification["screenshot"]["success"]:
                logger.info(f"📸 Including screenshot metadata: {notification['screenshot']['app_name']} - {notification['screenshot']['window_title']}")
            else:
                logger.warning(f"⚠️ Screenshot capture failed, including error info in notification")

        await service.broadcast(notification)
        logger.info(f"Sent agent_task started notification")

    except Exception as e:
        logger.error(f"Error sending agent_task started notification: {e}")


async def provide_feedback(service, message: str) -> None:
    """
    Provide feedback to the user about agent-task processing.

    Args:
        message: Feedback message to provide
    """
    try:
        # TODO: Integrate with voice feedback system
        # This could:
        # 1. Use text-to-speech to speak the response
        # 2. Show a notification
        # 3. Log to a feedback system

        logger.info(f"User feedback: {message}")
        print(f"VOICE FEEDBACK: {message}")

        # Placeholder for actual feedback implementation
        # await self.voice_feedback_service.speak(message)
        # await self.notification_service.show(message)

    except Exception as e:
        logger.error(f"Error providing user feedback: {e}")


async def provide_feedback_from_result(service, result: Dict[str, Any]) -> None:
    """
    Provide feedback based on agent-task processing result.

    Args:
        result: Result dictionary from agent-task orchestrator
    """
    try:
        message = result.get('message', 'Task processed.')
        success = result.get('success', False)
        operation = result.get('operation', 'unknown')

        if success:
            await service._provide_feedback(message)

            # Additional feedback based on operation type
            if operation == "capture_screen":
                await service._provide_feedback("Screenshot saved successfully.")
            elif operation == "generate_suggestions":
                suggestions = result.get('data', {}).get('suggestions', [])
                if suggestions:
                    await service._provide_feedback(f"I've generated {len(suggestions)} suggestions for you.")
            elif operation == "extract_text":
                word_count = result.get('data', {}).get('word_count', 0)
                if word_count > 0:
                    await service._provide_feedback(f"I've extracted {word_count} words from your screen.")

        else:
            # Handle errors and clarification requests
            if result.get('needs_clarification'):
                logger.info(f"🚧 Clarification requested: operation={operation}, message={message}")
                await service._provide_feedback(message)
                # Broadcast a structured result for frontend clarification UI
                await service.broadcast({
                    "event_type": "agent_task_result",
                    "success": False,
                    "needs_clarification": True,
                    "result": message,
                    "operation": result.get("operation")
                })
            else:
                await service._provide_feedback(f"Sorry, {message}")

        # Log the full result for debugging
        logger.debug(f"AgentTask processing result: {result}")

    except Exception as e:
        logger.error(f"Error providing feedback from result: {e}")
        await service._provide_feedback("I finished the task, but I couldn't provide detailed feedback.")


async def broadcast(service, message_data: Dict[str, Any]) -> None:
    """
    Broadcast a message to all connected WebSocket clients.
    Generic method for sending any WebSocket notifications.

    Args:
        message_data: Dictionary containing the message to broadcast
    """
    try:
        await _project_conversation_agent_task_progress(message_data)

        # Import here to avoid circular imports
        from api.services.websocket_connection_manager import active_connections

        evt = message_data.get('event_type', message_data.get('type', 'unknown'))
        logger.info(f"About to broadcast message to {len(active_connections)} connections: {evt}")
        successful_sends = 0
        for connection in active_connections:
            try:
                await connection.send_json(message_data)
                successful_sends += 1
                logger.info(f"✅ Successfully sent message to WebSocket connection")
            except Exception as e:
                logger.error(f"❌ CRITICAL: Failed to send WebSocket message to a connection: {e}")
                logger.error(f"❌ Message data: {message_data}")
                logger.error(f"❌ Connection state: {connection}")
                import traceback
                logger.error(f"❌ Full traceback: {traceback.format_exc()}")

        logger.info(f"Successfully broadcasted message to {successful_sends}/{len(active_connections)} WebSocket clients: {message_data.get('event_type', message_data.get('type', 'unknown'))}")

        # Special logging for agent_task_result messages
        if message_data.get('event_type') == 'agent_task_result':
            message_size = len(json.dumps(message_data))
            logger.info(f"🎯 VOICE AGENT TASK RESULT SENT - Message size: {message_size} bytes")
            logger.info(f"🎯 Message content preview: {str(message_data)[:200]}..." if len(str(message_data)) > 200 else f"🎯 Message content: {message_data}")

    except Exception as e:
        logger.error(f"Error broadcasting WebSocket message: {e}")
