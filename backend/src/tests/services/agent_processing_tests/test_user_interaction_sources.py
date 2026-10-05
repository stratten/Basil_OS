from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import api.core.preferences.preferences_io as preferences_io_module
import api.dependencies as dependencies_module
from api.core.models.preferences import ApprovalTimeoutBehavior, BrowserSensitiveFillPolicy, Preferences
from api.services.agent_processing.lifecycle.finalization import task_state_persistence
from api.services.agent_processing.lifecycle.runtime import user_interaction_timeline
from api.services.agent_processing.tools.direct_application_interactions.browser_automation import (
    browser_sensitive_approval,
)
from api.services.agent_processing.tools.direct_application_interactions.browser_automation.browser_sensitive_approval import (
    BrowserSensitiveApprovalManager,
    BrowserSensitiveFillRequest,
)
from api.services.agent_processing.tools.direct_application_interactions.shell import command_input_broker
from api.services.agent_processing.tools.direct_application_interactions.shell.command_input_broker import (
    CommandInputBroker,
)
from api.services.agent_processing.tools.internal_basil_tools.checkpoint_tool import CheckpointRequest
from api.services.agent_processing.tools.safety import interactive_approval
from api.services.agent_processing.tools.safety.interactive_approval import InteractiveApprovalManager
from api.services.agent_processing.tools.safety.models import ExecutionApprovalDecision
from api.services.mcp_connectors import swift_token_bridge


class _Recorder:
    def __init__(self) -> None:
        self.asked: list[dict] = []
        self.resolved: list[dict] = []

    async def ask(self, agent_task_id, **kwargs):
        self.asked.append({"agent_task_id": agent_task_id, **kwargs})

    async def resolve(self, agent_task_id, **kwargs):
        self.resolved.append({"agent_task_id": agent_task_id, **kwargs})


class _WebSocket:
    def __init__(self) -> None:
        self.events: list[dict] = []

    async def broadcast(self, event: dict) -> None:
        self.events.append(event)


@pytest.mark.asyncio
async def test_clarification_checkpoint_records_the_question_and_keeps_paused_reasoning(monkeypatch):
    recorder = _Recorder()
    monkeypatch.setattr(user_interaction_timeline, "record_user_interaction_asked", recorder.ask)
    status_updates: list[dict] = []

    async def get_agent_task(_agent_task_id):
        return SimpleNamespace(result_data={"existing": True})

    async def update_agent_task_status(**kwargs):
        status_updates.append(kwargs)

    knowledge = SimpleNamespace(
        agent_task_service=SimpleNamespace(
            _queries=SimpleNamespace(get_agent_task=get_agent_task),
            update_agent_task_status=update_agent_task_status,
        )
    )
    monkeypatch.setattr(dependencies_module, "get_sqlite_knowledge_service", lambda: knowledge)
    state = SimpleNamespace(
        context={"agent_task_id": "task-1"},
        user_agent_task="Find cat shirt shops near my hotel",
        available_tools=None,
    )
    checkpoint = CheckpointRequest({"prompt": "Which hotel?", "input_type": "text", "metadata": {}})

    await task_state_persistence.handle_checkpoint_request(
        checkpoint,
        state,
        SimpleNamespace(_websocket_manager=None),
        thinking_history=[
            {"iteration": 1, "text": "Hotel is ambiguous", "is_complete": True, "recorded_at": "2026-10-04T23:39:00+00:00"},
        ],
    )

    assert len(recorder.asked) == 1
    asked = recorder.asked[0]
    assert asked["agent_task_id"] == "task-1"
    assert asked["kind"] == "clarification"
    assert asked["prompt"] == "Which hotel?"
    assert asked["interaction_id"].startswith("checkpoint_")
    saved = status_updates[0]["result_data"]
    assert saved["existing"] is True
    assert saved["thinking_history"] == [
        {"iteration": 1, "text": "Hotel is ambiguous", "is_complete": True, "recorded_at": "2026-10-04T23:39:00+00:00"},
    ]


@pytest.mark.asyncio
async def test_secret_command_input_is_recorded_without_the_typed_answer(monkeypatch):
    recorder = _Recorder()
    monkeypatch.setattr(command_input_broker, "record_user_interaction_asked", recorder.ask)
    monkeypatch.setattr(command_input_broker, "record_user_interaction_resolved", recorder.resolve)

    async def no_attention(*_args):
        return None

    monkeypatch.setattr(command_input_broker, "publish_conversation_agent_attention", no_attention)
    monkeypatch.setattr(command_input_broker, "clear_conversation_agent_attention", no_attention)
    websocket = _WebSocket()

    request = asyncio.create_task(
        CommandInputBroker.request_input(
            agent_task_id="task-1",
            prompt="Password:",
            secret=True,
            command_echo="sudo make install",
            websocket_manager=websocket,
        )
    )
    while not websocket.events:
        await asyncio.sleep(0)
    while not recorder.asked:
        await asyncio.sleep(0)
    CommandInputBroker.respond(websocket.events[0]["approval_id"], action="answer", value="hunter2")
    reply = await request

    assert reply.text == "hunter2"
    assert recorder.asked[0]["kind"] == "command_input"
    assert recorder.asked[0]["input_type"] == "secret"
    assert recorder.resolved[0]["status"] == "answered"
    assert recorder.resolved[0]["response_hidden"] is True


@pytest.mark.asyncio
async def test_keychain_prompt_is_recorded_once_and_resolved_with_the_outcome(monkeypatch):
    recorder = _Recorder()
    monkeypatch.setattr(user_interaction_timeline, "record_user_interaction_asked", recorder.ask)
    monkeypatch.setattr(user_interaction_timeline, "record_user_interaction_resolved", recorder.resolve)
    broadcasts: list[dict] = []

    async def broadcast(payload):
        broadcasts.append(payload)
        return 1

    monkeypatch.setattr(swift_token_bridge, "_broadcast_to_active_connections", broadcast)
    swift_token_bridge._token_request_contexts["corr-1"] = {"agent_task_id": "task-1", "connection_id": "conn-1"}
    try:
        assert await swift_token_bridge.broadcast_token_user_action_waiting("corr-1", message="Allow Basil to read Slack token")
        assert await swift_token_bridge.broadcast_token_user_action_waiting("corr-1")
        await swift_token_bridge._broadcast_token_blocker_resolved(
            "corr-1",
            {"event_type": "agent_task_blocker_resolved", "agent_task_id": "task-1", "kind": "token_missing"},
        )
    finally:
        swift_token_bridge._token_request_contexts.pop("corr-1", None)

    assert [item["kind"] for item in recorder.asked] == ["credential"]
    assert recorder.asked[0]["prompt"] == "Allow Basil to read Slack token"
    assert recorder.resolved == [
        {"agent_task_id": "task-1", "interaction_id": "corr-1", "status": "denied", "broadcast": broadcast},
    ]


@pytest.mark.asyncio
async def test_token_requests_without_a_visible_prompt_are_not_recorded(monkeypatch):
    recorder = _Recorder()
    monkeypatch.setattr(user_interaction_timeline, "record_user_interaction_resolved", recorder.resolve)

    async def broadcast(_payload):
        return 1

    monkeypatch.setattr(swift_token_bridge, "_broadcast_to_active_connections", broadcast)
    swift_token_bridge._token_request_contexts["corr-2"] = {"agent_task_id": "task-1", "connection_id": "conn-1"}
    try:
        await swift_token_bridge._broadcast_token_blocker_resolved(
            "corr-2",
            {"event_type": "agent_task_blocker_resolved", "agent_task_id": "task-1", "kind": "token_available"},
        )
    finally:
        swift_token_bridge._token_request_contexts.pop("corr-2", None)

    assert recorder.resolved == []


class _ApprovalRepository:
    def __init__(self) -> None:
        self.record = {"id": "approval-1", "agent_task_id": "task-1", "status": "pending", "revision": 0}

    async def create_pending_approval(self, **_kwargs):
        return dict(self.record)

    async def get_approval(self, approval_id: str):
        return dict(self.record) if approval_id == "approval-1" else None

    async def resolve_pending_approval(self, **kwargs):
        self.record["status"] = "approved" if kwargs["approved"] else "denied"
        return dict(self.record)

    async def cancel_pending_approval(self, **_kwargs):
        self.record["status"] = "canceled"
        return dict(self.record)


def _execution_approval_manager(monkeypatch, recorder: _Recorder, *, timeout_behavior, timeout_seconds=30):
    monkeypatch.setattr(
        dependencies_module,
        "get_sqlite_knowledge_service",
        lambda: SimpleNamespace(execution_approval_repository=_ApprovalRepository()),
    )
    monkeypatch.setattr(interactive_approval, "persist_timeline_entry", AsyncMock())
    monkeypatch.setattr(interactive_approval, "publish_conversation_agent_attention", AsyncMock())
    monkeypatch.setattr(interactive_approval, "clear_conversation_agent_attention", AsyncMock())
    monkeypatch.setattr(interactive_approval, "record_user_interaction_asked", recorder.ask)
    monkeypatch.setattr(interactive_approval, "record_user_interaction_resolved", recorder.resolve)
    monkeypatch.setattr(
        interactive_approval,
        "resolve_tool_execution_settings",
        lambda _context: SimpleNamespace(approval_timeout_seconds=timeout_seconds, timeout_behavior=timeout_behavior),
    )
    return InteractiveApprovalManager(
        websocket_manager=_WebSocket(),
        generalizer=SimpleNamespace(generalize_command=lambda command: command),
    )


@pytest.fixture
def _clear_pending_execution_approvals():
    InteractiveApprovalManager._pending_approvals.clear()
    InteractiveApprovalManager._processing_approvals.clear()
    yield
    InteractiveApprovalManager._pending_approvals.clear()
    InteractiveApprovalManager._processing_approvals.clear()


@pytest.mark.asyncio
@pytest.mark.parametrize(("approved", "expected_status"), [(True, "approved"), (False, "denied")])
async def test_execution_approval_records_the_command_and_the_decision(
    monkeypatch, _clear_pending_execution_approvals, approved, expected_status
):
    recorder = _Recorder()
    manager = _execution_approval_manager(monkeypatch, recorder, timeout_behavior=ApprovalTimeoutBehavior.WAIT_FOREVER)
    decision = ExecutionApprovalDecision(needs_approval=True, reason="Not whitelisted", risk_level="low")

    request = asyncio.create_task(
        manager.request_approval(command="rm -rf build", decision=decision, context={"agent_task_id": "task-1"})
    )
    while not manager.websocket_manager.events:
        await asyncio.sleep(0)
    await manager.handle_approval_response(
        approval_id="approval-1", approved=approved, agent_task_id="task-1", expected_revision=0
    )
    result = await request

    assert result[0] is approved
    assert [(item["kind"], item["prompt"], item["interaction_id"]) for item in recorder.asked] == [
        ("approval", "rm -rf build", "approval-1"),
    ]
    assert [(item["interaction_id"], item["status"]) for item in recorder.resolved] == [("approval-1", expected_status)]


@pytest.mark.asyncio
async def test_execution_approval_timeout_is_recorded(monkeypatch, _clear_pending_execution_approvals):
    recorder = _Recorder()
    manager = _execution_approval_manager(
        monkeypatch, recorder, timeout_behavior=ApprovalTimeoutBehavior.DENY_ON_TIMEOUT, timeout_seconds=0.01
    )
    decision = ExecutionApprovalDecision(needs_approval=True, reason="Not whitelisted", risk_level="low")

    result = await manager.request_approval(command="pwd", decision=decision, context={"agent_task_id": "task-1"})

    assert result == (False, False, "timeout_denied")
    assert [item["status"] for item in recorder.resolved] == ["timed_out"]


def _browser_fill_request(websocket) -> BrowserSensitiveFillRequest:
    return BrowserSensitiveFillRequest(
        browser="Safari",
        selector="input[type=password]",
        url="https://example.com/login",
        field_metadata={"type": "password"},
        agent_task_id="task-1",
        websocket_manager=websocket,
    )


def _ask_every_time(monkeypatch, recorder: _Recorder, *, timeout_seconds: float = 30) -> None:
    preferences = Preferences()
    preferences.browser_automation.sensitive_fill_policy = BrowserSensitiveFillPolicy.ASK_EVERY_TIME
    preferences.tool_execution.approval_timeout_seconds = timeout_seconds
    monkeypatch.setattr(browser_sensitive_approval, "load_preferences", lambda: preferences)
    monkeypatch.setattr(preferences_io_module, "load_preferences", lambda: preferences)
    monkeypatch.setattr(browser_sensitive_approval, "record_user_interaction_asked", recorder.ask)
    monkeypatch.setattr(browser_sensitive_approval, "record_user_interaction_resolved", recorder.resolve)


@pytest.mark.asyncio
@pytest.mark.parametrize(("approved", "expected_status"), [(True, "approved"), (False, "denied")])
async def test_browser_sensitive_fill_approval_records_the_request_and_the_decision(
    monkeypatch, approved, expected_status
):
    recorder = _Recorder()
    _ask_every_time(monkeypatch, recorder)
    websocket = _WebSocket()

    task = asyncio.create_task(
        BrowserSensitiveApprovalManager().evaluate_sensitive_fill_request(_browser_fill_request(websocket))
    )
    while not recorder.asked:
        await asyncio.sleep(0)
    await BrowserSensitiveApprovalManager.resolve_browser_sensitive_fill_approval(
        approval_id=websocket.events[0]["approval_id"],
        approved=approved,
    )
    decision = await task

    assert decision.allowed is approved
    assert recorder.asked[0]["kind"] == "approval"
    assert recorder.asked[0]["prompt"] == "Fill sensitive browser field on example.com"
    assert recorder.asked[0]["input_type"] == "browser_sensitive_fill"
    assert [(item["interaction_id"], item["status"]) for item in recorder.resolved] == [
        (websocket.events[0]["approval_id"], expected_status),
    ]


@pytest.mark.asyncio
async def test_browser_sensitive_fill_timeout_is_recorded(monkeypatch):
    recorder = _Recorder()
    _ask_every_time(monkeypatch, recorder, timeout_seconds=0.01)

    decision = await BrowserSensitiveApprovalManager().evaluate_sensitive_fill_request(
        _browser_fill_request(_WebSocket())
    )

    assert decision.allowed is False
    assert [item["status"] for item in recorder.resolved] == ["timed_out"]
