from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

import api.services.conversation.conversation_agent_turn_lifecycle as lifecycle_module
from api.services.agent_processing.tools.safety.execution_approval_retirement import (
    retire_pending_execution_approvals,
)
from api.services.agent_processing.tools.safety.interactive_approval import InteractiveApprovalManager


class _Repository:
    def __init__(self) -> None:
        self.pending = {"task-1": [{"id": "approval-a"}, {"id": "approval-b"}], "task-2": []}
        self.canceled_for: list[list[str]] = []

    async def list_pending_approvals_for_agent_task(self, agent_task_id: str):
        return list(self.pending.get(agent_task_id, []))

    async def cancel_pending_approvals_for_tasks(self, agent_task_ids):
        self.canceled_for.append(list(agent_task_ids))
        return sum(len(self.pending.get(task_id, [])) for task_id in agent_task_ids)


@pytest.fixture(autouse=True)
def _clear_pending():
    InteractiveApprovalManager._pending_approvals.clear()
    yield
    InteractiveApprovalManager._pending_approvals.clear()


@pytest.mark.asyncio
async def test_retirement_stops_waiters_clears_attention_and_cancels_rows(monkeypatch):
    clear_attention = AsyncMock(side_effect=[RuntimeError("attention store down"), None])
    monkeypatch.setattr(lifecycle_module, "clear_conversation_agent_attention", clear_attention)
    waiter = asyncio.get_running_loop().create_future()
    InteractiveApprovalManager._pending_approvals["approval-b"] = waiter
    repository = _Repository()

    canceled = await retire_pending_execution_approvals(repository, ["task-1", "task-2", " "])

    assert canceled == 2
    assert repository.canceled_for == [["task-1", "task-2"]]
    assert clear_attention.await_count == 2
    assert waiter.cancelled() is True


@pytest.mark.asyncio
async def test_retirement_with_no_task_ids_is_a_noop():
    repository = _Repository()
    assert await retire_pending_execution_approvals(repository, []) == 0
    assert repository.canceled_for == []
