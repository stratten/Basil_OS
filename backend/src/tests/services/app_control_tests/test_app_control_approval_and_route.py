"""The approval prompt manager and the route that answers it."""

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.core.security import backend_request_guard
from api.routes.app_control_routes import router
from api.services.app_control.approval import SettingsChangeApprovalManager, SettingsChangeApprovalRequest


class _Socket:
    def __init__(self):
        self.events = []

    async def broadcast(self, event):
        self.events.append(event)


def _request(socket):
    return SettingsChangeApprovalRequest(
        tier="behavioral",
        reason="compare turns",
        changes=[{"key": "k", "label": "Open turns", "before": "single", "after": "multiple"}],
        websocket_manager=socket,
    )


@pytest.mark.asyncio
async def test_the_card_event_cannot_be_remembered_and_carries_the_diff(memory_preferences):
    socket = _Socket()
    task = asyncio.create_task(SettingsChangeApprovalManager().request(_request(socket)))
    for _ in range(50):
        if socket.events:
            break
        await asyncio.sleep(0.01)
    event = socket.events[0]
    assert event["execution_type"] == "settings_change"
    assert event["context"]["whitelist"]["eligible"] is False
    assert event["options"]["show_remember"] is False
    assert event["settings_change"]["changes"][0] == {"key": "k", "label": "Open turns", "before": "single", "after": "multiple"}
    assert await SettingsChangeApprovalManager.resolve(event["approval_id"], True) is True
    assert await task == "approved"
    assert await SettingsChangeApprovalManager.resolve(event["approval_id"], True) is False


@pytest.mark.asyncio
async def test_a_denial_and_a_timeout_are_reported(memory_preferences):
    memory_preferences.current.tool_execution.approval_timeout_seconds = 1
    socket = _Socket()
    denied = asyncio.create_task(SettingsChangeApprovalManager().request(_request(socket)))
    for _ in range(50):
        if socket.events:
            break
        await asyncio.sleep(0.01)
    await SettingsChangeApprovalManager.resolve(socket.events[0]["approval_id"], False)
    assert await denied == "denied"
    assert await SettingsChangeApprovalManager().request(_request(_Socket())) == "timed_out"


@pytest.mark.asyncio
async def test_without_a_connected_app_the_request_is_unavailable():
    assert await SettingsChangeApprovalManager().request(_request(None)) == "unavailable"


def _client(monkeypatch, credential_type):
    monkeypatch.setattr(backend_request_guard, "request_credential_type", lambda request: credential_type)
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_the_route_returns_404_for_an_unknown_id(monkeypatch):
    response = _client(monkeypatch, "host").post("/app-control/settings-change/approve", json={"approval_id": "nope", "approved": True})
    assert response.status_code == 404


def test_only_the_host_credential_can_answer(monkeypatch):
    response = _client(monkeypatch, "agent").post("/app-control/settings-change/approve", json={"approval_id": "nope", "approved": True})
    assert response.status_code == 403
    assert response.json() == {"detail": "host_credential_required"}


@pytest.mark.asyncio
async def test_a_second_request_from_the_same_task_is_turned_away_while_one_is_open(memory_preferences):
    socket = _Socket()
    first_request = _request(socket)
    first_request.agent_task_id = "task-a"
    first = asyncio.create_task(SettingsChangeApprovalManager().request(first_request))
    for _ in range(50):
        if socket.events:
            break
        await asyncio.sleep(0.01)
    second_request = _request(_Socket())
    second_request.agent_task_id = "task-a"
    assert await SettingsChangeApprovalManager().request(second_request) == "busy"
    await SettingsChangeApprovalManager.resolve(socket.events[0]["approval_id"], True)
    assert await first == "approved"


@pytest.mark.asyncio
async def test_no_more_than_three_prompts_are_open_at_once(memory_preferences):
    sockets, tasks = [], []
    for index in range(3):
        socket = _Socket()
        request = _request(socket)
        request.agent_task_id = f"task-{index}"
        sockets.append(socket)
        tasks.append(asyncio.create_task(SettingsChangeApprovalManager().request(request)))
    for _ in range(100):
        if all(socket.events for socket in sockets):
            break
        await asyncio.sleep(0.01)
    overflow = _request(_Socket())
    overflow.agent_task_id = "task-overflow"
    assert await SettingsChangeApprovalManager().request(overflow) == "busy"
    for socket in sockets:
        await SettingsChangeApprovalManager.resolve(socket.events[0]["approval_id"], False)
    assert [await task for task in tasks] == ["denied", "denied", "denied"]
