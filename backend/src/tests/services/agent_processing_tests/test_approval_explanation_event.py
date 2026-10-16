"""The approval event, its persisted render context, and the recovery route all carry the agent's explanation and remember eligibility."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import api.dependencies as dependencies_module
from api.core.models.preferences import ApprovalTimeoutBehavior
from api.routes.agent_tasks import provider_interaction_routes
from api.services.agent_processing.tools.safety import interactive_approval
from api.services.agent_processing.tools.safety.command_generalization import CommandGeneralizer
from api.services.agent_processing.tools.safety.interactive_approval import InteractiveApprovalManager
from api.services.agent_processing.tools.safety.models import ExecutionApprovalDecision


class _Repository:
    def __init__(self) -> None:
        self.created: dict = {}
        self.record: dict = {}
        self.resolutions: list[dict] = []

    async def create_pending_approval(self, **kwargs):
        self.created = kwargs
        self.record = {
            "id": "approval-1",
            "agent_task_id": kwargs["agent_task_id"],
            "execution_type": kwargs["execution_type"],
            "command": kwargs["command"],
            "generalized_pattern": kwargs["generalized_pattern"],
            "script_content": kwargs["script_content"],
            "reason": kwargs["reason"],
            "risk_level": kwargs["risk_level"],
            "render_context": kwargs["render_context"],
            "status": "pending",
            "revision": 0,
        }
        return dict(self.record)

    async def get_approval(self, approval_id: str):
        return dict(self.record) if approval_id == "approval-1" else None

    async def resolve_pending_approval(self, **kwargs):
        self.resolutions.append(kwargs)
        self.record["status"] = "approved"
        return dict(self.record)

    async def list_pending_approvals_for_agent_task(self, agent_task_id: str):
        return [dict(self.record)] if self.record.get("status") == "pending" else []

    async def cancel_pending_approval(self, **_kwargs):
        self.record["status"] = "canceled"
        return dict(self.record)


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


def _patch(monkeypatch, repository) -> None:
    monkeypatch.setattr(
        dependencies_module,
        "get_sqlite_knowledge_service",
        lambda: SimpleNamespace(
            execution_approval_repository=repository,
            get_agent_task=AsyncMock(return_value=SimpleNamespace(status="running")),
        ),
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


def _manager(websocket: _WebSocket) -> InteractiveApprovalManager:
    return InteractiveApprovalManager(websocket_manager=websocket, generalizer=CommandGeneralizer())


_DECISION = ExecutionApprovalDecision(needs_approval=True, reason="Command not in whitelist", risk_level="medium")


@pytest.mark.asyncio
async def test_script_approval_event_carries_the_explanation_script_and_forced_off_remember(monkeypatch) -> None:
    repository = _Repository()
    websocket = _WebSocket()
    _patch(monkeypatch, repository)
    request = asyncio.create_task(
        _manager(websocket).request_approval(
            command="python3 /tmp/report.py",
            decision=_DECISION,
            context={
                "agent_task_id": "task-1",
                "purpose": "Builds the weekly report from the exported CSV.",
                "whitelist_advice": {"recommend": True, "reason": "I run this every week."},
                "purpose_required": True,
                "script_content": "print('report')\n",
                "script_path": "/tmp/report.py",
                "script_sha256": "abc",
            },
        )
    )
    await websocket.published.wait()

    event = websocket.events[0]
    assert event["script_content"] == "print('report')\n"
    assert event["options"]["show_remember"] is False
    assert event["context"]["purpose"] == "Builds the weekly report from the exported CSV."
    assert event["context"]["script_path"] == "/tmp/report.py"
    assert event["context"]["whitelist"]["eligible"] is False
    assert event["context"]["whitelist"]["advice"]["recommend"] is False
    assert event["context"]["whitelist"]["advice"]["downgraded"] is True
    persisted = repository.created["render_context"]
    assert persisted["purpose"] == event["context"]["purpose"]
    assert persisted["whitelist"] == event["context"]["whitelist"]
    assert persisted["script_sha256"] == "abc"

    await _manager(websocket).handle_approval_response(
        approval_id="approval-1", approved=True, remember=True, pattern_type="prefix", agent_task_id="task-1", expected_revision=0
    )
    assert await request == (True, False, "prefix")
    assert repository.resolutions[0]["remember_choice"] is False


@pytest.mark.asyncio
async def test_a_remembered_choice_for_an_eligible_command_is_kept(monkeypatch) -> None:
    repository = _Repository()
    websocket = _WebSocket()
    _patch(monkeypatch, repository)
    request = asyncio.create_task(
        _manager(websocket).request_approval(
            command="git status",
            decision=_DECISION,
            context={"agent_task_id": "task-1", "purpose": "Shows changes.", "whitelist_advice": {"recommend": True, "reason": "Read-only."}},
        )
    )
    await websocket.published.wait()
    assert websocket.events[0]["options"]["show_remember"] is True
    assert websocket.events[0]["context"]["whitelist"]["advice"] == {"recommend": True, "reason": "Read-only.", "downgraded": False}

    await _manager(websocket).handle_approval_response(
        approval_id="approval-1", approved=True, remember=True, pattern_type="prefix", agent_task_id="task-1", expected_revision=0
    )

    assert await request == (True, True, "prefix")


@pytest.mark.asyncio
async def test_an_unexplained_command_is_flagged_and_gets_no_advice(monkeypatch) -> None:
    repository = _Repository()
    websocket = _WebSocket()
    _patch(monkeypatch, repository)
    request = asyncio.create_task(
        _manager(websocket).request_approval(
            command="cargo build",
            decision=_DECISION,
            context={"agent_task_id": "task-1", "purpose_required": True, "whitelist_advice": {"recommend": True, "reason": "Fine."}},
        )
    )
    await websocket.published.wait()

    context = websocket.events[0]["context"]
    assert context["purpose_missing"] is True
    assert "purpose" not in context
    assert context["whitelist"]["advice"] is None
    request.cancel()
    with pytest.raises(asyncio.CancelledError):
        await request


@pytest.mark.asyncio
async def test_a_recovered_approval_carries_the_same_explanation_fields(monkeypatch) -> None:
    repository = _Repository()
    websocket = _WebSocket()
    _patch(monkeypatch, repository)
    request = asyncio.create_task(
        _manager(websocket).request_approval(
            command="python3 /tmp/report.py",
            decision=_DECISION,
            context={
                "agent_task_id": "task-1",
                "purpose": "Builds the weekly report.",
                "purpose_required": True,
                "script_content": "print('report')\n",
                "script_path": "/tmp/report.py",
                "script_notice": "Shown in full.",
            },
        )
    )
    await websocket.published.wait()
    live_context = websocket.events[0]["context"]

    response = await provider_interaction_routes.get_pending_execution_approval("task-1")

    recovered_context = response.approvals[0].context
    for key in ("purpose", "whitelist", "script_path", "script_notice"):
        assert recovered_context[key] == live_context[key]
    request.cancel()
    with pytest.raises(asyncio.CancelledError):
        await request
