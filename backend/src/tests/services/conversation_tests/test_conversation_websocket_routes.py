from types import SimpleNamespace
from unittest.mock import AsyncMock
import asyncio

import pytest

from api.routes.websocket_routes import conversation as conversation_routes
from api.routes.websocket_routes.conversation import (
    handle_conversation_message,
    send_conversation_stream_reset,
)
from api.services.conversation.conversation_agent_status_contract import (
    build_conversation_agent_status_payload,
)
from api.services.conversation.conversation_turn_contract import ConversationTurnLifecycle
from api.routes.websocket_routes.conversation_request_runtime import (
    ConversationRequestRuntime,
    ConversationRequestState,
)
from api.services.conversation.conversation_turn_router import (
    AgentTaskConversationTurn,
    DirectConversationTurn,
)


def build_service():
    service = SimpleNamespace(
        create_conversation=AsyncMock(
            return_value=SimpleNamespace(id="created-conversation")
        ),
        send_message=AsyncMock(),
    )
    return service


def streaming_service(chunks, on_close=None):
    service = build_service()

    async def send_message_streaming(**kwargs):
        service.streaming_kwargs = kwargs
        try:
            for chunk in chunks:
                yield chunk
        finally:
            if on_close is not None:
                on_close()

    service.send_message_streaming = send_message_streaming
    return service


@pytest.mark.asyncio
async def test_streaming_forwards_plain_content_metadata_files_and_request_id():
    websocket = SimpleNamespace(send_json=AsyncMock())
    service = streaming_service([
        {
            "token": "Hello",
            "message_id": "assistant-1",
            "conversation_id": "conversation-1",
        },
        {
            "token": "",
            "message_id": "assistant-1",
            "conversation_id": "conversation-1",
            "is_final": True,
        },
    ])
    send_token = AsyncMock()

    await handle_conversation_message(
        websocket,
        {
            "type": "conversation_message",
            "message": "Hello Basil",
            "display_markdown": "**Hello** Basil",
            "request_id": "request-1",
            "conversation_id": "conversation-1",
            "message_id": "client-message-1",
            "model_id": "model-1",
            "file_paths": ["/tmp/a.txt"],
            "use_streaming": True,
            "delegation_opt_out": True,
        },
        lambda: service,
        send_token,
    )

    assert service.streaming_kwargs == {
        "conversation_id": "conversation-1",
        "content": "Hello Basil",
        "model_id": "model-1",
        "file_paths": ["/tmp/a.txt"],
        "message_metadata": {
            "surface": "basil_board_chats",
            "request_id": "request-1",
            "display_markdown": "**Hello** Basil",
            "delegation_opt_out": True,
        },
        "on_persistence_ready": None,
    }
    assert websocket.send_json.await_args_list[0].args[0] == {
        "event_type": "conversation_message_accepted",
        "status": "success",
        "message": "Message received",
        "request_id": "request-1",
    }
    assert send_token.await_args_list[0].kwargs == {
        "token": "Hello",
        "message_id": "assistant-1",
        "conversation_id": "conversation-1",
        "is_final": False,
        "request_id": "request-1",
    }
    assert send_token.await_args_list[-1].kwargs == {
        "token": "",
        "message_id": "assistant-1",
        "conversation_id": "conversation-1",
        "is_final": True,
        "request_id": "request-1",
    }
    assert send_token.await_count == 2


@pytest.mark.asyncio
async def test_non_streaming_forwards_metadata_and_echoes_request_id():
    websocket = SimpleNamespace(send_json=AsyncMock())
    service = build_service()
    service.send_message.return_value = SimpleNamespace(
        message=SimpleNamespace(id="assistant-1", content="Response")
    )

    await handle_conversation_message(
        websocket,
        {
            "message": "Plain input",
            "display_markdown": "*Plain* input",
            "request_id": "request-1",
            "conversation_id": "conversation-1",
            "use_streaming": False,
        },
        lambda: service,
        AsyncMock(),
    )

    service.send_message.assert_awaited_once_with(
        conversation_id="conversation-1",
        content="Plain input",
        model_id=None,
        file_paths=None,
        message_metadata={
            "surface": "basil_board_chats",
            "request_id": "request-1",
            "display_markdown": "*Plain* input",
            "delegation_opt_out": False,
        },
    )
    assert websocket.send_json.await_args_list[-1].args[0] == {
        "event_type": "conversation_message",
        "message": "Response",
        "message_id": "assistant-1",
        "conversation_id": "conversation-1",
        "model_id": None,
        "request_id": "request-1",
    }


@pytest.mark.asyncio
async def test_omitted_markdown_forwards_request_metadata_only():
    websocket = SimpleNamespace(send_json=AsyncMock())
    service = build_service()
    service.send_message.return_value = SimpleNamespace(
        message=SimpleNamespace(id="assistant-1", content="Response")
    )

    await handle_conversation_message(
        websocket,
        {
            "message": "Plain input",
            "request_id": "request-1",
            "conversation_id": "conversation-1",
            "use_streaming": False,
        },
        lambda: service,
        AsyncMock(),
    )

    assert service.send_message.await_args.kwargs["message_metadata"] == {
        "surface": "basil_board_chats",
        "request_id": "request-1",
        "delegation_opt_out": False,
    }


@pytest.mark.asyncio
async def test_omitted_or_malformed_optional_metadata_is_not_forwarded():
    websocket = SimpleNamespace(send_json=AsyncMock())
    service = build_service()
    service.send_message.return_value = SimpleNamespace(
        message=SimpleNamespace(id="assistant-1", content="Response")
    )

    await handle_conversation_message(
        websocket,
        {
            "message": "Plain input",
            "display_markdown": 42,
            "request_id": ["invalid"],
            "delegation_opt_out": "true",
            "conversation_id": "conversation-1",
            "use_streaming": False,
        },
        lambda: service,
        AsyncMock(),
    )

    assert service.send_message.await_args.kwargs["message_metadata"] == {
        "surface": "basil_board_chats",
        "delegation_opt_out": False,
    }
    assert "request_id" not in websocket.send_json.await_args_list[0].args[0]
    assert "request_id" not in websocket.send_json.await_args_list[-1].args[0]


@pytest.mark.asyncio
async def test_attachments_allow_empty_text_and_create_a_conversation():
    websocket = SimpleNamespace(send_json=AsyncMock())
    service = build_service()
    service.send_message.return_value = SimpleNamespace(
        message=SimpleNamespace(id="assistant-1", content="Read the file")
    )

    await handle_conversation_message(
        websocket,
        {
            "message": "",
            "request_id": "request-1",
            "file_paths": ["/tmp/a.txt"],
            "use_streaming": False,
        },
        lambda: service,
        AsyncMock(),
    )

    service.create_conversation.assert_awaited_once()
    assert service.send_message.await_args.kwargs["conversation_id"] == "created-conversation"
    assert service.send_message.await_args.kwargs["file_paths"] == ["/tmp/a.txt"]


@pytest.mark.asyncio
async def test_empty_message_rejection_echoes_request_id():
    websocket = SimpleNamespace(send_json=AsyncMock())
    service = build_service()

    await handle_conversation_message(
        websocket,
        {
            "message": "",
            "request_id": "request-1",
            "file_paths": [],
        },
        lambda: service,
        AsyncMock(),
    )

    websocket.send_json.assert_awaited_once_with({
        "event_type": "conversation_message_rejected",
        "status": "error",
        "message": "Empty message received",
        "request_id": "request-1",
    })
    service.create_conversation.assert_not_awaited()
    service.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_service_failure_emits_correlated_conversation_error():
    websocket = SimpleNamespace(send_json=AsyncMock())
    service = build_service()
    service.send_message.side_effect = RuntimeError("model unavailable")

    await handle_conversation_message(
        websocket,
        {
            "message": "Hello",
            "request_id": "request-1",
            "conversation_id": "conversation-1",
            "use_streaming": False,
        },
        lambda: service,
        AsyncMock(),
    )

    assert websocket.send_json.await_args_list[-1].args[0] == {
        "event_type": "conversation_error",
        "message": "Error: model unavailable",
        "conversation_id": "conversation-1",
        "request_id": "request-1",
    }


@pytest.mark.asyncio
async def test_streaming_failure_emits_correlated_conversation_error():
    websocket = SimpleNamespace(send_json=AsyncMock())
    service = build_service()

    async def failing_stream(**_kwargs):
        raise RuntimeError("stream interrupted")
        yield

    service.send_message_streaming = failing_stream

    await handle_conversation_message(
        websocket,
        {
            "message": "Hello",
            "request_id": "request-1",
            "conversation_id": "conversation-1",
            "use_streaming": True,
        },
        lambda: service,
        AsyncMock(),
    )

    assert websocket.send_json.await_args_list[-1].args[0] == {
        "event_type": "conversation_error",
        "message": "Error in streaming: stream interrupted",
        "conversation_id": "conversation-1",
        "request_id": "request-1",
    }


@pytest.mark.asyncio
async def test_streaming_failure_flushes_existing_token_buffer():
    websocket = SimpleNamespace(send_json=AsyncMock())
    service = build_service()

    async def failing_stream(**_kwargs):
        yield {
            "token": "Hi",
            "message_id": "assistant-1",
            "conversation_id": "conversation-1",
        }
        raise RuntimeError("stream interrupted")

    service.send_message_streaming = failing_stream
    send_token = AsyncMock()

    await handle_conversation_message(
        websocket,
        {
            "message": "Hello",
            "request_id": "request-1",
            "conversation_id": "conversation-1",
            "use_streaming": True,
        },
        lambda: service,
        send_token,
    )

    assert send_token.await_args_list[-1].kwargs == {
        "token": "",
        "message_id": "assistant-1",
        "conversation_id": "conversation-1",
        "is_final": True,
        "request_id": "request-1",
    }


@pytest.mark.asyncio
async def test_terminal_error_chunk_uses_correlated_error_contract():
    websocket = SimpleNamespace(send_json=AsyncMock())
    stream_closed = False

    def mark_stream_closed():
        nonlocal stream_closed
        stream_closed = True

    service = streaming_service([
        {
            "token": "Error: model failed",
            "message_id": "assistant-1",
            "conversation_id": "conversation-1",
            "error": True,
            "is_final": True,
        },
    ], on_close=mark_stream_closed)
    send_token = AsyncMock()

    await handle_conversation_message(
        websocket,
        {
            "message": "Hello",
            "request_id": "request-1",
            "conversation_id": "conversation-1",
            "use_streaming": True,
        },
        lambda: service,
        send_token,
    )

    assert websocket.send_json.await_args_list[-1].args[0] == {
        "event_type": "conversation_error",
        "message": "Error: model failed",
        "conversation_id": "conversation-1",
        "request_id": "request-1",
    }
    send_token.assert_awaited_once_with(
        token="",
        message_id="assistant-1",
        conversation_id="conversation-1",
        is_final=True,
        request_id="request-1",
    )
    assert stream_closed is True


@pytest.mark.asyncio
async def test_streaming_forwards_direct_pair_callback_to_runtime_after_service_persistence():
    websocket = SimpleNamespace(send_json=AsyncMock())
    runtime = ConversationRequestRuntime()
    request_state = ConversationRequestState(
        websocket=websocket,
        request_id="request-1",
        conversation_id="conversation-1",
    )
    service = build_service()

    async def send_message_streaming(**kwargs):
        service.streaming_kwargs = kwargs
        callback = kwargs["on_persistence_ready"]
        assert callback is not None
        callback("user-1", "assistant-1")
        yield {
            "token": "Hello",
            "message_id": "assistant-1",
            "conversation_id": "conversation-1",
        }
        yield {
            "token": "",
            "message_id": "assistant-1",
            "conversation_id": "conversation-1",
            "is_final": True,
        }

    service.send_message_streaming = send_message_streaming
    send_token = AsyncMock()

    await handle_conversation_message(
        websocket,
        {
            "message": "Hello",
            "request_id": "request-1",
            "conversation_id": "conversation-1",
            "use_streaming": True,
        },
        lambda: service,
        send_token,
        request_state=request_state,
        request_runtime=runtime,
    )

    assert request_state.conversation_id == "conversation-1"
    assert request_state.user_message_id == "user-1"
    assert request_state.assistant_message_id == "assistant-1"
    assert request_state.persistence_ready is True


@pytest.mark.asyncio
async def test_streaming_cancellation_emits_single_event_and_skips_final_token(monkeypatch):
    from api.routes.websocket_routes import conversation as conversation_module

    websocket = SimpleNamespace(send_json=AsyncMock())
    broadcast = AsyncMock()
    monkeypatch.setattr(conversation_module, "broadcast_conversation_canceled", broadcast)
    service = build_service()

    async def canceled_stream(**kwargs):
        service.streaming_kwargs = kwargs
        yield {
            "token": "Partial",
            "message_id": "assistant-1",
            "conversation_id": "conversation-1",
        }
        raise asyncio.CancelledError()

    service.send_message_streaming = canceled_stream
    send_token = AsyncMock()

    await handle_conversation_message(
        websocket,
        {
            "message": "Hello",
            "request_id": "request-1",
            "conversation_id": "conversation-1",
            "use_streaming": True,
        },
        lambda: service,
        send_token,
    )

    broadcast.assert_awaited_once_with({
        "event_type": "conversation_canceled",
        "conversation_id": "conversation-1",
        "message_id": "assistant-1",
        "request_id": "request-1",
        "canceled": True,
    })
    assert all(
        call.kwargs.get("is_final") is not True
        for call in send_token.await_args_list
    )
    assert conversation_module.send_conversation_token_buffer == {}
    assert conversation_module.send_conversation_token_chunk_counter == {}


@pytest.mark.asyncio
async def test_send_conversation_stream_reset_clears_buffer_and_broadcasts_once(monkeypatch):
    conversation_routes.send_conversation_token_buffer["assistant-1"] = "partial"
    conversation_routes.send_conversation_token_chunk_counter["assistant-1"] = 3
    connection_a = SimpleNamespace(send_json=AsyncMock())
    connection_b = SimpleNamespace(send_json=AsyncMock())
    monkeypatch.setattr(
        conversation_routes,
        "active_connections",
        [connection_a, connection_b],
    )

    await send_conversation_stream_reset("assistant-1", "conversation-1", 2)

    assert "assistant-1" not in conversation_routes.send_conversation_token_buffer
    assert "assistant-1" not in conversation_routes.send_conversation_token_chunk_counter
    for connection in (connection_a, connection_b):
        connection.send_json.assert_awaited_once()
        sent_event = connection.send_json.await_args.args[0]
        assert sent_event["event_type"] == "conversation_stream_reset"
        assert sent_event["message_id"] == "assistant-1"
        assert sent_event["conversation_id"] == "conversation-1"
        assert sent_event["attempt_count"] == 2
        assert isinstance(sent_event["timestamp"], float)


@pytest.mark.asyncio
async def test_send_conversation_stream_reset_rejects_invalid_arguments():
    with pytest.raises(ValueError, match="message_id must be a non-empty string"):
        await send_conversation_stream_reset("", "conversation-1", 1)
    with pytest.raises(ValueError, match="conversation_id must be a non-empty string"):
        await send_conversation_stream_reset("assistant-1", "", 1)
    with pytest.raises(ValueError, match="attempt_count must be a positive integer"):
        await send_conversation_stream_reset("assistant-1", "conversation-1", 0)


def build_turn_router(turn):
    async def route_turn(_request, *, on_link_persisted=None):
        if isinstance(turn, AgentTaskConversationTurn) and on_link_persisted is not None:
            await on_link_persisted(SimpleNamespace(
                conversation_id=turn.conversation_id,
                assistant_message_id=turn.assistant_message_id,
                agent_task_id=turn.agent_task_id,
            ))
        return turn

    return SimpleNamespace(route_turn=AsyncMock(side_effect=route_turn))


@pytest.mark.asyncio
async def test_agent_task_turn_sends_only_acknowledgment_and_binds_runtime_mapping():
    websocket = SimpleNamespace(send_json=AsyncMock())
    runtime = ConversationRequestRuntime()
    request_state = ConversationRequestState(
        websocket=websocket,
        request_id="request-1",
        conversation_id=None,
    )
    turn_router = build_turn_router(
        AgentTaskConversationTurn(
            conversation_id="conversation-1",
            user_message_id="user-1",
            assistant_message_id="assistant-1",
            agent_task_id="task-1",
        )
    )
    submission_service = SimpleNamespace(cancel_agent_task_durably=AsyncMock())

    await handle_conversation_message(
        websocket,
        {
            "message": "Draft the release notes.",
            "request_id": "request-1",
            "use_streaming": False,
        },
        lambda: build_service(),
        AsyncMock(),
        request_state=request_state,
        request_runtime=runtime,
        turn_router=turn_router,
        agent_task_submission_service=submission_service,
    )

    assert len(websocket.send_json.await_args_list) == 2
    assert websocket.send_json.await_args_list[0].args[0] == {
        "event_type": "conversation_message_accepted",
        "status": "success",
        "message": "Message received",
        "request_id": "request-1",
    }
    correlated_status = websocket.send_json.await_args_list[1].args[0]
    assert correlated_status["event_type"] == "conversation_agent_status"
    assert correlated_status["conversation_id"] == "conversation-1"
    assert correlated_status["request_id"] == "request-1"
    assert correlated_status["requires_user_attention"] is False
    assert request_state.conversation_id == "conversation-1"
    assert runtime.claim_agent_task_cancellation(websocket, "request-1") == "task-1"
    submission_service.cancel_agent_task_durably.assert_not_awaited()


def test_correlated_status_retains_attention_fields_when_request_id_is_added():
    payload = build_conversation_agent_status_payload(
        conversation_id="conversation-1",
        placeholder_message_id="assistant-1",
        agent_task_id="task-1",
        lifecycle=ConversationTurnLifecycle.RUNNING,
        status_text="Agent task needs your input.",
        terminal_outcome=None,
        requires_user_attention=True,
        attention_id="checkpoint-1",
    )
    payload["request_id"] = "request-1"
    assert payload["requires_user_attention"] is True
    assert payload["attention_id"] == "checkpoint-1"


@pytest.mark.asyncio
async def test_agent_task_turn_cancels_durably_when_cancel_requested_before_binding():
    websocket = SimpleNamespace(send_json=AsyncMock())
    runtime = ConversationRequestRuntime()
    request_state = ConversationRequestState(
        websocket=websocket,
        request_id="request-1",
        conversation_id=None,
        cancel_requested=True,
    )
    turn_router = build_turn_router(
        AgentTaskConversationTurn(
            conversation_id="conversation-1",
            user_message_id="user-1",
            assistant_message_id="assistant-1",
            agent_task_id="task-1",
        )
    )
    submission_service = SimpleNamespace(cancel_agent_task_durably=AsyncMock())

    await handle_conversation_message(
        websocket,
        {
            "message": "Draft the release notes.",
            "request_id": "request-1",
            "use_streaming": False,
        },
        lambda: build_service(),
        AsyncMock(),
        request_state=request_state,
        request_runtime=runtime,
        turn_router=turn_router,
        agent_task_submission_service=submission_service,
    )

    submission_service.cancel_agent_task_durably.assert_awaited_once_with(
        "task-1",
        "User canceled Conversation request",
    )
    assert runtime.claim_agent_task_cancellation(websocket, "request-1") is None


@pytest.mark.asyncio
async def test_direct_turn_via_router_preserves_existing_streaming_contract():
    websocket = SimpleNamespace(send_json=AsyncMock())
    service = streaming_service([
        {
            "token": "Hi",
            "message_id": "assistant-1",
            "conversation_id": "conversation-1",
        },
        {
            "token": "",
            "message_id": "assistant-1",
            "conversation_id": "conversation-1",
            "is_final": True,
        },
    ])
    turn_router = build_turn_router(
        DirectConversationTurn(
            conversation_id="conversation-1",
            content="Hello",
            model_id=None,
            file_paths=None,
            message_metadata={"surface": "basil_board_chats", "request_id": "request-1"},
            use_streaming=True,
        )
    )
    send_token = AsyncMock()

    await handle_conversation_message(
        websocket,
        {
            "message": "Hello",
            "request_id": "request-1",
            "conversation_id": "conversation-1",
            "use_streaming": True,
        },
        lambda: service,
        send_token,
        turn_router=turn_router,
        agent_task_submission_service=SimpleNamespace(cancel_agent_task_durably=AsyncMock()),
    )

    assert service.streaming_kwargs["conversation_id"] == "conversation-1"
    assert send_token.await_count == 2
