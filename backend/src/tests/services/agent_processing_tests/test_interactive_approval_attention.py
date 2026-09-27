from __future__ import annotations

import asyncio
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
        self.record["status"] = "cancelled"
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
        record["status"] = "cancelled"
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
async def test_cancel_pending_future_removes_and_cancels_the_waiter() -> None:
    future = asyncio.get_running_loop().create_future()
    InteractiveApprovalManager._pending_approvals["approval-retry"] = future

    cancelled = InteractiveApprovalManager.cancel_pending_future("approval-retry")

    assert cancelled is True
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
