from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from typing import Set
import asyncio
import json
import logging
import pyperclip
import os
import base64
import tempfile
from pathlib import Path
from ..services.transcription import HuggingFaceTranscriptionService
from ..core.models.preferences import Preferences
from pynput.keyboard import Key, Controller as KeyboardController
import stat
from ..models.websocket_events import WebSocketEventType, HistoryChatEvent
import uuid
import time
from ..dependencies import get_agent_task_submission_service, get_conversation_turn_router, get_conversation_service, get_wake_word_service, get_transcription_service, resolve_transcription_service, get_todo_workspace_turn_manager
from ..services.conversation import ConversationService
from ..services.agent_processing.lifecycle.submission import AgentTaskSubmissionService
from ..services.wake_word import WakeWordService
from datetime import datetime, timedelta
from ..core.knowledge.query.activity_summarizer import generate_activity_summary
from enum import Enum
from api.services.websocket_connection_manager import active_connections, add_connection, remove_connection
from api.services.transcription.local_model import model_unload_state
from .websocket_routes.transcription import (
    paste_transcribed_text,
    schedule_model_unload,
    send_transcription_status,
    handle_init_transcription,
    handle_initialize_transcription,
    handle_schedule_model_unload,
    handle_cancel_transcription,
    handle_set_context_info,
    handle_audio_transcription
)
from .websocket_routes.conversation import send_history_chat_event, send_conversation_token, handle_conversation_message
from .websocket_routes.todo_workspace import handle_todo_workspace_message
from .websocket_routes.conversation_request_runtime import conversation_request_runtime
from ..services.conversation.conversation_turn_router import ConversationTurnRouter

logger = logging.getLogger(__name__)

router = APIRouter()

SENSITIVE_LOG_KEYS = {
    "access_token",
    "refresh_token",
    "id_token",
    "token",
    "authorization",
    "auth",
    "secret",
    "password",
    "api_key",
    "client_secret",
}

CONTENT_LOG_KEYS = {
    "text",
    "message",
    "content",
    "prompt",
    "transcription",
    "selected_text",
}


def _summarize_websocket_text_for_log(text: str) -> str:
    """Return release-safe WebSocket metadata without raw user or token payloads."""
    if text == "ping" or text == "init_transcription":
        return f"plain_text={text!r}"
    if not (text.startswith("{") and text.endswith("}")):
        return f"plain_text_length={len(text)}"

    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return f"json_parse_failed length={len(text)}"

    if not isinstance(payload, dict):
        return f"json_payload_type={type(payload).__name__} length={len(text)}"

    return f"json {_summarize_websocket_payload_for_log(payload)}"


def _summarize_websocket_payload_for_log(payload: dict) -> str:
    """Summarize a parsed WebSocket payload while redacting sensitive fields."""
    safe_fields = []
    for key in ("agent_task_action", "type", "event_type", "request_id", "correlation_id", "agent_task_id"):
        value = payload.get(key)
        if value is not None:
            safe_fields.append(f"{key}={value!r}")

    redacted_keys = sorted(
        key for key in payload.keys()
        if key.lower() in SENSITIVE_LOG_KEYS or key.lower() in CONTENT_LOG_KEYS
    )
    visible_keys = sorted(
        key for key in payload.keys()
        if key.lower() not in SENSITIVE_LOG_KEYS and key.lower() not in CONTENT_LOG_KEYS
    )

    details = safe_fields + [
        f"keys={visible_keys}",
        f"redacted_keys={redacted_keys}",
    ]
    return " ".join(details)


async def _handle_conversation_cancel_message(
    websocket,
    msg_data: dict,
    request_runtime,
    agent_task_submission_service,
) -> None:
    """Cancel a direct or Agent Task Conversation turn correlated by request_id or conversation_id."""
    raw_request_id = msg_data.get("request_id")
    request_id = (
        raw_request_id.strip()
        if isinstance(raw_request_id, str) and raw_request_id.strip()
        else None
    )
    if not request_id:
        await websocket.send_json({
            "event_type": "conversation_cancel_rejected",
            "message": "A non-empty request_id is required.",
        })
        return
    raw_conversation_id = msg_data.get("conversation_id")
    conversation_id = (
        raw_conversation_id.strip()
        if isinstance(raw_conversation_id, str) and raw_conversation_id.strip()
        else None
    )
    state = request_runtime.request_cancel(websocket, request_id)
    agent_task_id = request_runtime.agent_task_for_request(websocket, request_id)
    if state is None and agent_task_id is None and conversation_id:
        state, agent_task_id = request_runtime.request_cancel_for_conversation(conversation_id)
    narration_canceled = False
    if agent_task_id:
        from api.services.conversation.conversation_agent_narration_service import (
            get_registered_conversation_agent_narration_service,
        )

        try:
            narration_canceled = await get_registered_conversation_agent_narration_service().cancel_narration(
                agent_task_id
            )
        except RuntimeError:
            narration_canceled = False
        if not narration_canceled:
            await agent_task_submission_service.cancel_agent_task_durably(
                agent_task_id,
                "User canceled Conversation request",
            )
            if request_runtime.claim_agent_task_cancellation(websocket, request_id) is None and conversation_id:
                request_runtime.claim_agent_task_cancellation_for_conversation(conversation_id)
    if narration_canceled:
        await websocket.send_json({
            "event_type": "conversation_canceled",
            "request_id": request_id,
            "message": "Conversation response canceled.",
        })
    if state is None and agent_task_id is None:
        await websocket.send_json({
            "event_type": "conversation_cancel_rejected",
            "request_id": request_id,
            "message": "No active Conversation request matched this socket.",
        })


@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    agent_task_submission_service: AgentTaskSubmissionService = Depends(get_agent_task_submission_service),
    wake_word_service: WakeWordService = Depends(get_wake_word_service),
    transcription_service: HuggingFaceTranscriptionService = Depends(get_transcription_service),
    conversation_turn_router: ConversationTurnRouter = Depends(get_conversation_turn_router),
    todo_workspace_turn_manager=Depends(get_todo_workspace_turn_manager),
):
    await websocket.accept()
    add_connection(websocket)
    logger.info(f"WebSocket client connected. Active connections: {len(active_connections)}")
    
    # Log system permissions and state
    logger.info("\n=== System Permissions Check ===")
    try:
        import os
        import stat
        config_dir = Path.home() / ".config" / "basil"
        logger.info(f"Config directory: {config_dir}")
        logger.info(f"Config directory exists: {config_dir.exists()}")
        if config_dir.exists():
            st = os.stat(config_dir)
            logger.info(f"Config directory permissions: {stat.filemode(st.st_mode)}")
            logger.info(f"Config directory owner: {st.st_uid}")
    except Exception as e:
        logger.error(f"Error checking system state: {e}")
    logger.info("=== End System Permissions Check ===\n")
    
    logger.info(f"WebSocket client connected. Active connections: {len(active_connections)}")
    
    try:
        while True:
            # Handle both text and binary messages
            message = await websocket.receive()
            logger.info(f"\n=== WebSocket Message Received ===")
            logger.info(f"Message type: {message['type']}")
            
            if message["type"] == "websocket.disconnect":
                logger.info(f"[CONNECTIONS] Client disconnect requested: id={id(websocket)}. Removing from active.")
                break
                
            elif message["type"] == "websocket.receive":
                if "text" in message:
                    text = message["text"]
                    logger.info("Text message received: %s", _summarize_websocket_text_for_log(text))
                    
                    if text == "ping":
                        await websocket.send_text("pong")
                        logger.info("Sent pong response")
                        
                    elif text == "init_transcription":
                        await handle_init_transcription(websocket, resolve_transcription_service(), send_transcription_status)
                        
                    # Handle JSON formatted messages
                    elif text.startswith("{") and text.endswith("}"):
                        try:
                            # Parse the JSON message
                            msg_data = json.loads(text)
                            client_action = msg_data.get("agent_task_action")
                            
                            logger.info(f"Processing websocket action: {client_action}")
                            
                            if client_action == "initialize_transcription":
                                await handle_initialize_transcription(websocket, resolve_transcription_service(), send_transcription_status, model_unload_state.cancel_scheduled_model_unload, Preferences, msg_data)
                                
                            elif client_action == "schedule_model_unload":
                                delay_seconds = msg_data.get("delay_seconds", 60)  # Default to 60 if not provided
                                model_unload_state.model_unload_task = schedule_model_unload(resolve_transcription_service(), delay_seconds, model_unload_state.model_unload_task)
                                
                            elif client_action == "cancel_model_unload":
                                model_unload_state.cancel_scheduled_model_unload()
                                await websocket.send_json({
                                    "event_type": "model_unload_cancel_result",
                                    "status": "success",
                                    "message": "Model unload canceled"
                                })
                                
                            elif client_action == "cancel_transcription":
                                await handle_cancel_transcription(websocket, send_transcription_status)
                                
                            elif client_action == "cancel_agent_task":
                                logger.info(f"Received agent_task cancellation request")
                                try:
                                    agent_task_id = msg_data.get("agent_task_id")
                                    await agent_task_submission_service.cancel_agent_task_durably(
                                        agent_task_id=agent_task_id,
                                        reason="user_canceled",
                                    )
                                    await websocket.send_json({
                                        "event_type": "agent_task_cancel_result",
                                        "status": "success",
                                        "message": "AgentTask canceled"
                                    })
                                    logger.info("AgentTask cancellation completed successfully")
                                except Exception as e:
                                    logger.error(f"Error canceling agent_task: {e}")
                                    await websocket.send_json({
                                        "event_type": "agent_task_cancel_result",
                                        "status": "error",
                                        "message": f"Failed to cancel agent_task: {str(e)}"
                                    })
                                
                            elif msg_data.get("type") == "mcp_token_response":
                                # Swift client returning the access token (and
                                # optionally the refresh token, when the
                                # backend asked for a bundle) it holds in
                                # Keychain for a previously-asked connection.
                                # Resolve the awaiting future on the
                                # connections router so the request handler
                                # that needs the token can proceed.
                                try:
                                    from api.services.mcp_connectors.swift_token_bridge import resolve_pending_token_response
                                    correlation_id = msg_data.get("correlation_id")
                                    access_token = msg_data.get("access_token")
                                    refresh_token = msg_data.get("refresh_token")
                                    if correlation_id:
                                        delivered = resolve_pending_token_response(
                                            correlation_id, access_token, refresh_token
                                        )
                                        logger.info(
                                            "mcp_token_response handled correlation_id=%s delivered=%s has_access=%s has_refresh=%s",
                                            correlation_id,
                                            delivered,
                                            access_token is not None,
                                            refresh_token is not None,
                                        )
                                        if not delivered:
                                            # No waiting future matched — the request
                                            # already timed out/canceled and was popped,
                                            # or the correlation_id never matched. This is
                                            # the signature of the "Waiting for access"
                                            # hang, so surface it above DEBUG.
                                            logger.warning(
                                                "mcp_token_response had no pending waiter for correlation_id=%s "
                                                "(request already resolved/timed out, or correlation mismatch)",
                                                correlation_id,
                                            )
                                    else:
                                        logger.warning(
                                            "mcp_token_response missing correlation_id; cannot resolve token waiter"
                                        )
                                except Exception as e:
                                    logger.error(f"Error handling mcp_token_response: {e}")

                            elif msg_data.get("type") == "mcp_token_user_action_waiting":
                                try:
                                    from api.services.mcp_connectors.swift_token_bridge import broadcast_token_user_action_waiting
                                    correlation_id = msg_data.get("correlation_id")
                                    if correlation_id:
                                        delivered = await broadcast_token_user_action_waiting(
                                            correlation_id,
                                            connection_id=msg_data.get("connection_id"),
                                            message=msg_data.get("message"),
                                        )
                                        logger.info(
                                            "mcp_token_user_action_waiting handled correlation_id=%s delivered=%s",
                                            correlation_id,
                                            delivered,
                                        )
                                    else:
                                        logger.warning(
                                            "mcp_token_user_action_waiting missing correlation_id; cannot surface Keychain prompt"
                                        )
                                except Exception as e:
                                    logger.error(f"Error handling mcp_token_user_action_waiting: {e}")

                            elif msg_data.get("type") == "operation_state_response":
                                logger.info(f"Received operation state response from frontend")
                                try:
                                    # Route to the voice listener service's orchestration service
                                    if wake_word_service and hasattr(wake_word_service, 'agent_task_orchestration_service'):
                                        wake_word_service.agent_task_orchestration_service.handle_operation_state_response(msg_data)
                                        logger.debug("Operation state response handled successfully")
                                    else:
                                        logger.warning("Voice listener orchestration service not available for operation state response")
                                except Exception as e:
                                    logger.error(f"Error handling operation state response: {e}")
                                
                            elif msg_data.get("type") == "widget_state_response":
                                logger.info(f"Received widget state response from frontend")
                                try:
                                    # Route to the voice listener service's orchestration service
                                    if wake_word_service and hasattr(wake_word_service, 'agent_task_orchestration_service'):
                                        wake_word_service.agent_task_orchestration_service.handle_widget_state_response(msg_data)
                                        logger.debug("Widget state response handled successfully")
                                    else:
                                        logger.warning("Voice listener orchestration service not available for widget state response")
                                except Exception as e:
                                    logger.error(f"Error handling widget state response: {e}")
                            
                            elif msg_data.get("type") == "auth_token_response":
                                # Swift is responding with the auth token we requested
                                logger.info(f"Received auth token response from Swift")
                                try:
                                    from ..core.services.model_service import resolve_pending_token_request
                                    request_id = msg_data.get("request_id")
                                    token = msg_data.get("access_token")
                                    if request_id:
                                        if resolve_pending_token_request(request_id, token):
                                            logger.info(f"🔐 Auth token request {request_id} resolved")
                                        else:
                                            logger.warning(f"🔐 No pending request found for {request_id}")
                                    else:
                                        logger.warning("🔐 Auth token response missing request_id")
                                except Exception as e:
                                    logger.error(f"Error handling auth token response: {e}")
                                
                            elif msg_data.get("type") in ("agent_task_widget_closed", "agentTask_widget_closed"):
                                # BasilClient builds from before 2026-09-29 send the camelCase spelling; keep accepting it so an
                                # installed client can still dismiss an awaiting task instead of leaving it hung at the checkpoint.
                                widget_agent_task_id = msg_data.get("agent_task_id")
                                widget_is_awaiting = bool(msg_data.get("is_awaiting_user_input", False))
                                logger.info(
                                    "Received widget closed notification from frontend "
                                    f"(agent_task_id={widget_agent_task_id!r}, is_awaiting_user_input={widget_is_awaiting})"
                                )

                                # If the closed widget belonged to an awaiting-user-input task,
                                # dispatch a dismiss-resume so the agent finalizes with partial
                                # work instead of being left hung at the checkpoint forever.
                                if widget_agent_task_id:
                                    try:
                                        # Confirm awaiting status: trust the flag from the payload
                                        # OR look it up in the DB if the flag wasn't provided.
                                        should_dismiss = widget_is_awaiting
                                        if not should_dismiss:
                                            try:
                                                from api.dependencies import get_sqlite_knowledge_service
                                                ks = get_sqlite_knowledge_service()
                                                row = await ks.agent_task_service._queries.get_agent_task(widget_agent_task_id)
                                                if row is not None and getattr(row, "status", None) == "awaiting_user_input":
                                                    should_dismiss = True
                                            except Exception as lookup_err:
                                                logger.debug(
                                                    f"Could not look up agent_task status for dismiss check: {lookup_err}"
                                                )

                                        if should_dismiss:
                                            from api.services.agent_processing.lifecycle.runtime.workflow_coordinator import WorkflowCoordinator
                                            from api.services.agent_processing.lifecycle.runtime.checkpoint_workflow_service import (
                                                USER_DISMISSED_CHECKPOINT_RESPONSE,
                                            )
                                            agent_task_submission_service = getattr(websocket.app.state, "agent_task_submission_service", None)
                                            coordinator = WorkflowCoordinator(websocket_manager=agent_task_submission_service)

                                            async def _dispatch_dismiss(task_id: str):
                                                try:
                                                    logger.info(
                                                        f"🚪 Dispatching dismiss-resume for agent_task_id={task_id} after widget close"
                                                    )
                                                    await coordinator.resume_workflow(
                                                        agent_task_id=task_id,
                                                        user_response=USER_DISMISSED_CHECKPOINT_RESPONSE,
                                                    )
                                                    logger.info(
                                                        f"✅ Dismiss-resume completed for {task_id}"
                                                    )
                                                except Exception as dismiss_err:
                                                    logger.warning(
                                                        f"⚠️ Dismiss-resume for {task_id} failed: {dismiss_err}",
                                                        exc_info=True,
                                                    )

                                            asyncio.create_task(_dispatch_dismiss(widget_agent_task_id))
                                    except Exception as e:
                                        logger.error(
                                            f"Error initiating dismiss-resume for widget closed notification: {e}",
                                            exc_info=True,
                                        )

                                # Always resume the wake-word listener (this is the original behavior
                                # and is independent of whether we triggered dismiss-resume above).
                                try:
                                    if wake_word_service and hasattr(wake_word_service, 'agent_task_orchestration_service'):
                                        await wake_word_service.agent_task_orchestration_service._resume_wake_word_detection()
                                        await wake_word_service.agent_task_orchestration_service._resume_listening_if_enabled()
                                        logger.info("Voice listener resume triggered after widget closure")
                                    else:
                                        logger.warning("Voice listener orchestration service not available for widget closed notification")
                                except Exception as e:
                                    logger.error(f"Error resuming voice listener after widget closed notification: {e}")
                                
                            elif client_action == "set_context_info" or msg_data.get("type") == "context_info":
                                await handle_set_context_info(websocket, msg_data)

                            elif msg_data.get("type") == "conversation_cancel":
                                await _handle_conversation_cancel_message(
                                    websocket,
                                    msg_data,
                                    conversation_request_runtime,
                                    agent_task_submission_service,
                                )

                            # Handle direct conversation messages (no activity database query)
                            elif msg_data.get("type") == "todo_workspace_message":
                                await handle_todo_workspace_message(
                                    websocket, msg_data, turn_manager=todo_workspace_turn_manager,
                                )
                            elif msg_data.get("type") == "conversation_message":
                                logger.info(
                                    "Processing conversation message: %s",
                                    _summarize_websocket_payload_for_log(msg_data),
                                )
                                raw_request_id = msg_data.get("request_id")
                                request_id = (
                                    raw_request_id.strip()
                                    if isinstance(raw_request_id, str) and raw_request_id.strip()
                                    else None
                                )
                                raw_conversation_id = msg_data.get("conversation_id")
                                conversation_id = (
                                    raw_conversation_id.strip()
                                    if isinstance(raw_conversation_id, str) and raw_conversation_id.strip()
                                    else None
                                )
                                if request_id:
                                    async def _run_conversation_request(state):
                                        await handle_conversation_message(
                                            websocket,
                                            msg_data,
                                            get_conversation_service,
                                            send_conversation_token,
                                            request_state=state,
                                            request_runtime=conversation_request_runtime,
                                            turn_router=conversation_turn_router,
                                            agent_task_submission_service=agent_task_submission_service,
                                        )

                                    conversation_conflict = bool(
                                        conversation_id
                                        and conversation_request_runtime.is_conversation_active(conversation_id)
                                    )
                                    started = conversation_request_runtime.start(
                                        websocket,
                                        request_id,
                                        conversation_id,
                                        _run_conversation_request,
                                    )
                                    if not started:
                                        rejection_event = {
                                            "event_type": "conversation_error",
                                            "request_id": request_id,
                                            "message": (
                                                "A response is already active for this conversation."
                                                if conversation_conflict
                                                else "A Conversation request with this request_id is already active."
                                            ),
                                        }
                                        if conversation_id:
                                            rejection_event["conversation_id"] = conversation_id
                                        await websocket.send_json(rejection_event)
                                else:
                                    await handle_conversation_message(
                                        websocket,
                                        msg_data,
                                        get_conversation_service,
                                        send_conversation_token,
                                        turn_router=conversation_turn_router,
                                        agent_task_submission_service=agent_task_submission_service,
                                    )
                        
                        except json.JSONDecodeError:
                            logger.error("Failed to parse JSON message")
                        except Exception as e:
                            logger.error(f"Error processing websocket action: {e}")
                        
                elif "bytes" in message:
                    await handle_audio_transcription(
                        websocket,
                        message,
                        resolve_transcription_service(),
                        send_transcription_status,
                        paste_transcribed_text,
                        Preferences
                    )
            
    except WebSocketDisconnect as e:
        logger.info(f"WebSocket disconnected: {e} (connection state: {getattr(websocket, 'client_state', 'unknown')})")
    except Exception as e:
        logger.error(f"WebSocket error: {e} (connection state: {getattr(websocket, 'client_state', 'unknown')})", exc_info=True)
    finally:
        await conversation_request_runtime.cancel_for_websocket(websocket)
        remove_connection(websocket)
        logger.info(f"[CONNECTIONS] Client disconnected: id={id(websocket)}. Total active: {len(active_connections)}") 