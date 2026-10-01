"""Tests that remembered approvals whitelist the durable command rather than the client-supplied one."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

import api.dependencies as dependencies_module
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.execution_approvals.repository import (
    ExecutionApprovalConflictError,
)
from api.routes.agent_tasks.execution_approval_routes import process_approval_decision
from api.routes.agent_tasks.execution_models import ApprovalDecisionRequest


class _FakeApprovalService:
    def __init__(self, *, conflict: Exception | None = None) -> None:
        self.responses: list[dict] = []
        self.whitelisted: list[dict] = []
        self._conflict = conflict

    async def handle_approval_response(self, **kwargs) -> None:
        if self._conflict is not None:
            raise self._conflict
        self.responses.append(kwargs)

    async def add_to_whitelist(
        self, *, command: str, pattern_type: str, description: str, risk_level: str, record_initial_use: bool = False
    ):
        self.whitelisted.append(
            {
                "command": command,
                "pattern_type": pattern_type,
                "description": description,
                "risk_level": risk_level,
                "record_initial_use": record_initial_use,
            }
        )
        return SimpleNamespace(id="pattern-1")


def _install_durable_record(monkeypatch: pytest.MonkeyPatch, record: dict | None) -> AsyncMock:
    get_approval = AsyncMock(return_value=record)
    knowledge_service = SimpleNamespace(execution_approval_repository=SimpleNamespace(get_approval=get_approval))
    monkeypatch.setattr(dependencies_module, "get_sqlite_knowledge_service", lambda: knowledge_service)
    return get_approval


def _decision(**overrides) -> ApprovalDecisionRequest:
    values = {
        "approval_id": "approval-1",
        "command": "rm -rf ~",
        "approved": True,
        "remember_choice": True,
        "pattern_type": "prefix",
        "agent_task_id": "task-1",
    }
    values.update(overrides)
    return ApprovalDecisionRequest(**values)


@pytest.mark.asyncio
async def test_remembered_approval_whitelists_the_durable_command(monkeypatch: pytest.MonkeyPatch) -> None:
    get_approval = _install_durable_record(monkeypatch, {"id": "approval-1", "command": "ls -la", "status": "approved"})
    service = _FakeApprovalService()

    response = await process_approval_decision(request=_decision(), approval_service=service)

    get_approval.assert_awaited_once_with("approval-1")
    assert response.success is True
    assert response.pattern_id == "pattern-1"
    assert service.whitelisted == [
        {
            "command": "ls -la",
            "pattern_type": "prefix",
            "description": "User-approved: ls -la",
            "risk_level": "low",
            "record_initial_use": True,
        }
    ]


@pytest.mark.asyncio
async def test_remembered_approval_without_a_durable_record_is_not_whitelisted(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_durable_record(monkeypatch, None)
    service = _FakeApprovalService()

    response = await process_approval_decision(request=_decision(), approval_service=service)

    assert response.message == "Command approved for this execution"
    assert response.pattern_id is None
    assert service.whitelisted == []


@pytest.mark.asyncio
async def test_denied_decision_never_whitelists(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_durable_record(monkeypatch, {"id": "approval-1", "command": "ls -la", "status": "denied"})
    service = _FakeApprovalService()

    response = await process_approval_decision(request=_decision(approved=False), approval_service=service)

    assert response.message == "Command denied"
    assert service.whitelisted == []


@pytest.mark.asyncio
async def test_stale_decision_returns_conflict_without_whitelisting(monkeypatch: pytest.MonkeyPatch) -> None:
    get_approval = _install_durable_record(monkeypatch, {"id": "approval-1", "command": "ls -la", "status": "approved"})
    service = _FakeApprovalService(conflict=ExecutionApprovalConflictError("execution approval 'approval-1' is not pending"))

    with pytest.raises(HTTPException) as excinfo:
        await process_approval_decision(request=_decision(), approval_service=service)

    assert excinfo.value.status_code == 409
    get_approval.assert_not_awaited()
    assert service.whitelisted == []
