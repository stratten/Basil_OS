"""Route-contract coverage for the provider-interaction respond endpoint (Package 4A)."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes.agent_tasks import router as agent_task_router
from api.routes.agent_tasks.execution_control_routes import router as execution_control_router
from api.routes.agent_tasks.provider_interaction_routes import router as provider_interaction_router
from api.services.agent_providers.interaction_delivery import (
    ProviderInteractionDeliveryRegistry,
)
from api.services.agent_processing.tools.safety.interactive_approval import (
    InteractiveApprovalManager,
)


class _FakeInteractionRepository:
    def __init__(self, interaction: dict | None) -> None:
        self._interaction = interaction
        self.resolutions: list[str] = []

    async def get_interaction(self, interaction_id: str):
        if self._interaction is None or self._interaction["id"] != interaction_id:
            return None
        return self._interaction

    async def get_pending_interaction_for_agent_task(self, agent_task_id: str):
        if self._interaction is None:
            return None
        if self._interaction["agent_task_id"] != agent_task_id or self._interaction["status"] != "pending":
            return None
        return self._interaction

    async def mark_answered(self, *, interaction_id: str, expected_revision: int, submitted_values: dict):
        assert self._interaction is not None
        assert interaction_id == self._interaction["id"]
        assert expected_revision == self._interaction["revision"]
        self._interaction["status"] = "answered"
        self._interaction["outcome"] = "accept"
        self._interaction["submitted_values"] = submitted_values
        self.resolutions.append("accept")
        return self._interaction

    async def mark_declined(self, *, interaction_id: str, expected_revision: int):
        assert self._interaction is not None
        assert expected_revision == self._interaction["revision"]
        self._interaction["status"] = "declined"
        self._interaction["outcome"] = "decline"
        self.resolutions.append("decline")
        return self._interaction

    async def mark_cancelled(self, *, interaction_id: str, expected_revision: int):
        assert self._interaction is not None
        assert expected_revision == self._interaction["revision"]
        self._interaction["status"] = "cancelled"
        self._interaction["outcome"] = "cancel"
        self.resolutions.append("cancel")
        return self._interaction

    async def resolve_permission_interaction(
        self,
        *,
        interaction_id: str,
        provider_run_id: str,
        agent_task_id: str,
        expected_revision: int,
        selected_option_id: str,
    ):
        assert self._interaction is not None
        assert interaction_id == self._interaction["id"]
        assert expected_revision == self._interaction["revision"]
        if selected_option_id not in {option.get("optionId") for option in self._interaction["fields"]}:
            from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.providers.interaction_repository import (
                ProviderInteractionConflictError,
            )

            raise ProviderInteractionConflictError(
                f"provider interaction {interaction_id!r} does not offer option {selected_option_id!r}"
            )
        self._interaction["status"] = "answered"
        self._interaction["outcome"] = "accept"
        self._interaction["submitted_values"] = {"selected_option_id": selected_option_id}
        self.resolutions.append(f"permission:{selected_option_id}")
        return self._interaction

    async def cancel_permission_interaction(
        self,
        *,
        interaction_id: str,
        provider_run_id: str,
        agent_task_id: str,
        expected_revision: int,
    ):
        assert self._interaction is not None
        assert interaction_id == self._interaction["id"]
        assert expected_revision == self._interaction["revision"]
        self._interaction["status"] = "cancelled"
        self._interaction["outcome"] = "cancel"
        self.resolutions.append("permission:cancel")
        return self._interaction


class _FakeExecutionApprovalRepository:
    def __init__(self, approval: dict | None) -> None:
        self._approval = approval

    async def get_pending_approval_for_agent_task(self, agent_task_id: str):
        if self._approval is None:
            return None
        if self._approval["agent_task_id"] != agent_task_id or self._approval["status"] != "pending":
            return None
        return self._approval

    async def list_pending_approvals_for_agent_task(self, agent_task_id: str):
        approval = await self.get_pending_approval_for_agent_task(agent_task_id)
        return [approval] if approval is not None else []


class _FakeKnowledgeService:
    def __init__(
        self,
        *,
        interaction: dict | None,
        agent_task_status: str,
        execution_approval: dict | None = None,
    ) -> None:
        self.provider_interaction_repository = _FakeInteractionRepository(interaction)
        self.execution_approval_repository = _FakeExecutionApprovalRepository(execution_approval)
        self._agent_task_status = agent_task_status

    async def get_agent_task(self, agent_task_id: str):
        if self._agent_task_status is None:
            return None
        return SimpleNamespace(id=agent_task_id, status=self._agent_task_status)


def _make_client(fake_service: _FakeKnowledgeService) -> TestClient:
    import api.dependencies as dependencies_module

    app = FastAPI()
    app.include_router(provider_interaction_router, prefix="/api/v1/agent-tasks")
    dependencies_module.get_sqlite_knowledge_service = lambda: fake_service
    return TestClient(app)


def test_execution_approval_decision_is_registered_under_agent_tasks() -> None:
    app = FastAPI()
    app.include_router(agent_task_router)
    app.include_router(execution_control_router)
    route_paths = {
        route.path
        for route in app.routes
        if getattr(route, "methods", set())
    }

    assert "/api/v1/agent-tasks/approval/decide" in route_paths
    assert "/api/v1/agent-tasks/sessions/{agent_task_id}/checkpoint-status" in route_paths
    assert "/api/v1/agent-tasks/sessions/{agent_task_id}/continue" in route_paths
    assert "/api/v1/agent-tasks/sessions/{agent_task_id}/cancel" in route_paths
    assert not any(path.startswith("/api/collaborative-workflow/") for path in route_paths)


def _sample_interaction(*, status: str = "pending", agent_task_id: str = "task-1") -> dict:
    return {
        "id": "interaction-1",
        "provider_run_id": "run-1",
        "agent_task_id": agent_task_id,
        "interaction_kind": "provider_user_input",
        "status": status,
        "revision": 0,
        "message": "Pick a strategy",
        "fields": [
            {
                "name": "strategy",
                "kind": "choice",
                "required": True,
                "options": [{"id": "a", "label": "balanced", "value": "balanced"}],
            }
        ],
    }


@pytest.fixture(autouse=True)
def _clear_registry():
    yield
    ProviderInteractionDeliveryRegistry._pending.clear()
    ProviderInteractionDeliveryRegistry._resolving.clear()
    InteractiveApprovalManager._pending_approvals.clear()
    InteractiveApprovalManager._processing_approvals.clear()


def _register_pending_future(interaction_id: str) -> asyncio.Future:
    """Register a delivery future from sync TestClient tests (no running asyncio loop)."""
    future: asyncio.Future = asyncio.Future()
    ProviderInteractionDeliveryRegistry._pending[interaction_id] = future
    return future


def test_respond_delivers_a_valid_accept_and_returns_success() -> None:
    interaction = _sample_interaction()
    client = _make_client(_FakeKnowledgeService(interaction=interaction, agent_task_status="processing"))
    future = _register_pending_future(interaction["id"])

    response = client.post(
        "/api/v1/agent-tasks/task-1/provider-interactions/interaction-1/respond",
        json={"outcome": "accept", "values": {"strategy": "balanced"}},
    )

    assert response.status_code == 200
    assert response.json()["success"] is True
    assert future.done()
    assert future.result() == {"outcome": "accept", "values": {"strategy": "balanced"}}
    assert interaction["status"] == "answered"
    assert interaction["submitted_values"] == {"strategy": "balanced"}


def test_respond_returns_404_for_an_unknown_interaction() -> None:
    client = _make_client(_FakeKnowledgeService(interaction=None, agent_task_status="processing"))

    response = client.post(
        "/api/v1/agent-tasks/task-1/provider-interactions/missing-id/respond",
        json={"outcome": "cancel"},
    )

    assert response.status_code == 404


def test_respond_returns_404_when_interaction_belongs_to_a_different_agent_task() -> None:
    interaction = _sample_interaction(agent_task_id="task-other")
    client = _make_client(_FakeKnowledgeService(interaction=interaction, agent_task_status="processing"))

    response = client.post(
        "/api/v1/agent-tasks/task-1/provider-interactions/interaction-1/respond",
        json={"outcome": "cancel"},
    )

    assert response.status_code == 404


def test_respond_returns_409_when_the_interaction_is_no_longer_pending() -> None:
    interaction = _sample_interaction(status="answered")
    client = _make_client(_FakeKnowledgeService(interaction=interaction, agent_task_status="processing"))

    response = client.post(
        "/api/v1/agent-tasks/task-1/provider-interactions/interaction-1/respond",
        json={"outcome": "cancel"},
    )

    assert response.status_code == 409


def test_respond_returns_409_when_the_agent_task_is_terminal() -> None:
    interaction = _sample_interaction()
    client = _make_client(_FakeKnowledgeService(interaction=interaction, agent_task_status="completed"))

    response = client.post(
        "/api/v1/agent-tasks/task-1/provider-interactions/interaction-1/respond",
        json={"outcome": "cancel"},
    )

    assert response.status_code == 409


def test_respond_returns_422_when_accept_values_violate_the_declared_enum() -> None:
    interaction = _sample_interaction()
    client = _make_client(_FakeKnowledgeService(interaction=interaction, agent_task_status="processing"))
    _register_pending_future(interaction["id"])

    response = client.post(
        "/api/v1/agent-tasks/task-1/provider-interactions/interaction-1/respond",
        json={"outcome": "accept", "values": {"strategy": "aggressive"}},
    )

    assert response.status_code == 422


def test_respond_returns_409_when_the_registry_has_no_matching_future() -> None:
    interaction = _sample_interaction()
    client = _make_client(_FakeKnowledgeService(interaction=interaction, agent_task_status="processing"))
    # Deliberately do not register a future: simulates a stale/duplicate answer.

    response = client.post(
        "/api/v1/agent-tasks/task-1/provider-interactions/interaction-1/respond",
        json={"outcome": "cancel"},
    )

    assert response.status_code == 409
    assert interaction["status"] == "pending"


def test_pending_interaction_returns_only_when_a_live_delivery_future_exists() -> None:
    interaction = _sample_interaction()
    client = _make_client(_FakeKnowledgeService(interaction=interaction, agent_task_status="processing"))

    no_live_run = client.get("/api/v1/agent-tasks/task-1/provider-interactions/pending")
    assert no_live_run.status_code == 200
    assert no_live_run.json() == {"interaction": None}

    _register_pending_future(interaction["id"])
    response = client.get("/api/v1/agent-tasks/task-1/provider-interactions/pending")

    assert response.status_code == 200
    assert response.json()["interaction"] == {
        "id": "interaction-1",
        "message": "Pick a strategy",
        "fields": interaction["fields"],
    }


def test_pending_execution_approval_uses_the_agent_task_api_path_and_requires_a_live_future() -> None:
    approval = {
        "id": "approval-1",
        "agent_task_id": "task-1",
        "status": "pending",
        "command": "pwd",
        "reason": "Not whitelisted",
        "risk_level": "low",
        "generalized_pattern": "pwd",
        "execution_type": "shell",
        "script_content": None,
        "revision": 0,
        "render_context": {"cwd": "/tmp", "source": "shell_service"},
    }
    client = _make_client(
        _FakeKnowledgeService(
            interaction=None,
            agent_task_status="awaiting_user_input",
            execution_approval=approval,
        )
    )

    no_live_run = client.get("/api/v1/agent-tasks/task-1/execution-approvals/pending")
    assert no_live_run.status_code == 200
    assert no_live_run.json() == {
        "approvals": [],
        "orphaned_approval_ids": ["approval-1"],
    }

    InteractiveApprovalManager._pending_approvals[approval["id"]] = asyncio.Future()
    response = client.get("/api/v1/agent-tasks/task-1/execution-approvals/pending")

    assert response.status_code == 200
    assert response.json() == {
        "approvals": [{
            "approval_id": "approval-1",
            "agent_task_id": "task-1",
            "command": "pwd",
            "reason": "Not whitelisted",
            "risk_level": "low",
            "generalized_pattern": "pwd",
            "execution_type": "shell",
            "script_content": None,
            "revision": 0,
            "context": {"cwd": "/tmp", "source": "shell_service", "description": None},
            "risk_metadata": None,
        }],
        "orphaned_approval_ids": [],
    }


def _sample_permission_interaction(*, status: str = "pending", agent_task_id: str = "task-1") -> dict:
    return {
        "id": "permission-1",
        "provider_run_id": "run-1",
        "agent_task_id": agent_task_id,
        "interaction_kind": "provider_permission",
        "status": status,
        "revision": 0,
        "message": "Run this command?",
        "fields": [
            {"optionId": "allow-once", "name": "Allow", "kind": "allow_once"},
            {"optionId": "reject-once", "name": "Reject", "kind": "reject_once"},
        ],
    }


def test_permission_decision_delivers_allow_and_returns_success() -> None:
    interaction = _sample_permission_interaction()
    client = _make_client(_FakeKnowledgeService(interaction=interaction, agent_task_status="processing"))
    future = _register_pending_future(interaction["id"])

    response = client.post(
        "/api/v1/agent-tasks/task-1/provider-interactions/permission-1/permission-decision",
        json={"selected_option_id": "allow-once"},
    )

    assert response.status_code == 200
    assert response.json()["success"] is True
    assert future.done()
    assert future.result() == {"outcome": "selected", "values": {"optionId": "allow-once"}}
    assert interaction["status"] == "answered"
    assert interaction["submitted_values"] == {"selected_option_id": "allow-once"}


def test_permission_decision_delivers_reject_and_returns_success() -> None:
    interaction = _sample_permission_interaction()
    client = _make_client(_FakeKnowledgeService(interaction=interaction, agent_task_status="processing"))
    future = _register_pending_future(interaction["id"])

    response = client.post(
        "/api/v1/agent-tasks/task-1/provider-interactions/permission-1/permission-decision",
        json={"selected_option_id": "reject-once"},
    )

    assert response.status_code == 200
    assert future.result() == {"outcome": "selected", "values": {"optionId": "reject-once"}}


def test_permission_decision_cancels_durably_before_delivering() -> None:
    interaction = _sample_permission_interaction()
    client = _make_client(_FakeKnowledgeService(interaction=interaction, agent_task_status="processing"))
    future = _register_pending_future(interaction["id"])

    response = client.post(
        "/api/v1/agent-tasks/task-1/provider-interactions/permission-1/permission-decision",
        json={"outcome": "cancel"},
    )

    assert response.status_code == 200
    assert response.json()["message"] == "Provider permission prompt cancelled."
    assert interaction["status"] == "cancelled"
    assert future.result() == {"outcome": "cancel", "values": None}


def test_permission_decision_rejects_selected_option_id_on_cancel() -> None:
    interaction = _sample_permission_interaction()
    client = _make_client(_FakeKnowledgeService(interaction=interaction, agent_task_status="processing"))
    _register_pending_future(interaction["id"])

    response = client.post(
        "/api/v1/agent-tasks/task-1/provider-interactions/permission-1/permission-decision",
        json={"outcome": "cancel", "selected_option_id": "reject-once"},
    )

    assert response.status_code == 422
    assert interaction["status"] == "pending"


def test_permission_decision_rejects_a_blank_selected_option_id() -> None:
    interaction = _sample_permission_interaction()
    client = _make_client(_FakeKnowledgeService(interaction=interaction, agent_task_status="processing"))
    _register_pending_future(interaction["id"])

    response = client.post(
        "/api/v1/agent-tasks/task-1/provider-interactions/permission-1/permission-decision",
        json={"selected_option_id": "   "},
    )

    assert response.status_code == 422
    assert interaction["status"] == "pending"


def test_permission_decision_returns_422_for_non_permission_interaction() -> None:
    interaction = _sample_interaction()
    client = _make_client(_FakeKnowledgeService(interaction=interaction, agent_task_status="processing"))

    response = client.post(
        "/api/v1/agent-tasks/task-1/provider-interactions/interaction-1/permission-decision",
        json={"selected_option_id": "allow-once"},
    )

    assert response.status_code == 422


def test_permission_decision_returns_409_when_interaction_is_no_longer_pending() -> None:
    interaction = _sample_permission_interaction(status="answered")
    client = _make_client(_FakeKnowledgeService(interaction=interaction, agent_task_status="processing"))

    response = client.post(
        "/api/v1/agent-tasks/task-1/provider-interactions/permission-1/permission-decision",
        json={"selected_option_id": "allow-once"},
    )

    assert response.status_code == 409


def test_permission_decision_returns_404_for_wrong_agent_task() -> None:
    interaction = _sample_permission_interaction(agent_task_id="task-other")
    client = _make_client(_FakeKnowledgeService(interaction=interaction, agent_task_status="processing"))

    response = client.post(
        "/api/v1/agent-tasks/task-1/provider-interactions/permission-1/permission-decision",
        json={"selected_option_id": "allow-once"},
    )

    assert response.status_code == 404


def test_permission_decision_returns_409_when_agent_task_is_terminal() -> None:
    interaction = _sample_permission_interaction()
    client = _make_client(_FakeKnowledgeService(interaction=interaction, agent_task_status="completed"))

    response = client.post(
        "/api/v1/agent-tasks/task-1/provider-interactions/permission-1/permission-decision",
        json={"selected_option_id": "allow-once"},
    )

    assert response.status_code == 409


def test_permission_decision_returns_409_for_unoffered_option() -> None:
    interaction = _sample_permission_interaction()
    client = _make_client(_FakeKnowledgeService(interaction=interaction, agent_task_status="processing"))
    _register_pending_future(interaction["id"])

    response = client.post(
        "/api/v1/agent-tasks/task-1/provider-interactions/permission-1/permission-decision",
        json={"selected_option_id": "not-offered"},
    )

    assert response.status_code == 409
    assert interaction["status"] == "pending"


def test_permission_decision_returns_409_when_registry_has_no_matching_future() -> None:
    interaction = _sample_permission_interaction()
    client = _make_client(_FakeKnowledgeService(interaction=interaction, agent_task_status="processing"))

    response = client.post(
        "/api/v1/agent-tasks/task-1/provider-interactions/permission-1/permission-decision",
        json={"selected_option_id": "allow-once"},
    )

    assert response.status_code == 409
    assert interaction["status"] == "pending"
