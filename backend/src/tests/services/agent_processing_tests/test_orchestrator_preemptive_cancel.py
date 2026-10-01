"""Integration test: cancel_agent_task preemptively cancels the live task.

Proves the normal user flow for preemptive cancellation:
  * _perform_processing registers its top-level asyncio.Task,
  * cancel_agent_task calls Task.cancel() on it (not just the cooperative event),
  * the task ends CANCELED, its registration is cleaned up in the finally, and
  * no 'completed'/'failed' status is written for the canceled task.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from api.services.agent_processing.lifecycle.submission.agent_task_processing.agent_task_orchestrator import (
    AgentTaskOrchestrator,
)


class _MockDbService:
    """Minimal db_service surface used by the orchestrator during processing."""

    def __init__(self, record) -> None:
        self._record = record
        self.status_updates: list = []
        self.provider_run_repository = SimpleNamespace()
        self.provider_profile_repository = SimpleNamespace()
        self.provider_interaction_repository = SimpleNamespace()
        self.provider_target_delegation_repository = SimpleNamespace()
        self.agent_task_service = SimpleNamespace()

    def register_agent_task_callback(self, callback) -> None:  # noqa: D401
        return None

    async def get_agent_task(self, agent_task_id: str):
        return self._record

    async def get_agent_task_chain(self, root_task_id: str):
        return []

    async def update_agent_task_status(self, **kwargs):
        self.status_updates.append(kwargs)


def _make_record(agent_task_id: str):
    return SimpleNamespace(
        id=agent_task_id,
        transcribed_prompt="do the thing",
        app_name=None,
        screen_text=None,
        root_task_id=None,
        previous_task_id=None,
        accumulated_artifacts=None,
        result_data=None,
        execution_timeline=None,
        operation_parameters={
            "operation": "multi_step_workflow",
            "parameters": {"workflow_type": "general"},
        },
    )


@pytest.mark.asyncio
async def test_cancel_agent_task_preempts_running_processing():
    agent_task_id = "task-123"
    db_service = _MockDbService(_make_record(agent_task_id))
    orchestrator = AgentTaskOrchestrator(db_service=db_service, websocket_manager=None)

    workflow_started = asyncio.Event()

    async def _blocking_workflow(parameters, request):
        # Prove the cancel_event was threaded through as before.
        assert getattr(request, "cancel_event", None) is not None
        workflow_started.set()
        await asyncio.Event().wait()  # never completes; only Task.cancel() ends it

    orchestrator._execute_multi_step_workflow = _blocking_workflow

    task = asyncio.create_task(orchestrator._perform_processing(agent_task_id))

    # Wait until execution has entered the (blocking) workflow.
    await asyncio.wait_for(workflow_started.wait(), timeout=5)

    # The live task must be registered while it runs.
    assert orchestrator._cancellation._active_tasks.get(agent_task_id) is task

    result = await orchestrator.cancel_agent_task(agent_task_id)
    assert result is True

    # The workflow blocks on a fresh, never-set Event, so the ONLY way the task
    # can finish is Task.cancel() injecting CancelledError. The orchestrator's
    # top-level handler intentionally converts that into a clean return, so the
    # task ends done (not in CANCELED state) rather than re-raising. If
    # preemption had failed, this await would hang and time out.
    await asyncio.wait_for(task, timeout=5)
    assert task.done() is True
    assert task.cancelled() is False
    assert task.result() is None

    # finally-block cleanup: no stale registration remains.
    assert orchestrator._cancellation._active_tasks.get(agent_task_id) is None

    # Cooperative state is also set (belt-and-suspenders / thread path).
    assert orchestrator.is_agent_task_canceled(agent_task_id) is True
    assert orchestrator._get_cancellation_event(agent_task_id).is_set() is True

    # Negative assertion: a preempted task must NOT be marked completed/failed.
    terminal_writes = [
        u for u in db_service.status_updates
        if u.get("status") in {"completed", "failed"}
    ]
    assert terminal_writes == []


@pytest.mark.asyncio
async def test_cancel_agent_task_no_active_task_is_safe():
    agent_task_id = "task-none"
    db_service = _MockDbService(_make_record(agent_task_id))
    orchestrator = AgentTaskOrchestrator(db_service=db_service, websocket_manager=None)

    # Nothing running for this id -> cancel still succeeds and marks cooperative state.
    result = await orchestrator.cancel_agent_task(agent_task_id)
    assert result is True
    assert orchestrator.is_agent_task_canceled(agent_task_id) is True


@pytest.mark.asyncio
async def test_duplicate_runtime_cancellation_broadcasts_terminal_event_once():
    class _WebsocketRecorder:
        def __init__(self):
            self.events = []

        async def broadcast(self, event):
            self.events.append(event)

    agent_task_id = "task-duplicate"
    websocket = _WebsocketRecorder()
    orchestrator = AgentTaskOrchestrator(
        db_service=_MockDbService(_make_record(agent_task_id)),
        websocket_manager=websocket,
    )

    assert await orchestrator.cancel_agent_task(agent_task_id) is True
    assert await orchestrator.cancel_agent_task(agent_task_id) is True

    cancellation_events = [
        event for event in websocket.events
        if event.get("event_type") == "agent_task_canceled"
    ]
    assert len(cancellation_events) == 1


@pytest.mark.asyncio
async def test_cancel_session_synthetic_task_end_to_end(tmp_path, monkeypatch):
    from api.core.knowledge.sqlite.sqlite_knowledge_service import SQLiteKnowledgeService
    from api.routes.agent_tasks import session_control_routes
    from api.routes.agent_tasks.session_control_routes import CancelSessionRequest
    from api.services.agent_processing.lifecycle.submission.agent_task_submission_service import (
        AgentTaskSubmissionService,
    )

    class _WebsocketRecorder:
        def __init__(self):
            self.events = []

        async def broadcast(self, event):
            self.events.append(event)

    db_service = SQLiteKnowledgeService(tmp_path / "synthetic-cancel.db")
    for task_id in ("cancel-me", "leave-running"):
        await db_service.store_agent_task(
            agent_task_id=task_id,
            original_prompt=task_id,
            transcribed_prompt=task_id,
            status="processing",
        )
        await db_service.update_agent_task_status(
            agent_task_id=task_id,
            status="processing",
            operation_parameters={
                "operation": "multi_step_workflow",
                "parameters": {"workflow_type": "general"},
            },
        )

    websocket = _WebsocketRecorder()
    orchestrator = AgentTaskOrchestrator(
        db_service=db_service,
        websocket_manager=websocket,
    )
    submission = AgentTaskSubmissionService(
        agent_task_orchestrator=orchestrator,
        db_service=db_service,
    )
    started_ids = set()
    both_started = asyncio.Event()

    async def _blocking_workflow(_parameters, request):
        started_ids.add(request.agent_task_id)
        if started_ids == {"cancel-me", "leave-running"}:
            both_started.set()
        await asyncio.Event().wait()

    orchestrator._execute_multi_step_workflow = _blocking_workflow
    canceled_task = asyncio.create_task(orchestrator._perform_processing("cancel-me"))
    unrelated_task = asyncio.create_task(orchestrator._perform_processing("leave-running"))
    await asyncio.wait_for(both_started.wait(), timeout=5)

    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(agent_task_submission_service=submission)
        )
    )
    response = await session_control_routes.cancel_session(
        "cancel-me",
        request,
        CancelSessionRequest(reason="Synthetic validation"),
    )

    await asyncio.wait_for(canceled_task, timeout=5)
    assert response.success is True
    assert (await db_service.get_agent_task("cancel-me")).status == "canceled"
    assert unrelated_task.done() is False
    assert any(
        event.get("event_type") == "agent_task_canceled"
        and event.get("agent_task_id") == "cancel-me"
        for event in websocket.events
    )
    assert not any(
        event.get("event_type") == "agent_task_result"
        and event.get("agent_task_id") == "cancel-me"
        for event in websocket.events
    )
    assert await db_service.update_agent_task_status_if_active(
        "cancel-me",
        "completed",
    ) is False

    unrelated_task.cancel()
    await asyncio.gather(unrelated_task, return_exceptions=True)
