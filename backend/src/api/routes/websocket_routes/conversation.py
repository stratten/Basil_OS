import logging
import time
import uuid
from typing import Any, Optional, TYPE_CHECKING
from enum import Enum
from api.services.websocket_connection_manager import active_connections
from ...models.websocket_events import HistoryChatEvent
import asyncio
from ...core.knowledge.query.activity_summarizer import generate_activity_summary
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
from datetime import datetime, timezone

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


async def broadcast_conversation_cancelled(event: dict[str, Any]) -> None:
    """Deliver one correlated conversation_cancelled event to every open Conversation socket."""
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
            "status": "error",
            "message": "Empty message received",
        }
        if request_id:
            rejection["request_id"] = request_id
        await websocket.send_json(rejection)
        return

    if model_id:
        logger.info(f"Using explicitly selected model: {model_id}")

    acknowledgement = {
        "status": "success",
        "message": "Message received",
    }
    if request_id:
        acknowledgement["request_id"] = request_id
    await websocket.send_json(acknowledgement)

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
                            "User cancelled Conversation request",
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
                    "event_type": "conversation_cancelled",
                    "conversation_id": conversation_id,
                    "message_id": streaming_msg_id,
                    "request_id": request_id,
                    "cancelled": True,
                }
                await broadcast_conversation_cancelled(cancellation_event)
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

async def handle_history_chat_message(
    websocket,
    msg_data,
    get_conversation_service,
    get_query_intent_handler,
    model_service,
    model_usage_service,
    send_history_chat_event
):
    logger = logging.getLogger(__name__)
    logger.info("Received history chat message")
    
    message = msg_data.get("message", "")
    context = msg_data.get("context")
    query_activity_database = msg_data.get("query_activity_database", True)
    conversation_id = msg_data.get("conversation_id")
    message_id = msg_data.get("message_id", str(uuid.uuid4()))
    model_id = msg_data.get("model_id")
    
    if not message:
        logger.warning("Received empty message")
        await websocket.send_json({
            "status": "error",
            "message": "Empty message received"
        })
        return
    
    if model_id:
        logger.info(f"Using explicitly selected model for history chat: {model_id}")
    
    await websocket.send_json({
        "status": "success",
        "message": "Message received"
    })
    
    if not query_activity_database:
        logger.info("Not querying activity database, routing to Conversation Service")
        try:
            conversation_service = get_conversation_service()
            if not conversation_id:
                logger.info("No conversation ID provided, creating new conversation")
                conversation = await conversation_service.create_conversation(
                    system_message="You are Basil, an intelligent assistant designed to be genuinely helpful, conversational, and insightful. You can engage in natural conversation while also providing practical assistance. When users ask casual questions like 'How are you?', respond naturally. When they need help with tasks, provide clear, actionable guidance. Adapt your communication style to match the context - be concise when brevity is needed, detailed when complexity requires it, and always aim to be more helpful than a standard LLM interaction."
                )
                conversation_id = conversation.id
                logger.info(f"Created new conversation with ID: {conversation_id}")
            await send_history_chat_event(
                active=True,
                message=message,
                message_type="user",
                context=context,
                is_loading=False,
                message_id=message_id,
                conversation_id=conversation_id
            )
            await send_history_chat_event(
                active=True,
                message="",
                message_type="assistant",
                context=context,
                is_loading=True,
                message_id=None,
                conversation_id=conversation_id
            )
            response = await conversation_service.send_message(
                conversation_id=conversation_id, 
                content=message,
                model_id=model_id
            )
            await send_history_chat_event(
                active=True,
                message=response.message.content,
                message_type="assistant",
                context=context,
                is_loading=False,
                message_id=response.message.id,
                conversation_id=conversation_id
            )
            logger.info(f"Sent response from Conversation Service: {response.message.content[:50]}...")
        except Exception as e:
            logger.error(f"Error routing to Conversation Service: {e}")
            await send_history_chat_event(
                active=True,
                message=f"Error: {str(e)}",
                message_type="error",
                context=context,
                is_loading=False,
                message_id=None,
                conversation_id=conversation_id
            )
        return
    await send_history_chat_event(
        active=True,
        message=message,
        message_type="user",
        context=context,
        is_loading=False,
        message_id=message_id,
        conversation_id=conversation_id
    )
    conversation_service = get_conversation_service()
    is_new_conversation = not conversation_id
    if is_new_conversation:
        logger.info("No conversation ID provided, creating new conversation")
        conversation = await conversation_service.create_conversation(
            system_message="You are Basil, an intelligent assistant designed to be genuinely helpful, conversational, and insightful. You can engage in natural conversation while also providing practical assistance. When users ask casual questions like 'How are you?', respond naturally. When they need help with tasks, provide clear, actionable guidance. Adapt your communication style to match the context - be concise when brevity is needed, detailed when complexity requires it, and always aim to be more helpful than a standard LLM interaction."
        )
        conversation_id = conversation.id
        logger.info(f"Created new conversation with ID: {conversation_id}")
    await conversation_service.add_message(conversation_id, "user", message)
    if is_new_conversation:
        asyncio.ensure_future(conversation_service._auto_title_conversation(conversation_id, message))
    await send_history_chat_event(
        active=True,
        message="",
        message_type="assistant",
        context=context,
        is_loading=True,
        message_id=None,
        conversation_id=conversation_id
    )
    try:
        logger.info(f"Processing history query: '{message}'")
        logger.info(f"Options: query_activity_database={query_activity_database}")
        query_intent_handler = get_query_intent_handler()
        response = await query_intent_handler.process_query(
            query_text=message,
            model_id=model_id
        )
        
        # Check if the response contains an error
        if "error" in response:
            error_message = response.get("error", "Unknown error occurred during query processing")
            logger.error(f"Query processing failed: {error_message}")
            await send_history_chat_event(
                active=True,
                message=f"I encountered an error while processing your query: {error_message}\n\nPlease try rephrasing your request or check that the necessary AI models are available.",
                message_type="assistant",
                context=context,
                is_loading=False,
                message_id=None,
                conversation_id=conversation_id
            )
            conversation_service.add_message(conversation_id, "assistant", f"Error: {error_message}")
            return
        
        activities = response.get("activities", [])
        timeframe = response.get("timeframe", {})
        model_used = response.get("model_id")
        if model_used:
            logger.info(f"Query processed using model: {model_used}")
        if activities:
            activity_count = len(activities)
            time_desc = ""
            if timeframe:
                start_time = timeframe.get("start")
                end_time = timeframe.get("end")
                # Debug: Log the actual timestamp values we received
                logger.debug(f"Received timeframe timestamps: start={start_time!r}, end={end_time!r}")
                if start_time and end_time:
                    # Convert backend timestamps to user-friendly format
                    try:
                        # Parse and format start time - handle multiple ISO formats
                        if isinstance(start_time, str):
                            # Try different parsing approaches for ISO format variations
                            start_time_clean = start_time.replace('Z', '+00:00') if 'Z' in start_time else start_time
                            # Handle timestamps without timezone info by treating as local
                            if '+' not in start_time_clean and 'Z' not in start_time:
                                start_dt = datetime.fromisoformat(start_time_clean)
                            else:
                                start_dt = datetime.fromisoformat(start_time_clean)
                            start_formatted = start_dt.astimezone().strftime("%-m/%-d/%Y %-I:%M %p")
                        else:
                            start_formatted = start_time.strftime("%-m/%-d/%Y %-I:%M %p")
                        
                        # Parse and format end time - handle multiple ISO formats
                        if isinstance(end_time, str):
                            # Try different parsing approaches for ISO format variations
                            end_time_clean = end_time.replace('Z', '+00:00') if 'Z' in end_time else end_time
                            # Handle timestamps without timezone info by treating as local
                            if '+' not in end_time_clean and 'Z' not in end_time:
                                end_dt = datetime.fromisoformat(end_time_clean)
                            else:
                                end_dt = datetime.fromisoformat(end_time_clean)
                            end_formatted = end_dt.astimezone().strftime("%-m/%-d/%Y %-I:%M %p")
                        else:
                            end_formatted = end_time.strftime("%-m/%-d/%Y %-I:%M %p")
                        
                        time_desc = f" between {start_formatted} and {end_formatted}"
                    except Exception as e:
                        # Enhanced error logging with more details about the timestamp format
                        logger.warning(f"Failed to parse timeframe timestamps for display: start={start_time!r} (type: {type(start_time)}), end={end_time!r} (type: {type(end_time)}), error={e}")
                        # Fallback to original format if parsing fails
                        time_desc = f" between {start_time} and {end_time}"
                elif start_time:
                    try:
                        # Parse and format start time - handle multiple ISO formats
                        if isinstance(start_time, str):
                            # Try different parsing approaches for ISO format variations
                            start_time_clean = start_time.replace('Z', '+00:00') if 'Z' in start_time else start_time
                            # Handle timestamps without timezone info by treating as local
                            if '+' not in start_time_clean and 'Z' not in start_time:
                                start_dt = datetime.fromisoformat(start_time_clean)
                            else:
                                start_dt = datetime.fromisoformat(start_time_clean)
                            start_formatted = start_dt.astimezone().strftime("%-m/%-d/%Y %-I:%M %p")
                        else:
                            start_formatted = start_time.strftime("%-m/%-d/%Y %-I:%M %p")
                        time_desc = f" after {start_formatted}"
                    except Exception as e:
                        logger.warning(f"Failed to parse start timestamp for display: {start_time!r} (type: {type(start_time)}), error={e}")
                        time_desc = f" after {start_time}"
                elif end_time:
                    try:
                        # Parse and format end time - handle multiple ISO formats
                        if isinstance(end_time, str):
                            # Try different parsing approaches for ISO format variations
                            end_time_clean = end_time.replace('Z', '+00:00') if 'Z' in end_time else end_time
                            # Handle timestamps without timezone info by treating as local
                            if '+' not in end_time_clean and 'Z' not in end_time:
                                end_dt = datetime.fromisoformat(end_time_clean)
                            else:
                                end_dt = datetime.fromisoformat(end_time_clean)
                            end_formatted = end_dt.astimezone().strftime("%-m/%-d/%Y %-I:%M %p")
                        else:
                            end_formatted = end_time.strftime("%-m/%-d/%Y %-I:%M %p")
                        time_desc = f" before {end_formatted}"
                    except Exception as e:
                        logger.warning(f"Failed to parse end timestamp for display: {end_time!r} (type: {type(end_time)}), error={e}")
                        time_desc = f" before {end_time}"
            app_counts = {}
            for activity in activities:
                app_name = activity.get("app_name", "Unknown")
                app_counts[app_name] = app_counts.get(app_name, 0) + 1
            app_summary = ", ".join([f"{app} ({count})" for app, count in sorted(
                app_counts.items(), 
                key=lambda x: x[1], 
                reverse=True
            )[:5]])
            response_message = f"I found {activity_count} activities{time_desc}.\n\n"
            response_message += f"Most used applications: {app_summary}"
            if activity_count > 0:
                response_message += "\n\n**Here's what you were working on:**\n"
                for i, activity in enumerate(activities[:10]):
                    app = activity.get("app_name", "Unknown")
                    title = activity.get("window_title", "")
                    timestamp = activity.get("timestamp", "")
                    try:
                        if isinstance(timestamp, str):
                            # Parse and format timestamp - handle multiple ISO format variations
                            # Try different parsing approaches for ISO format variations
                            timestamp_clean = timestamp.replace('Z', '+00:00') if 'Z' in timestamp else timestamp
                            # Handle timestamps without timezone info by treating as UTC (since DB stores in UTC)
                            if '+' not in timestamp_clean and 'Z' not in timestamp:
                                # Assume UTC if no timezone info
                                dt = datetime.fromisoformat(timestamp_clean)
                                # Treat as UTC and convert to local timezone
                                dt = dt.replace(tzinfo=timezone.utc)
                                local_dt = dt.astimezone()
                            else:
                                # Has timezone info, parse normally
                                dt = datetime.fromisoformat(timestamp_clean)
                                local_dt = dt.astimezone()
                            timestamp = local_dt.strftime("%I:%M %p")
                        else:
                            # Direct datetime object
                            if timestamp.tzinfo is None:
                                # Assume UTC if no timezone info
                                timestamp = timestamp.replace(tzinfo=timezone.utc).astimezone()
                            else:
                                timestamp = timestamp.astimezone()
                            timestamp = timestamp.strftime("%I:%M %p")
                    except Exception as e:
                        logger.warning(f"Failed to parse activity timestamp for display: {timestamp!r} (type: {type(timestamp)}), error={e}")
                        # Keep original format if parsing fails
                        pass
                    response_message += f"\n**{i+1}. {app} at {timestamp}:**\n"
                    
                    # Helper function to format multi-line content with proper indentation
                    def format_field(label, content):
                        if not content:
                            return ""
                        # Split content into lines and handle indentation
                        lines = str(content).strip().split('\n')
                        if len(lines) == 1:
                            return f"   **{label}:** {lines[0]}\n"
                        else:
                            # First line with label, subsequent lines indented with more spaces for better alignment
                            result = f"   **{label}:** {lines[0]}\n"
                            indent = "        "  # Use 8 spaces for better visual indentation
                            for line in lines[1:]:
                                result += f"{indent}{line.strip()}\n"
                            return result
                    
                    response_message += format_field("Title", title)
                    
                    # Remove extracted text and skills to make output cleaner and less technical
                    # extracted_text = activity.get("extracted_text", "")
                    # if extracted_text and len(extracted_text) > 0:
                    #     max_length = 200
                    #     if len(extracted_text) > max_length:
                    #         extracted_text = extracted_text[:max_length] + "..."
                    #     extracted_text = " ".join(extracted_text.split())
                    #     response_message += format_field("Content", extracted_text)
                    
                    ai_analysis = activity.get("ai_analysis", {})
                    if ai_analysis and isinstance(ai_analysis, dict):
                        summary = ai_analysis.get("summary", "")
                        if summary and len(summary) > 0:
                            response_message += format_field("Summary", summary)
                        
                        activity_type = ai_analysis.get("activity_type")
                        context = ai_analysis.get("context")
                        content_summary = ai_analysis.get("content_summary")
                        # skills = ai_analysis.get("skills", [])
                        
                        if activity_type:
                            response_message += format_field("Activity Type", activity_type)
                        if context:
                            response_message += format_field("Context", context)
                        if content_summary:
                            response_message += format_field("Content Summary", content_summary)
                        # Remove skills field for cleaner output
                        # if skills and len(skills) > 0:
                        #     skills_str = ", ".join(skills[:5])
                        #     response_message += format_field("Skills", skills_str)
                if activity_count > 10:
                    response_message += f"\n...and {activity_count - 10} more activities."
        else:
            response_message = "I couldn't find any activities matching your query."
            logger.info("No activities found, sending 'no results found' message")
        logger.info(f"Sending response message: '{response_message[:50]}...' with message_type='assistant', is_loading=False")
        await send_history_chat_event(
            active=True,
            message=response_message,
            message_type="assistant",
            context=context,
            is_loading=False,
            message_id=None,
            conversation_id=conversation_id
        )
        conversation_service.add_message(conversation_id, "assistant", response_message)
        if activities and len(activities) > 0:
            logger.info(f"Starting activity summarization process for {len(activities)} activities")
            await send_history_chat_event(
                active=True,
                message="",
                message_type="assistant",
                context=context,
                is_loading=True,
                message_id=None,
                conversation_id=conversation_id
            )
            logger.info("Sent loading event for summary")
            logger.info(f"Calling generate_activity_summary with {len(activities)} activities")
            summary = await generate_activity_summary(
                activities=activities, 
                time_desc=time_desc, 
                model_service=model_service,
                model_usage_service=model_usage_service,
                model_id=model_id
            )
            logger.info(f"Summary generation completed: {summary is not None}")
            if summary:
                logger.info(f"Sending summary as follow-up message ({len(summary)} characters)")
                # Clean up markdown heading syntax that displays as literal hashtags
                cleaned_summary = summary.replace('## ', '').replace('#', '')  # Remove markdown headers
                await send_history_chat_event(
                    active=True,
                    message=cleaned_summary,
                    message_type="assistant",
                    context=context,
                    is_loading=False,
                    message_id=None,
                    conversation_id=conversation_id
                )
                conversation_service.add_message(conversation_id, "assistant", cleaned_summary)
                logger.info("Summary sent successfully")
            else:
                logger.warning("No summary was generated, skipping follow-up message")
    except Exception as e:
        logger.error(f"Error processing history query: {e}")
        await send_history_chat_event(
            active=True,
            message=f"Error: {str(e)}",
            message_type="error",
            context=context,
            is_loading=False,
            message_id=message_id,
            conversation_id=conversation_id
        )