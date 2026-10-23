from __future__ import annotations

import asyncio
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import api.dependencies as dependencies_module
from api.core.models.preferences import ApprovalTimeoutBehavior
from api.services.agent_processing.tools.safety import interactive_approval
from api.services.agent_processing.tools.safety.interactive_approval import InteractiveApprovalManager
from api.services.agent_processing.tools.safety.models import ExecutionApprovalDecision


class _Repository:
    def __init__(self) -> None:
        self.record = {
            "id": "approval-1",
            "agent_task_id": "task-1",
            "status": "pending",
            "revision": 0,
        }

    async def create_pending_approval(self, **_kwargs):
        return dict(self.record)

    async def get_pending_approval_for_agent_task(self, agent_task_id: str):
        return dict(self.record) if agent_task_id == "task-1" else None

    async def get_approval(self, approval_id: str):
        return dict(self.record) if approval_id == "approval-1" else None

    async def resolve_pending_approval(self, **_kwargs):
        self.record["status"] = "approved"
        return dict(self.record)

    async def cancel_pending_approval(self, **_kwargs):
        self.record["status"] = "canceled"
        return dict(self.record)


class _MultiApprovalRepository:
    def __init__(self) -> None:
        self.records: dict[str, dict] = {}

    async def create_pending_approval(self, **kwargs):
        approval_id = f"approval-{len(self.records) + 1}"
        record = {
            "id": approval_id,
            "agent_task_id": kwargs["agent_task_id"],
            "status": "pending",
            "revision": 0,
        }
        self.records[approval_id] = record
        return dict(record)

    async def get_approval(self, approval_id: str):
        record = self.records.get(approval_id)
        return dict(record) if record else None

    async def resolve_pending_approval(self, **kwargs):
        record = self.records[kwargs["approval_id"]]
        record["status"] = "approved" if kwargs["approved"] else "denied"
        record["revision"] += 1
        return dict(record)

    async def cancel_pending_approval(self, **kwargs):
        record = self.records[kwargs["approval_id"]]
        record["status"] = "canceled"
        record["revision"] += 1
        return dict(record)


class _WebSocket:
    def __init__(self) -> None:
        self.events: list[dict] = []
        self.published = asyncio.Event()

    async def broadcast(self, event: dict) -> None:
        self.events.append(event)
        self.published.set()


@pytest.fixture(autouse=True)
def _clear_pending_approvals():
    InteractiveApprovalManager._pending_approvals.clear()
    InteractiveApprovalManager._processing_approvals.clear()
    yield
    InteractiveApprovalManager._pending_approvals.clear()
    InteractiveApprovalManager._processing_approvals.clear()


@pytest.mark.asyncio
async def test_execution_approval_projects_and_clears_matching_conversation_attention(monkeypatch):
    repository = _Repository()
    websocket = _WebSocket()
    publish_attention = AsyncMock()
    clear_attention = AsyncMock()
    monkeypatch.setattr(
        dependencies_module,
        "get_sqlite_knowledge_service",
        lambda: SimpleNamespace(execution_approval_repository=repository),
    )
    monkeypatch.setattr(interactive_approval, "persist_timeline_entry", AsyncMock())
    monkeypatch.setattr(
        interactive_approval,
        "publish_conversation_agent_attention",
        publish_attention,
    )
    monkeypatch.setattr(
        interactive_approval,
        "clear_conversation_agent_attention",
        clear_attention,
    )
    monkeypatch.setattr(
        interactive_approval,
        "resolve_tool_execution_settings",
        lambda _context: SimpleNamespace(
            approval_timeout_seconds=30,
            timeout_behavior=ApprovalTimeoutBehavior.WAIT_FOREVER,
        ),
    )

    manager = InteractiveApprovalManager(
        websocket_manager=websocket,
        generalizer=SimpleNamespace(generalize_command=lambda command: command),
    )
    decision = ExecutionApprovalDecision(
        needs_approval=True,
        reason="Not whitelisted",
        risk_level="low",
    )
    request = asyncio.create_task(
        manager.request_approval(
            command="pwd",
            decision=decision,
            context={"agent_task_id": "task-1"},
        )
    )

    await websocket.published.wait()
    publish_attention.assert_awaited_once_with("task-1", "approval-1")
    assert websocket.events[0]["event_type"] == "execution_approval_request"

    await manager.handle_approval_response(
        approval_id="approval-1",
        approved=True,
        agent_task_id="task-1",
        expected_revision=0,
    )

    assert await request == (True, False, "exact")
    clear_attention.assert_awaited_once_with("task-1", "approval-1")


@pytest.mark.asyncio
async def test_approval_activity_entries_use_sortable_iso_timestamps(monkeypatch):
    repository = _Repository()
    websocket = _WebSocket()
    persisted = AsyncMock()
    monkeypatch.setattr(
        dependencies_module,
        "get_sqlite_knowledge_service",
        lambda: SimpleNamespace(execution_approval_repository=repository),
    )
    monkeypatch.setattr(interactive_approval, "persist_timeline_entry", persisted)
    monkeypatch.setattr(interactive_approval, "publish_conversation_agent_attention", AsyncMock())
    monkeypatch.setattr(interactive_approval, "clear_conversation_agent_attention", AsyncMock())
    monkeypatch.setattr(
        interactive_approval,
        "resolve_tool_execution_settings",
        lambda _context: SimpleNamespace(
            approval_timeout_seconds=30,
            timeout_behavior=ApprovalTimeoutBehavior.WAIT_FOREVER,
        ),
    )
    manager = InteractiveApprovalManager(
        websocket_manager=websocket,
        generalizer=SimpleNamespace(generalize_command=lambda command: command),
    )
    request = asyncio.create_task(
        manager.request_approval(
            command="pwd",
            decision=ExecutionApprovalDecision(needs_approval=True, reason="Not whitelisted", risk_level="low"),
            context={"agent_task_id": "task-1"},
        )
    )
    await websocket.published.wait()
    await manager.handle_approval_response(
        approval_id="approval-1",
        approved=True,
        agent_task_id="task-1",
        expected_revision=0,
    )
    await request

    activity_entries = [
        call.args[1]
        for call in persisted.await_args_list
        if call.args[1].get("phase") == "approval_waiting"
    ]
    assert {entry["id"] for entry in activity_entries} == {"approval-wait-approval-1", "approval-granted-approval-1"}
    for entry in activity_entries:
        assert isinstance(entry["timestamp"], str)
        assert datetime.fromisoformat(entry["timestamp"].replace("Z", "+00:00")).tzinfo is not None


@pytest.mark.asyncio
async def test_cancel_pending_future_removes_and_cancels_the_waiter() -> None:
    future = asyncio.get_running_loop().create_future()
    InteractiveApprovalManager._pending_approvals["approval-retry"] = future

    canceled = InteractiveApprovalManager.cancel_pending_future("approval-retry")

    assert canceled is True
    assert future.cancelled() is True
    assert "approval-retry" not in InteractiveApprovalManager._pending_approvals


@pytest.mark.asyncio
async def test_parallel_approval_requests_remain_independently_decidable(monkeypatch):
    repository = _MultiApprovalRepository()
    websocket = _WebSocket()
    monkeypatch.setattr(
        dependencies_module,
        "get_sqlite_knowledge_service",
        lambda: SimpleNamespace(execution_approval_repository=repository),
    )
    monkeypatch.setattr(interactive_approval, "persist_timeline_entry", AsyncMock())
    monkeypatch.setattr(interactive_approval, "publish_conversation_agent_attention", AsyncMock())
    monkeypatch.setattr(interactive_approval, "clear_conversation_agent_attention", AsyncMock())
    monkeypatch.setattr(
        interactive_approval,
        "resolve_tool_execution_settings",
        lambda _context: SimpleNamespace(
            approval_timeout_seconds=30,
            timeout_behavior=ApprovalTimeoutBehavior.WAIT_FOREVER,
        ),
    )
    manager = InteractiveApprovalManager(
        websocket_manager=websocket,
        generalizer=SimpleNamespace(generalize_command=lambda command: command),
    )
    decision = ExecutionApprovalDecision(
        needs_approval=True,
        reason="Not whitelisted",
        risk_level="low",
    )
    requests = [
        asyncio.create_task(
            manager.request_approval(
                command=command,
                decision=decision,
                context={"agent_task_id": "task-1"},
            )
        )
        for command in ("pwd", "ls")
    ]

    for _ in range(10):
        if len(websocket.events) == 2:
            break
        await asyncio.sleep(0)
    assert [event["approval_id"] for event in websocket.events] == ["approval-1", "approval-2"]

    await manager.handle_approval_response(
        approval_id="approval-2",
        approved=False,
        agent_task_id="task-1",
        expected_revision=0,
    )
    await manager.handle_approval_response(
        approval_id="approval-1",
        approved=True,
        agent_task_id="task-1",
        expected_revision=0,
    )

    assert await asyncio.gather(*requests) == [
        (True, False, "exact"),
        (False, False, "exact"),
    ]


@pytest.mark.asyncio
async def test_response_without_live_waiter_keeps_durable_approval_pending(monkeypatch):
    repository = _Repository()
    monkeypatch.setattr(
        dependencies_module,
        "get_sqlite_knowledge_service",
        lambda: SimpleNamespace(execution_approval_repository=repository),
    )
    manager = InteractiveApprovalManager(
        websocket_manager=_WebSocket(),
        generalizer=SimpleNamespace(generalize_command=lambda command: command),
    )

    with pytest.raises(Exception, match="not active in this process"):
        await manager.handle_approval_response(
            approval_id="approval-1",
            approved=True,
            agent_task_id="task-1",
            expected_revision=0,
        )

    assert repository.record["status"] == "pending"


def _patch_waiting_manager(monkeypatch, repository, clear_attention):
    monkeypatch.setattr(
        dependencies_module,
        "get_sqlite_knowledge_service",
        lambda: SimpleNamespace(execution_approval_repository=repository),
    )
    monkeypatch.setattr(interactive_approval, "persist_timeline_entry", AsyncMock())
    monkeypatch.setattr(interactive_approval, "publish_conversation_agent_attention", AsyncMock())
    monkeypatch.setattr(interactive_approval, "clear_conversation_agent_attention", clear_attention)
    monkeypatch.setattr(
        interactive_approval,
        "resolve_tool_execution_settings",
        lambda _context: SimpleNamespace(
            approval_timeout_seconds=30,
            timeout_behavior=ApprovalTimeoutBehavior.WAIT_FOREVER,
        ),
    )


@pytest.mark.asyncio
async def test_canceled_waiter_cancels_durable_approval_and_reraises(monkeypatch):
    repository = _Repository()
    websocket = _WebSocket()
    clear_attention = AsyncMock()
    _patch_waiting_manager(monkeypatch, repository, clear_attention)
    manager = InteractiveApprovalManager(
        websocket_manager=websocket,
        generalizer=SimpleNamespace(generalize_command=lambda command: command),
    )
    decision = ExecutionApprovalDecision(needs_approval=True, reason="Not whitelisted", risk_level="low")
    request = asyncio.create_task(
        manager.request_approval(command="pwd", decision=decision, context={"agent_task_id": "task-1"})
    )
    await websocket.published.wait()

    request.cancel()
    with pytest.raises(asyncio.CancelledError):
        await request

    assert repository.record["status"] == "canceled"
    clear_attention.assert_awaited_once_with("task-1", "approval-1")
    assert "approval-1" not in InteractiveApprovalManager._pending_approvals


@pytest.mark.asyncio
async def test_canceling_the_run_during_an_approval_wait_records_the_interaction_canceled(monkeypatch):
    repository = _Repository()
    websocket = _WebSocket()
    clear_attention = AsyncMock()
    _patch_waiting_manager(monkeypatch, repository, clear_attention)
    resolved = AsyncMock()
    monkeypatch.setattr(interactive_approval, "record_user_interaction_resolved", resolved)
    manager = InteractiveApprovalManager(
        websocket_manager=websocket,
        generalizer=SimpleNamespace(generalize_command=lambda command: command),
    )
    decision = ExecutionApprovalDecision(needs_approval=True, reason="Not whitelisted", risk_level="low")
    request = asyncio.create_task(
        manager.request_approval(command="pwd", decision=decision, context={"agent_task_id": "task-1"})
    )
    await websocket.published.wait()

    request.cancel()
    with pytest.raises(asyncio.CancelledError):
        await request

    resolved.assert_awaited_once()
    assert resolved.await_args.args == ("task-1",)
    assert resolved.await_args.kwargs["interaction_id"] == "approval-1"
    assert resolved.await_args.kwargs["status"] == "canceled"


@pytest.mark.asyncio
async def test_retired_approval_returns_unavailable_without_leaking_cancellation(monkeypatch):
    repository = _Repository()
    websocket = _WebSocket()
    clear_attention = AsyncMock()
    _patch_waiting_manager(monkeypatch, repository, clear_attention)
    manager = InteractiveApprovalManager(
        websocket_manager=websocket,
        generalizer=SimpleNamespace(generalize_command=lambda command: command),
    )
    decision = ExecutionApprovalDecision(needs_approval=True, reason="Not whitelisted", risk_level="low")
    request = asyncio.create_task(
        manager.request_approval(command="pwd", decision=decision, context={"agent_task_id": "task-1"})
    )
    await websocket.published.wait()

    assert InteractiveApprovalManager.cancel_pending_future("approval-1") is True

    assert await request == (False, False, "approval_unavailable")
    assert repository.record["status"] == "canceled"


@pytest.mark.asyncio
async def test_approval_wait_pauses_the_workflow_budget(monkeypatch):
    from api.services.agent_processing.lifecycle.execution_graph.workflow_deadline import WorkflowDeadline
    from api.services.agent_processing.shared.agent_runtime_context import (
        reset_current_agent_context,
        set_current_agent_context,
    )

    repository = _Repository()
    websocket = _WebSocket()
    _patch_waiting_manager(monkeypatch, repository, AsyncMock())
    manager = InteractiveApprovalManager(
        websocket_manager=websocket,
        generalizer=SimpleNamespace(generalize_command=lambda command: command),
    )
    deadline = WorkflowDeadline.start(total_seconds=100, finalization_reserve_seconds=0)
    decision = ExecutionApprovalDecision(needs_approval=True, reason="Not whitelisted", risk_level="low")
    token = set_current_agent_context({"agent_task_id": "task-1", "_workflow_deadline": deadline})
    try:
        request = asyncio.create_task(
            manager.request_approval(command="pwd", decision=decision, context={"agent_task_id": "task-1"})
        )
    finally:
        reset_current_agent_context(token)
    await websocket.published.wait()
    for _ in range(10):
        if deadline.is_paused:
            break
        await asyncio.sleep(0)
    assert deadline.is_paused is True
    assert deadline.pause_reasons == ["execution_approval"]

    await manager.handle_approval_response(
        approval_id="approval-1",
        approved=True,
        agent_task_id="task-1",
        expected_revision=0,
    )

    assert await request == (True, False, "exact")
    assert deadline.is_paused is False


@pytest.mark.asyncio
async def test_decision_from_a_service_without_a_websocket_manager_still_releases_the_waiter(monkeypatch):
    """The decide route lazily builds `ExecutionApprovalService()` with no websocket manager, which used to raise after the durable approval committed and leave the task waiting forever."""
    from api.services.agent_processing.tools.safety import ExecutionApprovalService

    repository = _Repository()
    websocket = _WebSocket()
    _patch_waiting_manager(monkeypatch, repository, AsyncMock())
    manager = InteractiveApprovalManager(
        websocket_manager=websocket,
        generalizer=SimpleNamespace(generalize_command=lambda command: command),
    )
    decision = ExecutionApprovalDecision(needs_approval=True, reason="Not whitelisted", risk_level="low")
    request = asyncio.create_task(
        manager.request_approval(command="pwd", decision=decision, context={"agent_task_id": "task-1"})
    )
    await websocket.published.wait()

    await ExecutionApprovalService().handle_approval_response(
        approval_id="approval-1",
        approved=True,
        agent_task_id="task-1",
        expected_revision=0,
    )

    assert await asyncio.wait_for(request, timeout=2) == (True, False, "exact")


@pytest.mark.asyncio
async def test_broadcast_falls_back_to_connected_clients_without_a_websocket_manager(monkeypatch):
    sent: list[dict] = []

    async def _fake_broadcast_json_text(payload, *, log=None):
        sent.append(payload)
        return 1

    monkeypatch.setattr(interactive_approval, "broadcast_json_text", _fake_broadcast_json_text)
    generalizer = SimpleNamespace(generalize_command=lambda command: command)
    websocket = _WebSocket()

    await InteractiveApprovalManager(websocket_manager=None, generalizer=generalizer)._broadcast({"event_type": "a"})
    await InteractiveApprovalManager(websocket_manager=websocket, generalizer=generalizer)._broadcast({"event_type": "b"})

    assert sent == [{"event_type": "a"}]
    assert websocket.events == [{"event_type": "b"}]


@pytest.mark.asyncio
async def test_failed_resolution_bookkeeping_still_releases_the_waiting_run(monkeypatch):
    repository = _Repository()
    websocket = _WebSocket()
    _patch_waiting_manager(monkeypatch, repository, AsyncMock())
    manager = InteractiveApprovalManager(
        websocket_manager=websocket,
        generalizer=SimpleNamespace(generalize_command=lambda command: command),
    )
    decision = ExecutionApprovalDecision(needs_approval=True, reason="Not whitelisted", risk_level="low")
    request = asyncio.create_task(
        manager.request_approval(command="pwd", decision=decision, context={"agent_task_id": "task-1"})
    )
    await websocket.published.wait()
    monkeypatch.setattr(interactive_approval, "persist_timeline_entry", AsyncMock(side_effect=RuntimeError("timeline unavailable")))

    await manager.handle_approval_response(
        approval_id="approval-1",
        approved=False,
        agent_task_id="task-1",
        expected_revision=0,
    )

    assert await asyncio.wait_for(request, timeout=2) == (False, False, "exact")
