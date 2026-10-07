"""Tests for the command-input broker and its HTTP routes."""

from __future__ import annotations

import asyncio
import contextlib

import httpx
import pytest
from fastapi import FastAPI

from api.routes.agent_tasks.command_input_routes import router as command_input_router
from api.services.agent_processing.tools.direct_application_interactions.shell.command_input_broker import (
    CommandInputBroker,
    CommandInputConflictError,
    CommandInputNotFoundError,
    validate_command_input_text,
)


class FakeWebSocketManager:
    def __init__(self, fail: bool = False):
        self.events: list[dict] = []
        self._fail = fail

    async def broadcast(self, event):
        if self._fail:
            raise RuntimeError("socket closed")
        self.events.append(event)


async def _wait_for_event(manager: FakeWebSocketManager) -> dict:
    for _ in range(200):
        requests = [event for event in manager.events if event.get("event_type") == "execution_approval_request"]
        if requests:
            return requests[-1]
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(asyncio.Event().wait(), timeout=0.01)
    raise AssertionError("no command input event was broadcast")


@pytest.fixture(autouse=True)
def _clear_pending():
    CommandInputBroker._pending.clear()
    yield
    CommandInputBroker._pending.clear()


@pytest.mark.asyncio
async def test_unavailable_without_websocket_manager():
    reply = await CommandInputBroker.request_input(
        agent_task_id="task-1", prompt="Password:", secret=True, command_echo="sudo ls", websocket_manager=None
    )
    assert reply.status == "unavailable"


@pytest.mark.asyncio
async def test_broadcast_failure_is_unavailable_and_leaves_nothing_pending():
    reply = await CommandInputBroker.request_input(
        agent_task_id="task-1",
        prompt="Password:",
        secret=True,
        command_echo="sudo ls",
        websocket_manager=FakeWebSocketManager(fail=True),
    )
    assert reply.status == "unavailable"
    assert CommandInputBroker.pending_for_task("task-1") == []


@pytest.mark.asyncio
async def test_answer_round_trip_through_the_approval_channel():
    manager = FakeWebSocketManager()
    waiter = asyncio.create_task(
        CommandInputBroker.request_input(
            agent_task_id="task-1",
            prompt="Continue? [y/N]",
            secret=False,
            command_echo="brew upgrade",
            websocket_manager=manager,
        )
    )
    event = await _wait_for_event(manager)
    assert event["event_type"] == "execution_approval_request"
    assert event["execution_type"] == "command_input"
    assert event["command"] == "brew upgrade"
    assert event["command_input"]["prompt"] == "Continue? [y/N]"
    assert event["command_input"]["secret"] is False
    request_id = event["approval_id"]
    assert [item["request_id"] for item in CommandInputBroker.pending_for_task("task-1")] == [request_id]

    CommandInputBroker.respond(request_id, action="answer", value="y\n", agent_task_id="task-1")
    reply = await waiter

    assert reply.status == "answered"
    assert reply.text == "y"
    assert CommandInputBroker.pending_for_task("task-1") == []


@pytest.mark.asyncio
async def test_cancel_and_timeout_replies():
    manager = FakeWebSocketManager()
    waiter = asyncio.create_task(
        CommandInputBroker.request_input(
            agent_task_id="task-1", prompt="Proceed?", secret=False, command_echo="x", websocket_manager=manager
        )
    )
    event = await _wait_for_event(manager)
    CommandInputBroker.respond(event["approval_id"], action="cancel")
    assert (await waiter).status == "canceled"

    timed_out = await CommandInputBroker.request_input(
        agent_task_id="task-1",
        prompt="Proceed?",
        secret=False,
        command_echo="x",
        websocket_manager=FakeWebSocketManager(),
        timeout_seconds=0.2,
    )
    assert timed_out.status == "timeout"
    assert CommandInputBroker.pending_for_task("task-1") == []


@pytest.mark.asyncio
async def test_respond_rejects_unknown_foreign_and_malformed_requests():
    with pytest.raises(CommandInputNotFoundError):
        CommandInputBroker.respond("command-input-missing", action="answer", value="x")

    manager = FakeWebSocketManager()
    waiter = asyncio.create_task(
        CommandInputBroker.request_input(
            agent_task_id="task-1", prompt="Name:", secret=False, command_echo="x", websocket_manager=manager
        )
    )
    request_id = (await _wait_for_event(manager))["approval_id"]
    with pytest.raises(CommandInputConflictError):
        CommandInputBroker.respond(request_id, action="answer", value="x", agent_task_id="task-2")
    with pytest.raises(ValueError):
        CommandInputBroker.respond(request_id, action="answer", value="line one\nline two")
    with pytest.raises(ValueError):
        CommandInputBroker.respond(request_id, action="answer", value="x" * 5_000)
    CommandInputBroker.respond(request_id, action="cancel")
    assert (await waiter).status == "canceled"


def test_validate_command_input_text_accepts_empty_and_tabs():
    assert validate_command_input_text(None) == ""
    assert validate_command_input_text("") == ""
    assert validate_command_input_text("a\tb\r\n") == "a\tb"
    with pytest.raises(ValueError):
        validate_command_input_text("bad\x1bsequence")


@pytest.mark.asyncio
async def test_routes_list_and_answer_pending_requests():
    app = FastAPI()
    app.include_router(command_input_router, prefix="/api/v1/agent-tasks")
    manager = FakeWebSocketManager()
    waiter = asyncio.create_task(
        CommandInputBroker.request_input(
            agent_task_id="task-1", prompt="Password:", secret=True, command_echo="sudo ls", websocket_manager=manager
        )
    )
    request_id = (await _wait_for_event(manager))["approval_id"]
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as client:
        pending = await client.get("/api/v1/agent-tasks/task-1/command-input/pending")
        assert pending.status_code == 200
        assert [item["request_id"] for item in pending.json()["requests"]] == [request_id]
        assert pending.json()["requests"][0]["secret"] is True

        wrong_task = await client.post(
            f"/api/v1/agent-tasks/command-input/{request_id}/respond",
            json={"action": "answer", "value": "pw", "agent_task_id": "task-2"},
        )
        assert wrong_task.status_code == 409

        malformed = await client.post(
            f"/api/v1/agent-tasks/command-input/{request_id}/respond",
            json={"action": "answer", "value": "a\nb"},
        )
        assert malformed.status_code == 422

        answered = await client.post(
            f"/api/v1/agent-tasks/command-input/{request_id}/respond",
            json={"action": "answer", "value": "pw", "agent_task_id": "task-1"},
        )
        assert answered.status_code == 200
        assert (await waiter).text == "pw"

        stale = await client.post(
            f"/api/v1/agent-tasks/command-input/{request_id}/respond",
            json={"action": "cancel"},
        )
        assert stale.status_code == 404

        bad_action = await client.post(
            f"/api/v1/agent-tasks/command-input/{request_id}/respond",
            json={"action": "approve"},
        )
        assert bad_action.status_code == 422
