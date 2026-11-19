"""Waiting on the user for provider permission, provider input, or Keychain access must not consume the workflow budget."""

from __future__ import annotations

import asyncio
import logging

import pytest

from api.services.agent_processing.lifecycle.execution_graph.workflow_deadline import WorkflowDeadline
from api.services.agent_processing.lifecycle.submission.agent_task_processing.provider_interaction_coordinator import (
    ProviderInteractionCoordinator,
)
from api.services.agent_processing.lifecycle.submission.agent_task_processing.provider_permission_activation_coordinator import (
    ProviderPermissionActivationCoordinator,
)
from api.services.agent_processing.shared.agent_runtime_context import (
    reset_current_agent_context,
    set_current_agent_context,
)
from api.services.agent_providers.interaction_delivery import ProviderInteractionDeliveryRegistry


@pytest.fixture(autouse=True)
def _clear_registry():
    yield
    ProviderInteractionDeliveryRegistry._pending.clear()
    ProviderInteractionDeliveryRegistry._resolving.clear()


@pytest.fixture
def deadline_context():
    deadline = WorkflowDeadline.start(total_seconds=100, finalization_reserve_seconds=0)
    token = set_current_agent_context({"agent_task_id": "task-1", "_workflow_deadline": deadline})
    try:
        yield deadline
    finally:
        reset_current_agent_context(token)


async def _observe_pause(deadline: WorkflowDeadline, observed: list) -> None:
    for _ in range(50):
        if deadline.is_paused:
            break
        await asyncio.sleep(0)
    observed.append(deadline.pause_reasons)


class _PermissionRepository:
    def __init__(self) -> None:
        self.created: list[dict] = []

    async def create_permission_interaction(self, **kwargs):
        record = {
            **kwargs,
            "id": f"permission-{len(self.created) + 1}",
            "revision": 0,
            "status": "pending",
            "requested_schema": {"subject": kwargs["action_summary"]["subject"]},
        }
        self.created.append(record)
        return record

    async def get_interaction(self, interaction_id: str):
        return next((record for record in self.created if record["id"] == interaction_id), None)

    async def cancel_permission_interaction(self, **kwargs):
        return {"id": kwargs["interaction_id"], "status": "canceled"}

    async def supersede_pending_for_run(self, provider_run_id: str) -> int:
        return 1


class _PermissionRouting:
    def __init__(self, on_publish) -> None:
        self.websocket_manager = object()
        self._on_publish = on_publish

    async def publish_provider_permission_request(self, **kwargs):
        self._on_publish(kwargs["interaction_id"])
        return True

    async def publish_provider_permission_resolved(self, **kwargs):
        return True


@pytest.mark.asyncio
async def test_provider_permission_wait_pauses_the_budget(deadline_context):
    observed: list = []

    async def _observe_then_allow(interaction_id: str) -> None:
        await _observe_pause(deadline_context, observed)
        ProviderInteractionDeliveryRegistry.resolve(interaction_id, "selected", {"optionId": "allow-once"})

    routing = _PermissionRouting(lambda interaction_id: asyncio.ensure_future(_observe_then_allow(interaction_id)))
    coordinator = ProviderPermissionActivationCoordinator(
        routing_service=routing,
        provider_interaction_repository=_PermissionRepository(),
        agent_task_id="task-1",
        root_task_id="task-1",
        previous_task_id=None,
        provider_run_id="run-1",
        logger=logging.getLogger("test-permission-pause"),
        protocol_version=2,
    )
    coordinator.bind_session("session-1")

    result = await coordinator.handle_request_permission(
        {
            "sessionId": "session-1",
            "title": "Run this command?",
            "description": "The provider wants to proceed.",
            "options": [
                {"optionId": "allow-once", "name": "Allow", "kind": "allow_once"},
                {"optionId": "reject-once", "name": "Reject", "kind": "reject_once"},
            ],
            "subject": {"type": "command", "command": "ls", "cwd": "/tmp"},
        }
    )

    assert result == {"outcome": {"outcome": "selected", "optionId": "allow-once"}}
    assert observed == [["provider_permission"]]
    assert deadline_context.is_paused is False


class _InteractionRepository:
    def __init__(self) -> None:
        self.created: list[dict] = []

    async def create_interaction(self, **kwargs):
        record = {**kwargs, "id": f"interaction-{len(self.created) + 1}", "revision": 0, "status": "pending"}
        self.created.append(record)
        return record

    async def get_interaction(self, interaction_id: str):
        return next((record for record in self.created if record["id"] == interaction_id), None)

    async def mark_answered(self, *, interaction_id: str, expected_revision: int, submitted_values):
        return {"id": interaction_id, "status": "answered"}

    async def mark_declined(self, *, interaction_id: str, expected_revision: int):
        return {"id": interaction_id, "status": "declined"}

    async def mark_canceled(self, *, interaction_id: str, expected_revision: int):
        return {"id": interaction_id, "status": "canceled"}

    async def supersede_pending_for_run(self, provider_run_id: str) -> int:
        return 1


class _InteractionRouting:
    def __init__(self, on_publish=None) -> None:
        self.requests: list[dict] = []
        self._on_publish = on_publish

    async def publish_provider_interaction_request(self, **kwargs):
        self.requests.append(kwargs)
        if self._on_publish is not None:
            self._on_publish(kwargs["interaction_id"])
        return True

    async def publish_provider_interaction_resolved(self, **kwargs):
        return True


def _interaction_coordinator(routing: _InteractionRouting) -> ProviderInteractionCoordinator:
    coordinator = ProviderInteractionCoordinator(
        routing_service=routing,
        provider_interaction_repository=_InteractionRepository(),
        agent_task_id="task-1",
        root_task_id="task-1",
        previous_task_id=None,
        provider_run_id="run-1",
    )
    coordinator.bind_session("session-1")
    return coordinator


_ELICITATION = {
    "sessionId": "session-1",
    "mode": "form",
    "message": "Pick a strategy",
    "requestedSchema": {
        "type": "object",
        "properties": {"strategy": {"type": "string", "enum": ["balanced"]}},
    },
}


@pytest.mark.asyncio
async def test_provider_input_wait_pauses_the_budget(deadline_context):
    observed: list = []

    async def _observe_then_answer(interaction_id: str) -> None:
        await _observe_pause(deadline_context, observed)
        ProviderInteractionDeliveryRegistry.resolve(interaction_id, "accept", {"strategy": "balanced"})

    routing = _InteractionRouting(lambda interaction_id: asyncio.ensure_future(_observe_then_answer(interaction_id)))

    result = await _interaction_coordinator(routing).handle_elicitation_create(_ELICITATION)

    assert result == {"outcome": "accept", "content": {"strategy": "balanced"}}
    assert observed == [["provider_user_input"]]
    assert deadline_context.is_paused is False


@pytest.mark.asyncio
async def test_canceling_provider_input_wait_propagates_cancellation(deadline_context):
    routing = _InteractionRouting()
    task = asyncio.create_task(_interaction_coordinator(routing).handle_elicitation_create(_ELICITATION))
    for _ in range(50):
        if routing.requests and deadline_context.is_paused:
            break
        await asyncio.sleep(0)
    assert deadline_context.is_paused is True

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert deadline_context.is_paused is False


@pytest.mark.asyncio
async def test_keychain_token_wait_pauses_the_budget(monkeypatch, deadline_context):
    from api.services.agent_processing.shared import cancellable_wait
    from api.services.mcp_connectors import swift_token_bridge

    async def _fake_broadcast(payload: dict) -> int:
        return 1

    observed: list = []

    async def _fake_wait(future, *, timeout_s, cancel_event):
        observed.append(deadline_context.pause_reasons)
        return "timeout", None

    monkeypatch.setattr(swift_token_bridge, "_broadcast_to_active_connections", _fake_broadcast)
    monkeypatch.setattr(cancellable_wait, "await_future_with_cancellation", _fake_wait)

    result = await swift_token_bridge._ask_swift_for_credentials(
        connection_id="conn-1",
        timeout_s=1.0,
        agent_task_id="task-1",
        include_refresh_token=False,
        cancel_event=None,
    )

    assert result["kind"] == "token_response_timeout"
    assert observed == [["external_service_token"]]
    assert deadline_context.is_paused is False
    assert not swift_token_bridge._token_response_waiters
