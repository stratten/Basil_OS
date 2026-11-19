from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import api.dependencies as dependencies_module
from api.routes.agent_tasks.execution_models import RecoverExecutionApprovalsRequest
from api.routes.agent_tasks import provider_interaction_routes
from api.services.agent_processing.tools.safety.interactive_approval import (
    InteractiveApprovalManager,
)


class _ApprovalRepository:
    def __init__(self) -> None:
        self.records = {
            "live-approval": self._record("live-approval"),
            "orphaned-approval": self._record("orphaned-approval"),
        }

    @staticmethod
    def _record(approval_id: str) -> dict:
        return {
            "id": approval_id,
            "agent_task_id": "task-1",
            "command": "pwd",
            "reason": "Not whitelisted",
            "risk_level": "low",
            "generalized_pattern": "pwd",
            "execution_type": "shell",
            "script_content": None,
            "render_context": {},
            "status": "pending",
            "revision": 0,
        }

    async def list_pending_approvals_for_agent_task(self, agent_task_id: str):
        return [
            dict(record)
            for record in self.records.values()
            if record["agent_task_id"] == agent_task_id and record["status"] == "pending"
        ]

    async def cancel_pending_approval(self, *, approval_id: str, expected_revision: int):
        record = self.records[approval_id]
        assert record["status"] == "pending"
        assert record["revision"] == expected_revision
        record["status"] = "canceled"
        record["revision"] += 1
        return dict(record)


@pytest.fixture(autouse=True)
def _clear_pending_approval_futures():
    InteractiveApprovalManager._pending_approvals.clear()
    yield
    InteractiveApprovalManager._pending_approvals.clear()


@pytest.fixture
def route_dependencies(monkeypatch):
    repository = _ApprovalRepository()
    task = SimpleNamespace(status="awaiting_user_input", result_data={})
    task_service = SimpleNamespace(update_agent_task_status=AsyncMock())
    knowledge_service = SimpleNamespace(
        get_agent_task=AsyncMock(return_value=task),
        execution_approval_repository=repository,
        agent_task_service=task_service,
    )
    monkeypatch.setattr(
        dependencies_module,
        "get_sqlite_knowledge_service",
        lambda: knowledge_service,
    )
    monkeypatch.setattr(
        provider_interaction_routes,
        "logger",
        provider_interaction_routes.logger,
    )
    return repository, task_service


@pytest.mark.asyncio
async def test_pending_approval_hydration_lists_live_and_orphaned_records(route_dependencies):
    live_future = asyncio.get_running_loop().create_future()
    InteractiveApprovalManager._pending_approvals["live-approval"] = live_future

    response = await provider_interaction_routes.get_pending_execution_approval("task-1")

    assert [approval.approval_id for approval in response.approvals] == ["live-approval"]
    assert response.orphaned_approval_ids == ["orphaned-approval"]


@pytest.mark.asyncio
async def test_recovery_cancels_only_named_orphaned_approvals(route_dependencies, monkeypatch):
    repository, task_service = route_dependencies
    InteractiveApprovalManager._pending_approvals["live-approval"] = (
        asyncio.get_running_loop().create_future()
    )
    clear_attention = AsyncMock()
    monkeypatch.setattr(
        "api.services.conversation.conversation_agent_turn_lifecycle.clear_conversation_agent_attention",
        clear_attention,
    )

    response = await provider_interaction_routes.recover_orphaned_execution_approvals(
        "task-1",
        RecoverExecutionApprovalsRequest(approval_ids=["orphaned-approval"]),
    )

    assert response.canceled_approval_ids == ["orphaned-approval"]
    assert repository.records["orphaned-approval"]["status"] == "canceled"
    assert repository.records["live-approval"]["status"] == "pending"
    clear_attention.assert_awaited_once_with("task-1", "orphaned-approval")
    task_service.update_agent_task_status.assert_not_awaited()


@pytest.mark.asyncio
async def test_recovery_rejects_a_live_approval(route_dependencies):
    live_future = asyncio.get_running_loop().create_future()
    InteractiveApprovalManager._pending_approvals["live-approval"] = live_future

    with pytest.raises(Exception, match="live and cannot be recovered"):
        await provider_interaction_routes.recover_orphaned_execution_approvals(
            "task-1",
            RecoverExecutionApprovalsRequest(approval_ids=["live-approval"]),
        )


@pytest.mark.asyncio
async def test_recovery_marks_task_retryable_after_retiring_the_last_orphan(route_dependencies):
    repository, task_service = route_dependencies
    repository.records.pop("live-approval")

    await provider_interaction_routes.recover_orphaned_execution_approvals(
        "task-1",
        RecoverExecutionApprovalsRequest(approval_ids=["orphaned-approval"]),
    )

    task_service.update_agent_task_status.assert_awaited_once_with(
        agent_task_id="task-1",
        status="failed",
        result_data={
            "approval_recovery": {
                "canceled_approval_ids": ["orphaned-approval"],
                "reason": "backend_interrupted_approval_wait",
            }
        },
    )
