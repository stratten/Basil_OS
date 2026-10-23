"""Tests for the Keychain-wait + cancel fixes.

Covers the three fix surfaces:
  * WS1 helper ``await_future_with_cancellation`` — resolved / timeout / cancel.
  * WS1 bridge ``_ask_swift_for_credentials`` — bounded wait + blocker_resolved
    broadcasts on the timeout and cancel branches (previously the timeout branch
    left the UI blocker up forever).
  * WS2 durable cancellation — preserves completed parent turns, terminates
    active follow-ups, and prevents terminal records from resuming checkpoints.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from api.services.agent_processing.shared.cancellable_wait import (
    await_future_with_cancellation,
)


# --------------------------------------------------------------------------- #
# WS1 - helper                                                                #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_helper_resolved_without_cancel_event():
    loop = asyncio.get_running_loop()
    future = loop.create_future()
    future.set_result({"access_token": "abc"})

    kind, value = await await_future_with_cancellation(
        future, timeout_s=1.0, cancel_event=None
    )

    assert kind == "resolved"
    assert value == {"access_token": "abc"}


@pytest.mark.asyncio
async def test_helper_resolved_with_unset_cancel_event():
    loop = asyncio.get_running_loop()
    future = loop.create_future()
    cancel_event = asyncio.Event()

    async def _resolve_soon():
        await asyncio.sleep(0.01)
        if not future.done():
            future.set_result("token")

    asyncio.ensure_future(_resolve_soon())
    kind, value = await await_future_with_cancellation(
        future, timeout_s=1.0, cancel_event=cancel_event
    )

    assert kind == "resolved"
    assert value == "token"


@pytest.mark.asyncio
async def test_helper_timeout():
    loop = asyncio.get_running_loop()
    future = loop.create_future()  # never resolved

    kind, value = await await_future_with_cancellation(
        future, timeout_s=0.05, cancel_event=None
    )

    assert kind == "timeout"
    assert value is None


@pytest.mark.asyncio
async def test_helper_canceled_when_event_already_set():
    loop = asyncio.get_running_loop()
    future = loop.create_future()  # never resolved
    cancel_event = asyncio.Event()
    cancel_event.set()

    kind, value = await await_future_with_cancellation(
        future, timeout_s=5.0, cancel_event=cancel_event
    )

    assert kind == "canceled"
    assert value is None


@pytest.mark.asyncio
async def test_helper_canceled_when_event_set_midwait():
    loop = asyncio.get_running_loop()
    future = loop.create_future()  # never resolved
    cancel_event = asyncio.Event()

    async def _cancel_soon():
        await asyncio.sleep(0.01)
        cancel_event.set()

    asyncio.ensure_future(_cancel_soon())
    kind, value = await await_future_with_cancellation(
        future, timeout_s=5.0, cancel_event=cancel_event
    )

    assert kind == "canceled"
    assert value is None


# --------------------------------------------------------------------------- #
# WS1 - bridge blocker broadcasts                                             #
# --------------------------------------------------------------------------- #
def _install_broadcast_recorder(monkeypatch):
    """Patch the bridge broadcaster to record events and report one recipient."""
    from api.services.mcp_connectors import swift_token_bridge

    events: list[dict] = []

    async def _fake_broadcast(payload: dict) -> int:
        events.append(payload)
        return 1

    monkeypatch.setattr(swift_token_bridge, "_broadcast_to_active_connections", _fake_broadcast)
    return swift_token_bridge, events


@pytest.mark.asyncio
async def test_bridge_timeout_emits_blocker_resolved(monkeypatch):
    bridge, events = _install_broadcast_recorder(monkeypatch)

    # No one ever resolves the pending future, so the bounded wait times out.
    result = await bridge._ask_swift_for_credentials(
        connection_id="conn-1",
        timeout_s=0.05,
        agent_task_id="task-1",
        include_refresh_token=False,
        cancel_event=None,
    )

    assert result["kind"] == "token_response_timeout"
    resolved = [e for e in events if e.get("event_type") == "agent_task_blocker_resolved"]
    assert any(e.get("kind") == "token_response_timeout" for e in resolved)
    # The pending waiter must be cleaned up (no leak).
    assert not bridge._token_response_waiters


@pytest.mark.asyncio
async def test_bridge_cancel_emits_blocker_resolved(monkeypatch):
    bridge, events = _install_broadcast_recorder(monkeypatch)

    cancel_event = asyncio.Event()
    cancel_event.set()

    result = await bridge._ask_swift_for_credentials(
        connection_id="conn-1",
        timeout_s=30.0,
        agent_task_id="task-1",
        include_refresh_token=False,
        cancel_event=cancel_event,
    )

    assert result["kind"] == "token_request_canceled"
    resolved = [e for e in events if e.get("event_type") == "agent_task_blocker_resolved"]
    assert any(e.get("kind") == "token_request_canceled" for e in resolved)
    assert not bridge._token_response_waiters


@pytest.mark.asyncio
async def test_bridge_resolved_returns_token(monkeypatch):
    bridge, events = _install_broadcast_recorder(monkeypatch)

    async def _resolve_after_send():
        # Give _ask_swift_for_credentials a beat to register the waiter, then
        # resolve it the way the WebSocket dispatcher would.
        for _ in range(50):
            await asyncio.sleep(0.005)
            if bridge._token_response_waiters:
                cid = next(iter(bridge._token_response_waiters))
                bridge.resolve_pending_token_response(cid, "the-token", None)
                return

    asyncio.ensure_future(_resolve_after_send())
    result = await bridge._ask_swift_for_credentials(
        connection_id="conn-1",
        timeout_s=5.0,
        agent_task_id="task-1",
        include_refresh_token=False,
        cancel_event=None,
    )

    assert result["kind"] == "token_available"
    assert result["access_token"] == "the-token"


@pytest.mark.asyncio
async def test_bridge_user_action_waiting_broadcasts_for_known_correlation(monkeypatch):
    bridge, events = _install_broadcast_recorder(monkeypatch)

    async def _surface_waiting_then_resolve():
        for _ in range(50):
            await asyncio.sleep(0.005)
            if bridge._token_request_contexts:
                cid = next(iter(bridge._token_request_contexts))
                delivered = await bridge.broadcast_token_user_action_waiting(
                    cid,
                    connection_id="conn-1",
                    message="Keychain access required",
                )
                assert delivered is True
                bridge.resolve_pending_token_response(cid, "the-token", None)
                return

    asyncio.ensure_future(_surface_waiting_then_resolve())
    result = await bridge._ask_swift_for_credentials(
        connection_id="conn-1",
        timeout_s=5.0,
        agent_task_id="task-1",
        include_refresh_token=False,
        cancel_event=None,
    )

    assert result["kind"] == "token_available"
    waiting_events = [
        e for e in events
        if e.get("event_type") == "agent_task_blocker_waiting"
        and e.get("user_action_required") is True
    ]
    assert waiting_events
    assert waiting_events[0]["agent_task_id"] == "task-1"
    assert waiting_events[0]["connection_id"] == "conn-1"
    assert waiting_events[0]["kind"] == "external_service_token"
    assert not bridge._token_request_contexts


@pytest.mark.asyncio
async def test_bridge_user_action_waiting_ignores_unknown_correlation(monkeypatch):
    bridge, events = _install_broadcast_recorder(monkeypatch)

    delivered = await bridge.broadcast_token_user_action_waiting(
        "unknown-correlation",
        connection_id="conn-1",
        message="Keychain access required",
    )

    assert delivered is False
    assert not events


# --------------------------------------------------------------------------- #
# WS2 - durable agent-task cancellation and terminal checkpoint guards        #
# --------------------------------------------------------------------------- #
class _AgentTask:
    def __init__(self, task_id, status, root_task_id=None):
        self.id = task_id
        self.status = status
        self.root_task_id = root_task_id


class _DurableCancellationDb:
    def __init__(self, records):
        self.records = {record.id: record for record in records}
        self.updates = []

    async def get_agent_task(self, agent_task_id):
        return self.records.get(agent_task_id)

    async def get_agent_task_chain(self, root_task_id):
        return [
            record
            for record in self.records.values()
            if record.id == root_task_id or record.root_task_id == root_task_id
        ]

    async def update_agent_task_status(self, agent_task_id, status, result_data=None):
        self.updates.append((agent_task_id, status, result_data))
        self.records[agent_task_id].status = status


class _FakeOrchestrator:
    def __init__(self, runtime_canceled):
        self.runtime_canceled = runtime_canceled
        self.canceled_ids = []

    async def cancel_agent_task(self, agent_task_id):
        self.canceled_ids.append(agent_task_id)
        return self.runtime_canceled


class _FakeCheckpointHandler:
    async def has_checkpoint(self, agent_task_id):
        return True


class _FakeCoordinator:
    instances = []

    def __init__(self, websocket_manager=None):
        self.checkpoint_workflow_service = _FakeCheckpointHandler()
        self.resume_calls = []
        self.__class__.instances.append(self)

    async def resume_workflow(self, agent_task_id, user_response):
        self.resume_calls.append((agent_task_id, user_response))
        raise AssertionError("terminal task must not resume")


class _FakeAgentTaskService:
    def __init__(self, record):
        self.record = record

    async def get_agent_task(self, agent_task_id):
        return self.record if self.record.id == agent_task_id else None


class _FakeKnowledgeService:
    def __init__(self, record):
        self.agent_task_service = _FakeAgentTaskService(record)


class _FakeSubmissionService:
    def __init__(self):
        self.calls = []

    async def cancel_agent_task_durably(self, *, agent_task_id, reason):
        self.calls.append((agent_task_id, reason))
        return {
            "root_task_id": agent_task_id,
            "canceled_task_ids": [agent_task_id],
            "runtime_canceled": False,
        }


class _PreemptiveCancellationDb:
    def __init__(self):
        self.stored_ids = []
        self.status_updates = []

    async def store_agent_task(self, *, agent_task_id, **_kwargs):
        self.stored_ids.append(agent_task_id)

    async def update_agent_task_status(self, *, agent_task_id, status, result_data=None):
        self.status_updates.append((agent_task_id, status, result_data))


class _PreemptiveCancellationRouting:
    def __init__(self):
        self.title_calls = []

    async def generate_agent_task_title(self, agent_task_id, agent_task):
        self.title_calls.append((agent_task_id, agent_task))


@pytest.mark.asyncio
async def test_durable_cancellation_preserves_completed_root_and_cancels_active_child():
    from api.services.agent_processing.lifecycle.submission.agent_task_submission_service import (
        AgentTaskSubmissionService,
    )

    root = _AgentTask("root-1", "completed")
    child = _AgentTask("child-1", "processing", root_task_id=root.id)
    db_service = _DurableCancellationDb([root, child])
    orchestrator = _FakeOrchestrator(runtime_canceled=False)
    submission = AgentTaskSubmissionService(
        agent_task_orchestrator=orchestrator,
        db_service=db_service,
    )
    broadcasts = []

    async def _record_broadcast(event):
        broadcasts.append(event)

    submission.broadcast = _record_broadcast

    receipt = await submission.cancel_agent_task_durably(
        agent_task_id=root.id,
        reason="User canceled",
    )

    assert orchestrator.canceled_ids == [root.id]
    assert receipt["root_task_id"] == root.id
    assert receipt["canceled_task_ids"] == [child.id]
    assert db_service.updates[0][0:2] == (child.id, "canceled")
    assert root.status == "completed"
    assert child.status == "canceled"
    assert broadcasts == [{
        "event_type": "agent_task_canceled",
        "agent_task_id": child.id,
        "root_task_id": root.id,
        "message": "Task canceled",
    }]


@pytest.mark.asyncio
async def test_durable_cancellation_accepts_provisional_id_before_persistence():
    from api.services.agent_processing.lifecycle.submission.agent_task_submission_service import (
        AgentTaskSubmissionService,
    )

    db_service = _DurableCancellationDb([])
    orchestrator = _FakeOrchestrator(runtime_canceled=True)
    submission = AgentTaskSubmissionService(
        agent_task_orchestrator=orchestrator,
        db_service=db_service,
    )

    receipt = await submission.cancel_agent_task_durably(
        agent_task_id="provisional-1",
        reason="User canceled",
    )

    assert orchestrator.canceled_ids == ["provisional-1"]
    assert receipt["root_task_id"] == "provisional-1"
    assert receipt["canceled_task_ids"] == ["provisional-1"]
    assert receipt["runtime_canceled"] is True
    assert receipt["preemption_completed_at"] <= receipt["durable_completed_at"]
    assert receipt["durable_completed_at"] <= receipt["cleanup_completed_at"]
    assert db_service.updates == []


@pytest.mark.asyncio
async def test_durable_cancellation_is_idempotent_for_terminal_chain():
    from api.services.agent_processing.lifecycle.submission.agent_task_submission_service import (
        AgentTaskSubmissionService,
    )

    root = _AgentTask("root-1", "completed")
    child = _AgentTask("child-1", "canceled", root_task_id=root.id)
    db_service = _DurableCancellationDb([root, child])
    submission = AgentTaskSubmissionService(
        agent_task_orchestrator=_FakeOrchestrator(runtime_canceled=True),
        db_service=db_service,
    )

    receipt = await submission.cancel_agent_task_durably(
        agent_task_id=root.id,
        reason="User canceled",
    )

    assert receipt["canceled_task_ids"] == []
    assert db_service.updates == []


@pytest.mark.asyncio
async def test_submission_persists_preemptively_canceled_task_as_terminal():
    from api.services.agent_processing.lifecycle.submission.agent_task_processing.agent_task_submission_service import (
        AgentTaskSubmissionService,
    )

    db_service = _PreemptiveCancellationDb()
    routing_service = _PreemptiveCancellationRouting()
    submission = AgentTaskSubmissionService(
        db_service=db_service,
        screen_context_service=SimpleNamespace(),
        routing_service=routing_service,
        processing_service=SimpleNamespace(),
        is_canceled=lambda agent_task_id: agent_task_id == "provisional-1",
    )

    result = await submission.process_agent_task(
        agent_task="Do the thing",
        agent_task_id="provisional-1",
    )

    assert db_service.stored_ids == ["provisional-1"]
    assert len(db_service.status_updates) == 1
    canceled_id, canceled_status, cancellation_payload = db_service.status_updates[0]
    assert (canceled_id, canceled_status) == ("provisional-1", "canceled")
    assert cancellation_payload["canceled"] is True
    assert cancellation_payload["cancellation_reason"] == "User canceled"
    assert routing_service.title_calls == []
    assert result == {
        "success": False,
        "agent_task_id": "provisional-1",
        "status": "canceled",
        "message": "Task canceled",
    }


@pytest.mark.asyncio
async def test_cancel_route_uses_durable_cancellation_without_resuming_checkpoint(monkeypatch):
    from api.routes.agent_tasks import session_control_routes
    from api.routes.agent_tasks.session_control_routes import (
        CancelSessionRequest,
        cancel_session,
    )

    submission = _FakeSubmissionService()

    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(agent_task_submission_service=submission))
    )

    response = await cancel_session(
        agent_task_id="task-1",
        request=request,
        body=CancelSessionRequest(reason="User canceled"),
    )

    assert response.success is True
    assert response.finalized_via_agent is False
    assert submission.calls == [("task-1", "User canceled")]


@pytest.mark.asyncio
async def test_checkpoint_status_keeps_stored_checkpoint_visible_but_terminal_task_nonresumable(monkeypatch):
    from api.routes.agent_tasks import session_control_routes
    from api.routes.agent_tasks.session_control_routes import get_checkpoint_status
    import api.dependencies as dependencies

    record = _AgentTask("task-1", "canceled")
    submission = _FakeSubmissionService()
    _FakeCoordinator.instances = []
    monkeypatch.setattr(session_control_routes, "WorkflowCoordinator", _FakeCoordinator)
    monkeypatch.setattr(
        dependencies,
        "get_sqlite_knowledge_service",
        lambda: _FakeKnowledgeService(record),
    )
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(agent_task_submission_service=submission))
    )

    response = await get_checkpoint_status("task-1", request)

    assert response.has_checkpoint is True
    assert response.can_resume is False
    assert response.message == "Task is terminal and cannot be resumed"


@pytest.mark.asyncio
async def test_continue_rejects_canceled_task_before_resume(monkeypatch):
    from fastapi import HTTPException

    from api.routes.agent_tasks import session_control_routes
    from api.routes.agent_tasks.execution_models import ContinueSessionRequest
    from api.routes.agent_tasks.session_control_routes import continue_session
    import api.dependencies as dependencies

    record = _AgentTask("task-1", "canceled")
    submission = _FakeSubmissionService()
    _FakeCoordinator.instances = []
    monkeypatch.setattr(session_control_routes, "WorkflowCoordinator", _FakeCoordinator)
    monkeypatch.setattr(
        dependencies,
        "get_sqlite_knowledge_service",
        lambda: _FakeKnowledgeService(record),
    )
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(agent_task_submission_service=submission))
    )

    with pytest.raises(HTTPException) as exc_info:
        await continue_session(
            agent_task_id="task-1",
            request=request,
            body=ContinueSessionRequest(agent_task_id="task-1", user_input="continue"),
        )

    assert exc_info.value.status_code == 409
    assert _FakeCoordinator.instances == []


@pytest.mark.asyncio
async def test_submission_persists_conversation_id_as_durable_artifact():
    from api.services.agent_processing.lifecycle.submission.agent_task_processing.agent_task_submission_service import (
        AgentTaskSubmissionService,
    )

    stored = []

    class DbService:
        async def store_agent_task(self, **kwargs):
            stored.append(kwargs)

        async def update_agent_task_status(self, **_kwargs):
            return None

        async def update_agent_task_screen_context(self, **_kwargs):
            return None

    class RoutingService:
        async def generate_agent_task_title(self, *_args):
            return None

    submission = AgentTaskSubmissionService(
        db_service=DbService(),
        screen_context_service=SimpleNamespace(
            capture_screen_context=AsyncMock(return_value={}),
        ),
        routing_service=RoutingService(),
        processing_service=SimpleNamespace(),
    )

    await submission.process_agent_task(
        agent_task="Conversation-delegated task",
        agent_task_id="conversation-task-1",
        conversation_id="conversation-1",
    )
    await submission.process_agent_task(
        agent_task="Ordinary task",
        agent_task_id="ordinary-task-1",
    )
    await asyncio.sleep(0)

    assert stored[0]["accumulated_artifacts"] == {"conversation_id": "conversation-1"}
    assert stored[1]["accumulated_artifacts"] is None
