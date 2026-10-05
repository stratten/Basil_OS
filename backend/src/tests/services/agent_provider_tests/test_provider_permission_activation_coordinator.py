"""Unit coverage for ProviderPermissionActivationCoordinator (Package 4B.3)."""

from __future__ import annotations

import asyncio
import logging

import pytest

from api.services.agent_providers.acp.session_client import AcpRequestError
from api.services.agent_providers.interaction_delivery import (
    ProviderInteractionDeliveryRegistry,
)
from api.services.agent_processing.lifecycle.submission.agent_task_processing.provider_permission_activation_coordinator import (
    ProviderPermissionActivationCoordinator,
)


class _FakePermissionRepository:
    def __init__(self) -> None:
        self.created: list[dict] = []
        self.canceled: list[str] = []
        self._next_id = 0

    async def create_permission_interaction(self, **kwargs):
        self._next_id += 1
        record = {
            **kwargs,
            "id": f"permission-{self._next_id}",
            "revision": 0,
            "status": "pending",
            "requested_schema": {"subject": kwargs["action_summary"]["subject"]},
        }
        self.created.append(record)
        return record

    async def get_interaction(self, interaction_id: str):
        for record in self.created:
            if record["id"] == interaction_id:
                return record
        return None

    async def cancel_permission_interaction(self, **kwargs):
        interaction_id = kwargs["interaction_id"]
        self.canceled.append(interaction_id)
        for record in self.created:
            if record["id"] == interaction_id:
                record["status"] = "canceled"
        return {"id": interaction_id, "status": "canceled"}

    async def supersede_pending_for_run(self, provider_run_id: str) -> int:
        return 1


class _FakeRoutingService:
    def __init__(self, *, websocket_manager: object | None = None) -> None:
        self.websocket_manager = websocket_manager
        self.requests: list[dict] = []
        self.resolutions: list[dict] = []
        self.publish_result = True

    async def publish_provider_permission_request(self, **kwargs):
        self.requests.append(kwargs)
        return self.publish_result

    async def publish_provider_permission_resolved(self, **kwargs):
        self.resolutions.append(kwargs)
        return True


def _make_coordinator(
    repository: _FakePermissionRepository,
    routing: _FakeRoutingService,
    *,
    protocol_version: int = 2,
) -> ProviderPermissionActivationCoordinator:
    coordinator = ProviderPermissionActivationCoordinator(
        routing_service=routing,
        provider_interaction_repository=repository,
        agent_task_id="task-1",
        root_task_id="task-1",
        previous_task_id=None,
        provider_run_id="run-1",
        logger=logging.getLogger("test-permission-activation"),
        protocol_version=protocol_version,
    )
    coordinator.bind_session("session-1")
    return coordinator


def _allow_option(option_id: str = "allow-once") -> dict:
    return {"optionId": option_id, "name": "Allow", "kind": "allow_once"}


def _reject_option(option_id: str = "reject-once") -> dict:
    return {"optionId": option_id, "name": "Reject", "kind": "reject_once"}


def _permission_params(**overrides) -> dict:
    params = {
        "sessionId": "session-1",
        "title": "Run this command?",
        "description": "The provider wants to proceed.",
        "options": [_allow_option(), _reject_option()],
        "subject": {"type": "command", "command": "rm -rf /tmp/scratch", "cwd": "/tmp"},
    }
    params.update(overrides)
    return params


@pytest.fixture(autouse=True)
def _clear_registry():
    yield
    ProviderInteractionDeliveryRegistry._pending.clear()
    ProviderInteractionDeliveryRegistry._resolving.clear()


@pytest.mark.asyncio
async def test_v1_permission_request_fails_closed_without_a_websocket_manager() -> None:
    repository = _FakePermissionRepository()
    routing = _FakeRoutingService(websocket_manager=None)
    coordinator = _make_coordinator(repository, routing, protocol_version=1)

    result = await coordinator.handle_request_permission(
        {
            "sessionId": "session-1",
            "toolCall": {"toolCallId": "call-1", "title": "Read README"},
            "options": [_reject_option()],
        }
    )

    assert result == {"outcome": {"outcome": "selected", "optionId": "reject-once"}}
    assert repository.created == []
    assert routing.requests == []


@pytest.mark.asyncio
async def test_handle_request_permission_fails_closed_without_websocket_manager() -> None:
    repository = _FakePermissionRepository()
    routing = _FakeRoutingService(websocket_manager=None)
    coordinator = _make_coordinator(repository, routing)

    result = await coordinator.handle_request_permission(_permission_params())

    assert result == {"outcome": {"outcome": "selected", "optionId": "reject-once"}}
    assert repository.created == []
    assert routing.requests == []


@pytest.mark.asyncio
async def test_handle_request_permission_returns_allow_when_user_selects_allow() -> None:
    repository = _FakePermissionRepository()
    routing = _FakeRoutingService(websocket_manager=object())
    coordinator = _make_coordinator(repository, routing)

    original_publish = routing.publish_provider_permission_request

    async def publish_and_deliver(**kwargs):
        await original_publish(**kwargs)
        interaction_id = kwargs["interaction_id"]
        ProviderInteractionDeliveryRegistry.resolve(
            interaction_id, "selected", {"optionId": "allow-once"}
        )
        return True

    routing.publish_provider_permission_request = publish_and_deliver

    result = await coordinator.handle_request_permission(_permission_params())

    assert result == {"outcome": {"outcome": "selected", "optionId": "allow-once"}}
    assert len(repository.created) == 1
    assert repository.canceled == []
    assert routing.requests[0]["subject"] == {
        "type": "command",
        "command": "rm -rf /tmp/scratch",
        "cwd": "/tmp",
    }
    assert routing.resolutions == [{
        "agent_task_id": "task-1",
        "root_task_id": "task-1",
        "previous_task_id": None,
        "interaction_id": "permission-1",
        "status": "approved",
        "response": "Allow",
    }]


@pytest.mark.asyncio
async def test_handle_request_permission_records_a_user_rejection_with_the_chosen_option() -> None:
    repository = _FakePermissionRepository()
    routing = _FakeRoutingService(websocket_manager=object())
    coordinator = _make_coordinator(repository, routing)

    async def publish_and_reject(**kwargs):
        ProviderInteractionDeliveryRegistry.resolve(
            kwargs["interaction_id"], "selected", {"optionId": "reject-once"}
        )
        return True

    routing.publish_provider_permission_request = publish_and_reject

    result = await coordinator.handle_request_permission(_permission_params())

    assert result == {"outcome": {"outcome": "selected", "optionId": "reject-once"}}
    assert repository.canceled == []
    assert routing.resolutions[0]["status"] == "denied"
    assert routing.resolutions[0]["response"] == "Reject"


@pytest.mark.asyncio
async def test_handle_request_permission_cancels_pending_row_when_resolution_is_cancel() -> None:
    repository = _FakePermissionRepository()
    routing = _FakeRoutingService(websocket_manager=object())
    coordinator = _make_coordinator(repository, routing)

    async def publish_and_cancel(**kwargs):
        interaction_id = kwargs["interaction_id"]
        ProviderInteractionDeliveryRegistry.resolve(interaction_id, "cancel", None)
        return True

    routing.publish_provider_permission_request = publish_and_cancel

    result = await coordinator.handle_request_permission(_permission_params())

    assert result == {"outcome": {"outcome": "selected", "optionId": "reject-once"}}
    assert len(repository.created) == 1
    assert repository.canceled == ["permission-1"]
    assert routing.resolutions == [{
        "agent_task_id": "task-1",
        "root_task_id": "task-1",
        "previous_task_id": None,
        "interaction_id": "permission-1",
        "status": "cancelled",
        "response": None,
    }]


@pytest.mark.asyncio
async def test_handle_request_permission_falls_back_when_publish_returns_false() -> None:
    repository = _FakePermissionRepository()
    routing = _FakeRoutingService(websocket_manager=object())
    routing.publish_result = False
    coordinator = _make_coordinator(repository, routing)

    result = await coordinator.handle_request_permission(_permission_params())

    assert result == {"outcome": {"outcome": "selected", "optionId": "reject-once"}}
    assert len(repository.created) == 1
    assert repository.canceled == ["permission-1"]


@pytest.mark.asyncio
async def test_handle_request_permission_rejects_when_no_reject_kind_option_exists() -> None:
    repository = _FakePermissionRepository()
    routing = _FakeRoutingService(websocket_manager=object())
    coordinator = _make_coordinator(repository, routing)

    with pytest.raises(AcpRequestError) as exc_info:
        await coordinator.handle_request_permission(
            _permission_params(options=[_allow_option()])
        )

    assert exc_info.value.code == -32601
    assert repository.created == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "params",
    [
        {"title": ""},
        {"options": []},
        {
            "options": [
                {"optionId": "dup", "name": "Allow", "kind": "allow_once"},
                {"optionId": "dup", "name": "Reject", "kind": "reject_once"},
            ]
        },
        {"sessionId": "wrong-session"},
    ],
)
async def test_handle_request_permission_rejects_malformed_requests(params: dict) -> None:
    repository = _FakePermissionRepository()
    routing = _FakeRoutingService(websocket_manager=object())
    coordinator = _make_coordinator(repository, routing)

    with pytest.raises(AcpRequestError) as exc_info:
        await coordinator.handle_request_permission(_permission_params(**params))

    assert exc_info.value.code == -32602
    assert repository.created == []


@pytest.mark.asyncio
async def test_cancel_pending_interaction_supersedes_and_resolves_future() -> None:
    repository = _FakePermissionRepository()
    routing = _FakeRoutingService(websocket_manager=object())
    coordinator = _make_coordinator(repository, routing)

    task = asyncio.create_task(coordinator.handle_request_permission(_permission_params()))
    await asyncio.sleep(0.05)
    assert coordinator._active_interaction_id is not None
    await coordinator.cancel_pending_interaction()
    result = await task

    assert result == {"outcome": {"outcome": "selected", "optionId": "reject-once"}}
