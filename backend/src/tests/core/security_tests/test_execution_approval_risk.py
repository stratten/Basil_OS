"""Tests for backend-owned approval-risk classification and the 428 confirmation contract."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from api.core.models.preferences import ExecutionApprovalMode, ToolExecutionSettings
from api.core.security.execution_approval_risk import (
    RISK_CONFIRMATION_HEADER,
    RISK_CONFIRMATION_REQUIRED_CODE,
    RISK_CONFIRMATION_REQUIRED_STATUS,
    added_whitelist_pattern_risk,
    approval_settings_change_risk,
    updated_whitelist_pattern_risk,
)
from api.main import app
from api.routes.agent_tasks import execution_approval_routes

SETTINGS_PATH = "/api/v1/agent-tasks/approval/settings"
WHITELIST_PATH = "/api/v1/agent-tasks/whitelist"
CONFIRMED = {RISK_CONFIRMATION_HEADER: "true"}


def _settings_risk(**overrides):
    arguments = {
        "requested_approval_mode": None,
        "requested_block_dangerous_patterns": None,
        "requested_safe_execution_mode": None,
        "current_approval_mode": "whitelist_only",
        "current_block_dangerous_patterns": True,
        "current_safe_execution_mode": True,
    }
    arguments.update(overrides)
    return approval_settings_change_risk(**arguments)


def test_switching_to_always_approve_is_risky() -> None:
    risk = _settings_risk(requested_approval_mode="always_approve")

    assert risk is not None
    assert risk.title == "Lower command-approval protection?"
    assert "without asking you first" in risk.message


def test_disabling_active_protections_is_risky_and_lists_every_reason() -> None:
    risk = _settings_risk(requested_block_dangerous_patterns=False, requested_safe_execution_mode=False)

    assert risk is not None
    assert risk.message.count("\n\n") == 1


def test_repeating_values_that_are_already_set_is_not_risky() -> None:
    assert _settings_risk(
        requested_approval_mode="always_approve",
        requested_block_dangerous_patterns=False,
        requested_safe_execution_mode=False,
        current_approval_mode="always_approve",
        current_block_dangerous_patterns=False,
        current_safe_execution_mode=False,
    ) is None


def test_strengthening_and_neutral_changes_are_not_risky() -> None:
    assert _settings_risk(
        requested_approval_mode="always_prompt",
        requested_block_dangerous_patterns=True,
        requested_safe_execution_mode=True,
        current_approval_mode="always_approve",
        current_block_dangerous_patterns=False,
        current_safe_execution_mode=False,
    ) is None
    assert _settings_risk() is None


def test_whitelist_additions_always_confirm_and_updates_confirm_only_broad_types() -> None:
    assert added_whitelist_pattern_risk("ls", "exact").title == "Allow this command without asking?"
    assert updated_whitelist_pattern_risk("ls -la", "exact") is None
    assert updated_whitelist_pattern_risk("git", "prefix") is not None
    assert updated_whitelist_pattern_risk(".*", "REGEX") is not None


class _PreferencesStore:
    def __init__(self) -> None:
        self.preferences = SimpleNamespace(tool_execution=ToolExecutionSettings())
        self.save_count = 0

    def load(self):
        return self.preferences

    def save(self, preferences) -> None:
        self.save_count += 1


class _RecordingApprovalService:
    def __init__(self) -> None:
        self.added: list[str] = []
        self.updated: list[str] = []

    async def add_to_whitelist(self, *, command: str, pattern_type: str, description: str, risk_level: str):
        self.added.append(command)
        return _pattern(command, pattern_type)

    async def update_whitelist_pattern(self, *, pattern_id: str, command: str, pattern_type: str, description: str):
        self.updated.append(pattern_id)
        return _pattern(command, pattern_type)


def _pattern(command: str, pattern_type: str) -> SimpleNamespace:
    return SimpleNamespace(
        id="pattern-1",
        pattern=command,
        pattern_type=pattern_type,
        description="",
        added_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
        last_used=None,
        use_count=0,
        risk_level="low",
    )


@pytest.fixture
def preferences_store(monkeypatch: pytest.MonkeyPatch) -> _PreferencesStore:
    store = _PreferencesStore()
    monkeypatch.setattr(execution_approval_routes, "load_preferences", store.load)
    monkeypatch.setattr(execution_approval_routes, "save_preferences", store.save)
    return store


@pytest.fixture
def approval_service():
    service = _RecordingApprovalService()
    app.dependency_overrides[execution_approval_routes.get_approval_service] = lambda: service
    yield service
    app.dependency_overrides.pop(execution_approval_routes.get_approval_service, None)


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_risky_settings_change_returns_428_and_saves_nothing(client: TestClient, preferences_store: _PreferencesStore) -> None:
    response = client.post(SETTINGS_PATH, json={"approval_mode": "always_approve"})

    assert response.status_code == RISK_CONFIRMATION_REQUIRED_STATUS
    detail = response.json()["detail"]
    assert detail["code"] == RISK_CONFIRMATION_REQUIRED_CODE
    assert detail["title"] == "Lower command-approval protection?"
    assert detail["message"]
    assert preferences_store.save_count == 0
    assert preferences_store.preferences.tool_execution.approval_mode == ExecutionApprovalMode.WHITELIST_ONLY


def test_confirmed_risky_settings_change_is_saved(client: TestClient, preferences_store: _PreferencesStore) -> None:
    response = client.post(SETTINGS_PATH, json={"approval_mode": "always_approve"}, headers=CONFIRMED)

    assert response.status_code == 200
    assert response.json()["approval_mode"] == "always_approve"
    assert preferences_store.save_count == 1


def test_neutral_settings_change_needs_no_confirmation(client: TestClient, preferences_store: _PreferencesStore) -> None:
    response = client.post(SETTINGS_PATH, json={"approval_timeout_seconds": 60})

    assert response.status_code == 200
    assert preferences_store.save_count == 1


def test_confirmation_header_must_be_exactly_true(client: TestClient, preferences_store: _PreferencesStore) -> None:
    response = client.post(SETTINGS_PATH, json={"approval_mode": "always_approve"}, headers={RISK_CONFIRMATION_HEADER: "yes"})

    assert response.status_code == RISK_CONFIRMATION_REQUIRED_STATUS
    assert preferences_store.save_count == 0


def test_whitelist_addition_requires_confirmation(client: TestClient, approval_service: _RecordingApprovalService) -> None:
    unconfirmed = client.post(WHITELIST_PATH, json={"pattern": "git status", "pattern_type": "exact"})
    assert unconfirmed.status_code == RISK_CONFIRMATION_REQUIRED_STATUS
    assert unconfirmed.json()["detail"]["title"] == "Allow this command without asking?"
    assert approval_service.added == []

    confirmed = client.post(WHITELIST_PATH, json={"pattern": "git status", "pattern_type": "exact"}, headers=CONFIRMED)
    assert confirmed.status_code == 200
    assert approval_service.added == ["git status"]


def test_invalid_pattern_type_is_rejected_before_any_confirmation(client: TestClient, approval_service: _RecordingApprovalService) -> None:
    response = client.post(WHITELIST_PATH, json={"pattern": "git", "pattern_type": "glob"})

    assert response.status_code == 400
    assert approval_service.added == []


def test_whitelist_update_confirms_only_broad_pattern_types(client: TestClient, approval_service: _RecordingApprovalService) -> None:
    exact = client.put(f"{WHITELIST_PATH}/pattern-1", json={"pattern": "ls -la", "pattern_type": "exact"})
    assert exact.status_code == 200

    broad = client.put(f"{WHITELIST_PATH}/pattern-1", json={"pattern": ".*", "pattern_type": "regex"})
    assert broad.status_code == RISK_CONFIRMATION_REQUIRED_STATUS
    assert approval_service.updated == ["pattern-1"]

    confirmed = client.put(f"{WHITELIST_PATH}/pattern-1", json={"pattern": ".*", "pattern_type": "regex"}, headers=CONFIRMED)
    assert confirmed.status_code == 200
    assert approval_service.updated == ["pattern-1", "pattern-1"]
