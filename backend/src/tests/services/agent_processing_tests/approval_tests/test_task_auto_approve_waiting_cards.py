"""Turning a task's auto-approve switch on approves the cards that task is already waiting on, and only those."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import api.dependencies as dependencies_module
from api.core.models.preferences import ApprovalTimeoutBehavior
from api.services.agent_processing.tools.safety import interactive_approval
from api.services.agent_processing.tools.safety.execution_approval_service import ExecutionApprovalService
from api.services.agent_processing.tools.safety.interactive_approval import InteractiveApprovalManager
from api.services.agent_processing.tools.safety.models import ExecutionApprovalDecision


class _Repository:
    def __init__(self) -> None:
        self.records: dict[str, dict] = {}

    async def create_pending_approval(self, **kwargs):
        approval_id = f"approval-{len(self.records) + 1}"
        record = {"id": approval_id, "agent_task_id": kwargs["agent_task_id"], "status": "pending", "revision": 0}
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

    async def broadcast(self, event: dict) -> None:
        self.events.append(event)


@pytest.fixture(autouse=True)
def _clear_state():
    for registry in (
        InteractiveApprovalManager._pending_approvals,
        InteractiveApprovalManager._processing_approvals,
        InteractiveApprovalManager._auto_approvable_roots,
    ):
        registry.clear()
    yield
    for registry in (
        InteractiveApprovalManager._pending_approvals,
        InteractiveApprovalManager._processing_approvals,
        InteractiveApprovalManager._auto_approvable_roots,
    ):
        registry.clear()


@pytest.fixture
def manager(monkeypatch):
    repository = _Repository()
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
    return InteractiveApprovalManager(
        websocket_manager=_WebSocket(),
        generalizer=SimpleNamespace(generalize_command=lambda command: command),
    )


async def _cancel(*tasks) -> None:
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


def _service(manager) -> ExecutionApprovalService:
    service = ExecutionApprovalService()
    service.interactive_manager = manager
    return service


def _decision() -> ExecutionApprovalDecision:
    return ExecutionApprovalDecision(needs_approval=True, reason="Not whitelisted", risk_level="low")


async def _wait_for_pending(count: int) -> None:
    for _ in range(200):
        if len(InteractiveApprovalManager._pending_approvals) >= count:
            return
        await asyncio.sleep(0.01)
    raise AssertionError("the cards never became pending")


def _card(manager, command: str, root: str, turn: str, *, auto_approvable: bool = True, context_root: str | None = None):
    context = {"agent_task_id": turn}
    if context_root is not None or auto_approvable:
        context["root_task_id"] = context_root if context_root is not None else root
    return asyncio.create_task(
        manager.request_approval(
            command=command,
            decision=_decision(),
            context=context,
            auto_approve_root=root if auto_approvable else None,
        )
    )


@pytest.mark.asyncio
async def test_enabling_approves_the_waiting_cards_for_that_task_only(manager):
    first = _card(manager, "touch a", "root-1", "turn-1")
    second = _card(manager, "touch b", "root-1", "turn-2")
    other_task = _card(manager, "touch c", "root-2", "turn-3")
    await _wait_for_pending(3)

    approved = await _service(manager).approve_waiting_for_task("root-1")

    assert approved == 2
    assert await first == (True, False, "exact")
    assert await second == (True, False, "exact")
    assert other_task.done() is False
    assert len(InteractiveApprovalManager._pending_approvals) == 1
    await _cancel(other_task)


@pytest.mark.asyncio
async def test_a_card_that_the_switch_may_not_cover_keeps_waiting(manager):
    covered = _card(manager, "touch a", "root-1", "turn-1")
    explicit_only = _card(manager, "grant access", "root-1", "turn-2", auto_approvable=False)
    await _wait_for_pending(2)

    approved = await _service(manager).approve_waiting_for_task("root-1")

    assert approved == 1
    assert await covered == (True, False, "exact")
    assert explicit_only.done() is False
    await _cancel(explicit_only)


@pytest.mark.asyncio
async def test_resolved_cards_leave_the_registry(manager):
    card = _card(manager, "touch a", "root-1", "turn-1")
    await _wait_for_pending(1)
    assert InteractiveApprovalManager.auto_approvable_pending_ids("root-1") == ["approval-1"]

    await manager.handle_approval_response("approval-1", False, False, "exact")
    await card

    assert InteractiveApprovalManager.auto_approvable_pending_ids("root-1") == []
    assert InteractiveApprovalManager._auto_approvable_roots == {}


@pytest.mark.asyncio
async def test_a_card_that_was_not_marked_never_enters_the_registry(manager):
    card = _card(manager, "grant access", "root-1", "turn-1", auto_approvable=False)
    await _wait_for_pending(1)

    assert InteractiveApprovalManager._auto_approvable_roots == {}
    await _cancel(card)


@pytest.mark.asyncio
async def test_approving_when_nothing_waits_is_a_no_op(manager):
    assert await _service(manager).approve_waiting_for_task("root-1") == 0


@pytest.mark.asyncio
async def test_a_card_that_was_answered_in_the_meantime_is_skipped_not_fatal(manager, monkeypatch):
    first = _card(manager, "touch a", "root-1", "turn-1")
    second = _card(manager, "touch b", "root-1", "turn-2")
    await _wait_for_pending(2)
    service = _service(manager)
    original = manager.handle_approval_response
    calls: list[str] = []

    async def flaky(approval_id, *args, **kwargs):
        calls.append(approval_id)
        if len(calls) == 1:
            raise RuntimeError("answered a moment ago")
        await original(approval_id, *args, **kwargs)

    monkeypatch.setattr(manager, "handle_approval_response", flaky)

    approved = await service.approve_waiting_for_task("root-1")

    assert approved == 1
    assert len(calls) == 2
    await _cancel(first, second)


@pytest.mark.asyncio
async def test_the_root_the_service_resolved_is_the_one_a_card_is_filed_under(manager):
    # The caller's context names no root (the running agent's does), so the manager alone would file the card under the turn's own id.
    card = asyncio.create_task(
        manager.request_approval(
            command="touch a",
            decision=_decision(),
            context={"agent_task_id": "turn-2"},
            auto_approve_root="root-1",
        )
    )
    await _wait_for_pending(1)

    assert InteractiveApprovalManager.auto_approvable_pending_ids("root-1") == ["approval-1"]
    assert InteractiveApprovalManager.auto_approvable_pending_ids("turn-2") == []
    await _cancel(card)


@pytest.mark.asyncio
async def test_the_service_files_its_cards_under_the_running_agents_root(manager, monkeypatch):
    from api.services.agent_processing.shared.agent_runtime_context import (
        reset_current_agent_context,
        set_current_agent_context,
    )
    from api.services.agent_processing.tools.safety import execution_approval_service as service_module

    service = _service(manager)
    monkeypatch.setattr(
        service_module, "get_current_agent_context", lambda: {"agent_task_id": "turn-2", "root_task_id": "root-1"}
    )
    outcome = asyncio.create_task(service.request_approval_with_outcome("touch a", {"agent_task_id": "turn-2"}))
    await _wait_for_pending(1)

    assert InteractiveApprovalManager.auto_approvable_pending_ids("root-1") == ["approval-1"]
    assert await service.approve_waiting_for_task("root-1") == 1
    await outcome
