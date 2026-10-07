"""Unit coverage for ProviderInteractionCoordinator's schema handling and lifecycle (Package 4A)."""

from __future__ import annotations

import asyncio

import pytest

from api.services.agent_providers.acp.session_client import AcpRequestError
from api.services.agent_providers.interaction_delivery import (
    ProviderInteractionDeliveryRegistry,
)
from api.services.agent_processing.lifecycle.submission.agent_task_processing.provider_interaction_coordinator import (
    ProviderInteractionCoordinator,
    validate_submitted_values,
)


class _FakeRepository:
    def __init__(self) -> None:
        self.created: list[dict] = []
        self.resolutions: list[tuple[str, str]] = []
        self.superseded_runs: list[str] = []
        self._next_id = 0

    async def create_interaction(self, **kwargs):
        self._next_id += 1
        record = {**kwargs, "id": f"interaction-{self._next_id}", "revision": 0, "status": "pending"}
        self.created.append(record)
        return record

    async def get_interaction(self, interaction_id: str):
        for record in self.created:
            if record["id"] == interaction_id:
                return record
        return None

    async def mark_answered(self, *, interaction_id: str, expected_revision: int, submitted_values):
        self.resolutions.append((interaction_id, "accept"))
        return {"id": interaction_id, "status": "answered"}

    async def mark_declined(self, *, interaction_id: str, expected_revision: int):
        self.resolutions.append((interaction_id, "decline"))
        return {"id": interaction_id, "status": "declined"}

    async def mark_canceled(self, *, interaction_id: str, expected_revision: int):
        self.resolutions.append((interaction_id, "cancel"))
        return {"id": interaction_id, "status": "canceled"}

    async def supersede_pending_for_run(self, provider_run_id: str) -> int:
        self.superseded_runs.append(provider_run_id)
        return 1


class _FakeRoutingService:
    def __init__(self) -> None:
        self.requests: list[dict] = []
        self.resolutions: list[dict] = []
        self.on_request = None

    async def publish_provider_interaction_request(self, **kwargs):
        self.requests.append(kwargs)
        if self.on_request is not None:
            self.on_request(kwargs)
        return True

    async def publish_provider_interaction_resolved(self, **kwargs):
        self.resolutions.append(kwargs)
        return True


def _make_coordinator(repository: _FakeRepository, routing: _FakeRoutingService) -> ProviderInteractionCoordinator:
    coordinator = ProviderInteractionCoordinator(
        routing_service=routing,
        provider_interaction_repository=repository,
        agent_task_id="task-1",
        root_task_id="task-1",
        previous_task_id=None,
        provider_run_id="run-1",
    )
    coordinator.bind_session("session-1")
    return coordinator


@pytest.mark.asyncio
async def test_handle_elicitation_create_declines_an_unsupported_schema_without_persisting(monkeypatch) -> None:
    repository = _FakeRepository()
    routing = _FakeRoutingService()
    coordinator = _make_coordinator(repository, routing)

    result = await coordinator.handle_elicitation_create(
        {
            "sessionId": "session-1",
            "mode": "form",
            "message": "How many retries?",
            "requestedSchema": {"type": "object", "properties": {"retries": {"type": "number"}}},
        }
    )

    assert result == {"outcome": "decline"}
    assert repository.created == []
    assert routing.requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "requested_schema",
    [
        {"type": "object", "properties": {"strategy": {"type": "string"}}, "required": "strategy"},
        {
            "type": "object",
            "properties": {"strategy": {"type": "string"}},
            "required": ["unknown"],
        },
        {"type": "object", "properties": {"strategy": {"type": "string", "default": 1}}},
        {"type": "object", "properties": {"strategy": {"type": "string", "minLength": 1}}},
    ],
)
async def test_handle_elicitation_create_declines_schema_constraints_that_basil_cannot_render(
    requested_schema: dict,
) -> None:
    repository = _FakeRepository()
    routing = _FakeRoutingService()
    coordinator = _make_coordinator(repository, routing)

    result = await coordinator.handle_elicitation_create(
        {
            "sessionId": "session-1",
            "mode": "form",
            "message": "Pick a strategy",
            "requestedSchema": requested_schema,
        }
    )

    assert result == {"outcome": "decline"}
    assert repository.created == []


@pytest.mark.asyncio
async def test_handle_elicitation_create_rejects_a_non_form_mode() -> None:
    repository = _FakeRepository()
    routing = _FakeRoutingService()
    coordinator = _make_coordinator(repository, routing)

    with pytest.raises(AcpRequestError) as excinfo:
        await coordinator.handle_elicitation_create(
            {"sessionId": "session-1", "mode": "url", "requestedSchema": {"type": "object", "properties": {}}}
        )
    assert excinfo.value.code == -32602


@pytest.mark.asyncio
async def test_handle_elicitation_create_rejects_a_mismatched_session_id() -> None:
    repository = _FakeRepository()
    routing = _FakeRoutingService()
    coordinator = _make_coordinator(repository, routing)

    with pytest.raises(AcpRequestError) as excinfo:
        await coordinator.handle_elicitation_create(
            {
                "sessionId": "some-other-session",
                "mode": "form",
                "requestedSchema": {"type": "object", "properties": {"x": {"type": "string"}}},
            }
        )
    assert excinfo.value.code == -32602


@pytest.mark.asyncio
async def test_handle_elicitation_create_persists_publishes_awaits_and_resolves_on_accept() -> None:
    repository = _FakeRepository()
    routing = _FakeRoutingService()
    coordinator = _make_coordinator(repository, routing)

    async def _run():
        return await coordinator.handle_elicitation_create(
            {
                "sessionId": "session-1",
                "mode": "form",
                "message": "Pick a strategy",
                "requestedSchema": {
                    "type": "object",
                    "properties": {"strategy": {"type": "string", "enum": ["conservative", "balanced"]}},
                    "required": ["strategy"],
                },
            }
        )

    task = asyncio.create_task(_run())
    for _ in range(50):
        if repository.created:
            break
        await asyncio.sleep(0.01)
    assert len(repository.created) == 1
    interaction_id = repository.created[0]["id"]
    assert routing.requests[0]["fields"][0]["name"] == "strategy"

    delivered = ProviderInteractionDeliveryRegistry.resolve(interaction_id, "accept", {"strategy": "balanced"})
    assert delivered is True

    result = await asyncio.wait_for(task, timeout=2.0)
    assert result == {"outcome": "accept", "content": {"strategy": "balanced"}}
    assert repository.resolutions == [(interaction_id, "accept")]
    assert len(routing.resolutions) == 1
    assert routing.resolutions[0]["interaction_id"] == interaction_id
    assert routing.resolutions[0]["status"] == "answered"
    assert routing.resolutions[0]["response"] == "strategy: balanced"


@pytest.mark.asyncio
async def test_handle_elicitation_records_a_decline_without_a_response() -> None:
    repository = _FakeRepository()
    routing = _FakeRoutingService()
    coordinator = _make_coordinator(repository, routing)
    routing.on_request = lambda request: ProviderInteractionDeliveryRegistry.resolve(
        request["interaction_id"], "decline", None
    )

    result = await coordinator.handle_elicitation_create(
        {
            "sessionId": "session-1",
            "mode": "form",
            "message": "Pick a strategy",
            "requestedSchema": {"type": "object", "properties": {"strategy": {"type": "string"}}},
        }
    )

    assert result == {"outcome": "decline"}
    assert routing.resolutions[0]["status"] == "denied"
    assert routing.resolutions[0]["response"] is None


@pytest.mark.asyncio
async def test_handle_elicitation_registers_delivery_before_publishing_to_the_ui() -> None:
    repository = _FakeRepository()
    routing = _FakeRoutingService()
    coordinator = _make_coordinator(repository, routing)

    def _resolve_immediately(request: dict) -> None:
        assert ProviderInteractionDeliveryRegistry.resolve(
            request["interaction_id"], "accept", {"strategy": "balanced"}
        )

    routing.on_request = _resolve_immediately
    result = await coordinator.handle_elicitation_create(
        {
            "sessionId": "session-1",
            "mode": "form",
            "message": "Pick a strategy",
            "requestedSchema": {
                "type": "object",
                "properties": {"strategy": {"type": "string", "enum": ["balanced"]}},
            },
        }
    )

    assert result == {"outcome": "accept", "content": {"strategy": "balanced"}}


@pytest.mark.asyncio
async def test_cancel_pending_interaction_resolves_the_active_future_and_supersedes_the_run() -> None:
    repository = _FakeRepository()
    routing = _FakeRoutingService()
    coordinator = _make_coordinator(repository, routing)

    async def _run():
        return await coordinator.handle_elicitation_create(
            {
                "sessionId": "session-1",
                "mode": "form",
                "message": "Pick a strategy",
                "requestedSchema": {"type": "object", "properties": {"strategy": {"type": "string"}}},
            }
        )

    task = asyncio.create_task(_run())
    for _ in range(50):
        if repository.created:
            break
        await asyncio.sleep(0.01)

    await coordinator.cancel_pending_interaction()
    result = await asyncio.wait_for(task, timeout=2.0)

    assert result == {"outcome": "cancel"}
    assert repository.superseded_runs == ["run-1"]
    assert routing.resolutions[-1]["status"] == "canceled"


def test_validate_submitted_values_rejects_an_unknown_field() -> None:
    fields = [{"name": "strategy", "kind": "text", "required": True, "options": None}]
    with pytest.raises(ValueError):
        validate_submitted_values(fields, {"strategy": "balanced", "extra": "nope"})


def test_validate_submitted_values_rejects_a_missing_required_field() -> None:
    fields = [{"name": "strategy", "kind": "text", "required": True, "options": None}]
    with pytest.raises(ValueError):
        validate_submitted_values(fields, {})


def test_validate_submitted_values_rejects_a_choice_value_outside_the_enum() -> None:
    fields = [
        {
            "name": "strategy",
            "kind": "choice",
            "required": True,
            "options": [{"id": "a", "label": "balanced", "value": "balanced"}],
        }
    ]
    with pytest.raises(ValueError):
        validate_submitted_values(fields, {"strategy": "aggressive"})


def test_validate_submitted_values_accepts_a_valid_choice_value() -> None:
    fields = [
        {
            "name": "strategy",
            "kind": "choice",
            "required": True,
            "options": [{"id": "a", "label": "balanced", "value": "balanced"}],
        }
    ]
    assert validate_submitted_values(fields, {"strategy": "balanced"}) == {"strategy": "balanced"}
