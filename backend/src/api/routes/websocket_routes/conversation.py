import logging
import time
import uuid
from typing import Any, Optional, TYPE_CHECKING
from enum import Enum
from api.services.websocket_connection_manager import active_connections
from ...models.websocket_events import HistoryChatEvent
import asyncio
from ...services.conversation.conversation_turn_router import (
    DEFAULT_CONVERSATION_SYSTEM_MESSAGE,
    AgentTaskConversationTurn,
    ConversationTurnAlreadyActiveError,
    ConversationTurnRequest,
    DirectConversationTurn,
)
from ...services.conversation.conversation_agent_status_contract import (
    build_conversation_agent_status_payload,
)
from ...services.conversation.conversation_turn_contract import ConversationTurnLifecycle

if TYPE_CHECKING:
    from .conversation_request_runtime import ConversationRequestRuntime, ConversationRequestState
    from ...services.conversation.conversation_turn_router import ConversationTurnRouter

logger = logging.getLogger(__name__)

# Add a buffer and chunk counter to collect tokens before sending
send_conversation_token_buffer = {}
send_conversation_token_chunk_counter = {}


def discard_conversation_token_state(message_id: Optional[str]) -> None:
    if not message_id:
        return
    send_conversation_token_buffer.pop(message_id, None)
    send_conversation_token_chunk_counter.pop(message_id, None)


async def send_conversation_stream_reset(
    message_id: str,
    conversation_id: str,
    attempt_count: int,
) -> None:
    """Clear buffered tokens and tell clients to discard partial narration output."""
    if not isinstance(message_id, str) or not message_id.strip():
        raise ValueError("message_id must be a non-empty string")
    if not isinstance(conversation_id, str) or not conversation_id.strip():
        raise ValueError("conversation_id must be a non-empty string")
    if not isinstance(attempt_count, int) or isinstance(attempt_count, bool) or attempt_count < 1:
        raise ValueError("attempt_count must be a positive integer")
    discard_conversation_token_state(message_id)
    event = {
        "event_type": "conversation_stream_reset",
        "message_id": message_id,
        "conversation_id": conversation_id,
        "attempt_count": attempt_count,
        "timestamp": time.time(),
    }
    for connection in active_connections:
        try:
            await connection.send_json(event)
        except Exception as e:
            logger.error(f"Error sending conversation stream reset to connection {id(connection)}: {e}")


async def broadcast_conversation_canceled(event: dict[str, Any]) -> None:
    """Deliver one correlated conversation_canceled event to every open Conversation socket."""
    for connection in active_connections:
        try:
            await connection.send_json(event)
        except Exception as exc:
            logger.error(f"Error broadcasting conversation cancellation to connection {id(connection)}: {exc}")


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
        logger.warning(f"No message_type provided, defaulting to 'assistant'")
    if message == "I couldn't find any activities matching your query.":
        logger.info(f"Sending 'no results found' message with message_type={message_type}, is_loading={is_loading}")
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
    logger.info(f"Sending history chat event: active={active}, message_type={message_type}, is_loading={is_loading}")
    logger.info(f"Event data: {event.dict()}")
    logger.info(f"[CONNECTIONS] Active connections before send: " + ", ".join([
        f"id={id(conn)} state={getattr(conn, 'client_state', 'unknown')}" for conn in active_connections
    ]))
    for connection in active_connections:
        try:
            event_dict = event.dict()
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
                logger.info(f"[CANARY] About to send CANARY message to connection {id(connection)}: {canary_event} (connection state: {getattr(connection, 'client_state', 'unknown')})")
                await connection.send_json(canary_event)
                logger.info(f"[CANARY] Successfully sent CANARY message to connection {id(connection)}: {canary_event} (connection state: {getattr(connection, 'client_state', 'unknown')})")
            logger.info(f"[ANALYSIS] About to send analysis event to connection {id(connection)}: {event_dict} (connection state: {getattr(connection, 'client_state', 'unknown')})")
            await connection.send_json(event_dict)
            logger.info(f"[ANALYSIS] Successfully sent analysis event to connection {id(connection)}: {event_dict} (connection state: {getattr(connection, 'client_state', 'unknown')})")
        except Exception as e:
            logger.error(f"[ANALYSIS] Error sending analysis event to connection {id(connection)}: {event_dict}; Exception: {e} (connection state: {getattr(connection, 'client_state', 'unknown')})", exc_info=True)

async def send_conversation_token(
    token: str,
    message_id: str,
    conversation_id: str,
    is_final: bool = False,
    request_id: Optional[str] = None,
):
    """Send a streaming token for a regular conversation (not history chat)."""
    global send_conversation_token_buffer, send_conversation_token_chunk_counter
    # Use message_id as the buffer key
    buf = send_conversation_token_buffer.setdefault(message_id, "")
    chunk_counter = send_conversation_token_chunk_counter.setdefault(message_id, 0)
    buf += token
    send_conversation_token_buffer[message_id] = buf  # Update buffer
    
    # Log only every 20th chunk (~5% of tokens) or on final/start
    should_log = (chunk_counter % 20 == 0) or is_final or chunk_counter == 0
    
    flush = False
    if len(buf) >= 3 or is_final:
        flush = True
    
    if flush and (len(buf) > 0 or is_final):  # Only send if we have content OR it's the final marker
        event = {
            "event_type": "conversation_token",
            "token": buf,
            "message_id": message_id,
            "conversation_id": conversation_id,
            "is_final": is_final,
            "chunk_id": chunk_counter,
            "timestamp": time.time(),
        }
        if request_id:
            event["request_id"] = request_id
        if should_log:
            logger.info(f"[TOKEN SEND] chunk_id={chunk_counter}, {len(buf)} chars, is_final={is_final}")
        
        for connection in active_connections:
            try:
                await connection.send_json(event)
            except Exception as e:
                logger.error(f"Error sending conversation token to connection {id(connection)}: {e}")
        
        # Reset buffer and increment counter after successful send
        send_conversation_token_buffer[message_id] = ""
        send_conversation_token_chunk_counter[message_id] = chunk_counter + 1
        
        if is_final:
            # Clear everything on final
            send_conversation_token_buffer.pop(message_id, None)
            send_conversation_token_chunk_counter.pop(message_id, None)

async def handle_conversation_message(
    websocket,
    msg_data,
    get_conversation_service,
    send_conversation_token,
    request_state: Optional["ConversationRequestState"] = None,
    request_runtime: Optional["ConversationRequestRuntime"] = None,
    turn_router: Optional["ConversationTurnRouter"] = None,
    agent_task_submission_service: Optional[Any] = None,
):
    logger.info("Received direct conversation message")
    message = msg_data.get("message", "")
    context = msg_data.get("context")
    conversation_id = msg_data.get("conversation_id")
    message_id = msg_data.get("message_id", str(uuid.uuid4()))
    use_streaming = msg_data.get("use_streaming", False)
    model_id = msg_data.get("model_id")
    file_paths = msg_data.get("file_paths", [])
    raw_request_id = msg_data.get("request_id")
    request_id = raw_request_id.strip() if isinstance(raw_request_id, str) and raw_request_id.strip() else None
    raw_display_markdown = msg_data.get("display_markdown")
    display_markdown = (
        raw_display_markdown.strip()
        if isinstance(raw_display_markdown, str) and raw_display_markdown.strip()
        else None
    )
    delegation_opt_out = msg_data.get("delegation_opt_out") is True
    message_metadata = {
        key: value
        for key, value in {
            "surface": "basil_board_chats",
            "request_id": request_id,
            "display_markdown": display_markdown,
            "delegation_opt_out": delegation_opt_out,
        }.items()
        if value is not None
    }

    if file_paths:
        logger.info(f"Message includes {len(file_paths)} file attachments: {file_paths}")

    if not message and not file_paths:
        logger.warning("Received empty message with no files")
        rejection = {
            "event_type": "conversation_message_rejected",
            "status": "error",
            "message": "Empty message received",
        }
        if request_id:
            rejection["request_id"] = request_id
        await websocket.send_json(rejection)
        return

    if model_id:
        logger.info(f"Using explicitly selected model: {model_id}")

    acknowledgment = {
        "event_type": "conversation_message_accepted",
        "status": "success",
        "message": "Message received",
    }
    if request_id:
        acknowledgment["request_id"] = request_id
    await websocket.send_json(acknowledgment)

    try:
        conversation_service = get_conversation_service()
        if turn_router is not None:
            async def on_agent_task_link_persisted(link) -> None:
                if request_state is None or request_runtime is None:
                    return
                if not request_runtime.associate_conversation(request_state, link.conversation_id):
                    raise ConversationTurnAlreadyActiveError(link.conversation_id)
                request_runtime.bind_agent_task(
                    websocket,
                    request_state.request_id,
                    link.agent_task_id,
                )
                correlated_status = build_conversation_agent_status_payload(
                    conversation_id=link.conversation_id,
                    placeholder_message_id=link.assistant_message_id,
                    agent_task_id=link.agent_task_id,
                    lifecycle=ConversationTurnLifecycle.PENDING,
                    status_text="Preparing agent task",
                    terminal_outcome=None,
                    agent_status="pending",
                    narration_state="pending",
                )
                correlated_status["request_id"] = request_state.request_id
                await websocket.send_json(correlated_status)
                if request_state.cancel_requested and agent_task_submission_service is not None:
                    claimed_agent_task_id = request_runtime.claim_agent_task_cancellation(
                        websocket,
                        request_state.request_id,
                    )
                    if claimed_agent_task_id is not None:
                        await agent_task_submission_service.cancel_agent_task_durably(
                            claimed_agent_task_id,
                            "User canceled Conversation request",
                        )

            routed_turn = await turn_router.route_turn(
                ConversationTurnRequest(
                    content=message,
                    conversation_id=conversation_id or None,
                    model_id=model_id,
                    file_paths=file_paths if file_paths else None,
                    message_metadata=message_metadata,
                    display_prompt_markdown=display_markdown,
                    delegation_opt_out=delegation_opt_out,
                    use_streaming=use_streaming,
                ),
                on_link_persisted=on_agent_task_link_persisted,
            )
        else:
            if not conversation_id:
                logger.info("No conversation ID provided, creating new conversation")
                created_conversation = await conversation_service.create_conversation(
                    system_message=DEFAULT_CONVERSATION_SYSTEM_MESSAGE
                )
                conversation_id = created_conversation.id
                logger.info(f"Created new conversation with ID: {conversation_id}")
            routed_turn = DirectConversationTurn(
                conversation_id=conversation_id,
                content=message,
                model_id=model_id,
                file_paths=file_paths if file_paths else None,
                message_metadata=message_metadata,
                use_streaming=use_streaming,
            )

        conversation_id = routed_turn.conversation_id
        if request_state is not None and request_runtime is not None:
            if not request_runtime.associate_conversation(request_state, conversation_id):
                conflict_event = {
                    "event_type": "conversation_error",
                    "message": "A response is already active for this conversation.",
                    "conversation_id": conversation_id,
                }
                if request_id:
                    conflict_event["request_id"] = request_id
                await websocket.send_json(conflict_event)
                return

        if isinstance(routed_turn, AgentTaskConversationTurn):
            return

        if routed_turn.use_streaming:
            logger.info("Using streaming for conversation response")
            try:
                # Use actual streaming generator
                streaming_msg_id = None
                terminal_error_sent = False

                async for chunk in conversation_service.send_message_streaming(
                    conversation_id=routed_turn.conversation_id,
                    content=routed_turn.content,
                    model_id=routed_turn.model_id,
                    file_paths=routed_turn.file_paths,
                    message_metadata=routed_turn.message_metadata,
                    on_persistence_ready=(
                        (
                            lambda user_id, assistant_id: request_runtime.mark_persistence_ready(
                                request_state,
                                user_id,
                                assistant_id,
                            )
                        )
                        if request_state and request_runtime
                        else None
                    ),
                ):
                    # Extract token and message_id from the chunk.
                    token = chunk.get("token", "")
                    if streaming_msg_id is None:
                        streaming_msg_id = chunk.get("message_id")
                    if request_state is not None and streaming_msg_id is not None:
                        request_state.assistant_message_id = streaming_msg_id

                    if terminal_error_sent:
                        continue
                    if chunk.get("error"):
                        error_event = {
                            "event_type": "conversation_error",
                            "message": token or "The streaming response failed.",
                            "conversation_id": conversation_id,
                        }
                        if request_id:
                            error_event["request_id"] = request_id
                        await websocket.send_json(error_event)
                        await send_conversation_token(
                            token="",
                            message_id=streaming_msg_id,
                            conversation_id=conversation_id,
                            is_final=True,
                            request_id=request_id,
                        )
                        terminal_error_sent = True
                        continue
                    if chunk.get("is_final") and not token:
                        continue

                    # send_conversation_token already batches to 3+ chars, just pass through.
                    await send_conversation_token(
                        token=token,
                        message_id=streaming_msg_id,
                        conversation_id=conversation_id,
                        is_final=False,
                        request_id=request_id,
                    )

                if terminal_error_sent:
                    return
                # Send final marker.
                await send_conversation_token(
                    token="",
                    message_id=streaming_msg_id,
                    conversation_id=conversation_id,
                    is_final=True,
                    request_id=request_id,
                )
                logger.info(f"Streaming completed for message ID: {streaming_msg_id}")
            except asyncio.CancelledError:
                discard_conversation_token_state(streaming_msg_id)
                cancellation_event = {
                    "event_type": "conversation_canceled",
                    "conversation_id": conversation_id,
                    "message_id": streaming_msg_id,
                    "request_id": request_id,
                    "canceled": True,
                }
                await broadcast_conversation_canceled(cancellation_event)
                return
            except Exception as e:
                logger.error(f"Error in streaming: {e}")
                error_event = {
                    "event_type": "conversation_error",
                    "message": f"Error in streaming: {str(e)}",
                    "conversation_id": conversation_id,
                }
                if request_id:
                    error_event["request_id"] = request_id
                await websocket.send_json(error_event)
                if streaming_msg_id is not None:
                    await send_conversation_token(
                        token="",
                        message_id=streaming_msg_id,
                        conversation_id=conversation_id,
                        is_final=True,
                        request_id=request_id,
                    )
        else:
            response = await conversation_service.send_message(
                conversation_id=routed_turn.conversation_id,
                content=routed_turn.content,
                model_id=routed_turn.model_id,
                file_paths=routed_turn.file_paths,
                message_metadata=routed_turn.message_metadata,
            )
            terminal_event = {
                "event_type": "conversation_message",
                "message": response.message.content,
                "message_id": response.message.id,
                "conversation_id": conversation_id,
                "model_id": model_id,
            }
            if request_id:
                terminal_event["request_id"] = request_id
            await websocket.send_json(terminal_event)
            logger.info(f"Sent response from Conversation Service: {response.message.content[:50]}...")
    except ConversationTurnAlreadyActiveError as exc:
        logger.info("Rejected Conversation turn for an already-active conversation: %s", exc.conversation_id)
        error_event = {
            "event_type": "conversation_error",
            "message": "A response is already active for this conversation.",
            "conversation_id": exc.conversation_id,
        }
        if request_id:
            error_event["request_id"] = request_id
        await websocket.send_json(error_event)
    except Exception as e:
        logger.error(f"Error processing conversation message: {e}")
        error_event = {
            "event_type": "conversation_error",
            "message": f"Error: {str(e)}",
            "conversation_id": conversation_id,
        }
        if request_id:
            error_event["request_id"] = request_id
        await websocket.send_json(error_event)
