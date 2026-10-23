import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from api.routes.websocket import _handle_conversation_cancel_message
from api.routes.websocket_routes.conversation_request_runtime import (
    ConversationRequestRuntime,
)


@pytest.mark.asyncio
async def test_missing_request_id_is_rejected():
    websocket = SimpleNamespace(send_json=AsyncMock())
    runtime = ConversationRequestRuntime()
    submission_service = SimpleNamespace(cancel_agent_task_durably=AsyncMock())

    await _handle_conversation_cancel_message(websocket, {}, runtime, submission_service)

    websocket.send_json.assert_awaited_once_with({
        "event_type": "conversation_cancel_rejected",
        "message": "A non-empty request_id is required.",
    })
    submission_service.cancel_agent_task_durably.assert_not_awaited()


@pytest.mark.asyncio
async def test_malformed_request_id_is_rejected():
    websocket = SimpleNamespace(send_json=AsyncMock())
    runtime = ConversationRequestRuntime()
    submission_service = SimpleNamespace(cancel_agent_task_durably=AsyncMock())

    await _handle_conversation_cancel_message(
        websocket, {"request_id": ["invalid"]}, runtime, submission_service
    )

    websocket.send_json.assert_awaited_once_with({
        "event_type": "conversation_cancel_rejected",
        "message": "A non-empty request_id is required.",
    })


@pytest.mark.asyncio
async def test_no_matching_request_or_agent_task_is_rejected():
    websocket = SimpleNamespace(send_json=AsyncMock())
    runtime = ConversationRequestRuntime()
    submission_service = SimpleNamespace(cancel_agent_task_durably=AsyncMock())

    await _handle_conversation_cancel_message(
        websocket, {"request_id": "request-1"}, runtime, submission_service
    )

    websocket.send_json.assert_awaited_once_with({
        "event_type": "conversation_cancel_rejected",
        "request_id": "request-1",
        "message": "No active Conversation request matched this socket.",
    })
    submission_service.cancel_agent_task_durably.assert_not_awaited()


@pytest.mark.asyncio
async def test_direct_in_flight_request_is_canceled_without_durable_call():
    websocket = SimpleNamespace(send_json=AsyncMock())
    runtime = ConversationRequestRuntime()
    submission_service = SimpleNamespace(cancel_agent_task_durably=AsyncMock())
    gate = asyncio.Event()

    async def worker(_state):
        await gate.wait()

    assert runtime.start(websocket, "request-1", None, worker) is True

    await _handle_conversation_cancel_message(
        websocket, {"request_id": "request-1"}, runtime, submission_service
    )

    websocket.send_json.assert_not_awaited()
    submission_service.cancel_agent_task_durably.assert_not_awaited()
    gate.set()


@pytest.mark.asyncio
async def test_bound_agent_task_is_canceled_durably_without_rejection():
    websocket = SimpleNamespace(send_json=AsyncMock())
    runtime = ConversationRequestRuntime()
    submission_service = SimpleNamespace(cancel_agent_task_durably=AsyncMock())
    runtime.bind_agent_task(websocket, "request-1", "task-1")

    await _handle_conversation_cancel_message(
        websocket, {"request_id": "request-1"}, runtime, submission_service
    )

    submission_service.cancel_agent_task_durably.assert_awaited_once_with(
        "task-1",
        "User canceled Conversation request",
    )
    websocket.send_json.assert_not_awaited()


@pytest.mark.asyncio
async def test_duplicate_cancellation_of_a_bound_agent_task_is_rejected_the_second_time():
    websocket = SimpleNamespace(send_json=AsyncMock())
    runtime = ConversationRequestRuntime()
    submission_service = SimpleNamespace(cancel_agent_task_durably=AsyncMock())
    runtime.bind_agent_task(websocket, "request-1", "task-1")

    await _handle_conversation_cancel_message(
        websocket, {"request_id": "request-1"}, runtime, submission_service
    )
    await _handle_conversation_cancel_message(
        websocket, {"request_id": "request-1"}, runtime, submission_service
    )

    submission_service.cancel_agent_task_durably.assert_awaited_once()
    websocket.send_json.assert_awaited_once_with({
        "event_type": "conversation_cancel_rejected",
        "request_id": "request-1",
        "message": "No active Conversation request matched this socket.",
    })


@pytest.mark.asyncio
async def test_cancel_falls_back_to_conversation_id_when_request_id_is_unowned():
    runtime = ConversationRequestRuntime()
    owner_websocket = object()
    caller_websocket = SimpleNamespace(send_json=AsyncMock())
    gate = asyncio.Event()

    async def worker(_state):
        await gate.wait()

    assert runtime.start(owner_websocket, "owner-request", "conversation-1", worker) is True

    agent_task_submission_service = SimpleNamespace(cancel_agent_task_durably=AsyncMock())

    await _handle_conversation_cancel_message(
        caller_websocket,
        {"request_id": "caller-request", "conversation_id": "conversation-1"},
        runtime,
        agent_task_submission_service,
    )

    caller_websocket.send_json.assert_not_awaited()
    gate.set()


@pytest.mark.asyncio
async def test_cancel_rejects_when_neither_request_id_nor_conversation_id_match():
    runtime = ConversationRequestRuntime()
    caller_websocket = SimpleNamespace(send_json=AsyncMock())
    agent_task_submission_service = SimpleNamespace(cancel_agent_task_durably=AsyncMock())

    await _handle_conversation_cancel_message(
        caller_websocket,
        {"request_id": "caller-request", "conversation_id": "conversation-unknown"},
        runtime,
        agent_task_submission_service,
    )

    caller_websocket.send_json.assert_awaited_once_with({
        "event_type": "conversation_cancel_rejected",
        "request_id": "caller-request",
        "message": "No active Conversation request matched this socket.",
    })
