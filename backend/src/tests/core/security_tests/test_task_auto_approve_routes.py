"""The per-task auto-approve routes: who may change the switch, the native confirmation, and what turning it on does."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.core.security.backend_credentials import BACKEND_TOKEN_HEADER, get_backend_credential_store
from api.core.security.execution_approval_risk import (
    RISK_CONFIRMATION_HEADER,
    RISK_CONFIRMATION_REQUIRED_CODE,
    RISK_CONFIRMATION_REQUIRED_STATUS,
)
from api.main import app
from api.routes.agent_tasks import execution_approval_routes
from api.services.agent_processing.tools.safety.task_auto_approve import (
    clear_all_task_auto_approve,
    is_task_auto_approve_enabled,
    set_task_auto_approve,
)

PATH = "/api/v1/agent-tasks/auto-approve/root-1"
CONFIRMED = {RISK_CONFIRMATION_HEADER: "true"}


class _RecordingApprovalService:
    def __init__(self, waiting: int = 0) -> None:
        self.waiting = waiting
        self.approved_for: list[str] = []

    async def approve_waiting_for_task(self, root_task_id: str) -> int:
        self.approved_for.append(root_task_id)
        return self.waiting


@pytest.fixture(autouse=True)
def _clean_switches():
    clear_all_task_auto_approve()
    yield
    clear_all_task_auto_approve()


@pytest.fixture
def approval_service():
    service = _RecordingApprovalService(waiting=2)
    app.dependency_overrides[execution_approval_routes.get_approval_service] = lambda: service
    yield service
    app.dependency_overrides.pop(execution_approval_routes.get_approval_service, None)


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_the_switch_reads_off_by_default(client: TestClient) -> None:
    response = client.get(PATH)

    assert response.status_code == 200
    assert response.json() == {"enabled": False, "approved_waiting": 0}


def test_the_task_windows_can_read_the_switch_with_the_web_credential() -> None:
    set_task_auto_approve("root-1", True)
    webview_token = get_backend_credential_store().current().webview_token

    response = TestClient(app, headers={BACKEND_TOKEN_HEADER: webview_token}).get(PATH)

    assert response.status_code == 200
    assert response.json()["enabled"] is True


def test_the_web_credential_cannot_change_the_switch(approval_service: _RecordingApprovalService) -> None:
    webview_token = get_backend_credential_store().current().webview_token
    web_client = TestClient(app, headers={BACKEND_TOKEN_HEADER: webview_token})

    response = web_client.post(PATH, json={"enabled": True}, headers=CONFIRMED)

    assert response.status_code == 403
    assert response.json() == {"detail": "host_credential_required"}
    assert is_task_auto_approve_enabled("root-1") is False
    assert approval_service.approved_for == []


def test_enabling_without_the_native_confirmation_returns_428_and_changes_nothing(
    client: TestClient, approval_service: _RecordingApprovalService
) -> None:
    response = client.post(PATH, json={"enabled": True})

    assert response.status_code == RISK_CONFIRMATION_REQUIRED_STATUS
    detail = response.json()["detail"]
    assert detail["code"] == RISK_CONFIRMATION_REQUIRED_CODE
    assert detail["title"] == "Approve every command for this task?"
    assert detail["message"]
    assert is_task_auto_approve_enabled("root-1") is False
    assert approval_service.approved_for == []


def test_the_confirmation_header_must_be_exactly_true(client: TestClient, approval_service: _RecordingApprovalService) -> None:
    response = client.post(PATH, json={"enabled": True}, headers={RISK_CONFIRMATION_HEADER: "yes"})

    assert response.status_code == RISK_CONFIRMATION_REQUIRED_STATUS
    assert is_task_auto_approve_enabled("root-1") is False


def test_a_confirmed_enable_turns_it_on_and_approves_the_waiting_cards(
    client: TestClient, approval_service: _RecordingApprovalService
) -> None:
    response = client.post(PATH, json={"enabled": True}, headers=CONFIRMED)

    assert response.status_code == 200
    assert response.json() == {"enabled": True, "approved_waiting": 2}
    assert is_task_auto_approve_enabled("root-1") is True
    assert approval_service.approved_for == ["root-1"]
    assert client.get(PATH).json()["enabled"] is True


def test_enabling_one_task_does_not_enable_another(client: TestClient, approval_service: _RecordingApprovalService) -> None:
    client.post(PATH, json={"enabled": True}, headers=CONFIRMED)

    assert client.get("/api/v1/agent-tasks/auto-approve/root-2").json()["enabled"] is False


def test_enabling_again_needs_no_second_confirmation_and_approves_nothing_more(
    client: TestClient, approval_service: _RecordingApprovalService
) -> None:
    client.post(PATH, json={"enabled": True}, headers=CONFIRMED)

    again = client.post(PATH, json={"enabled": True})

    assert again.status_code == 200
    assert again.json() == {"enabled": True, "approved_waiting": 0}
    assert approval_service.approved_for == ["root-1"]


def test_turning_it_off_needs_no_confirmation(client: TestClient, approval_service: _RecordingApprovalService) -> None:
    set_task_auto_approve("root-1", True)

    response = client.post(PATH, json={"enabled": False})

    assert response.status_code == 200
    assert response.json() == {"enabled": False, "approved_waiting": 0}
    assert is_task_auto_approve_enabled("root-1") is False
    assert approval_service.approved_for == []


def test_a_malformed_body_is_rejected(client: TestClient, approval_service: _RecordingApprovalService) -> None:
    assert client.post(PATH, json={}, headers=CONFIRMED).status_code == 422
    assert client.post(PATH, json={"enabled": "maybe"}, headers=CONFIRMED).status_code == 422
    assert is_task_auto_approve_enabled("root-1") is False


def test_an_oversized_or_blank_task_id_is_rejected(client: TestClient, approval_service: _RecordingApprovalService) -> None:
    too_long = "x" * 201

    assert client.post(f"/api/v1/agent-tasks/auto-approve/{too_long}", json={"enabled": True}, headers=CONFIRMED).status_code == 400
    assert client.get(f"/api/v1/agent-tasks/auto-approve/{too_long}").status_code == 400
    assert client.post("/api/v1/agent-tasks/auto-approve/%20", json={"enabled": True}, headers=CONFIRMED).status_code == 400
