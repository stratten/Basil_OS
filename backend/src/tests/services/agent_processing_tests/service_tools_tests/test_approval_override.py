"""Unit tests for per-run approval-policy override (test-only registry)."""

from types import SimpleNamespace

import pytest

from api.core.models.preferences import (
    ExecutionApprovalMode,
    ToolExecutionSettings,
)
from api.services.agent_processing.tools.safety.approval_override import (
    ApprovalOverride,
    _MAX_OVERRIDES,
    clear_override,
    register_override,
    resolve_tool_execution_settings,
)
from api.services.agent_processing.tools.safety.execution_approval_service import (
    ExecutionApprovalService,
)


def _stub_preferences() -> SimpleNamespace:
    return SimpleNamespace(
        tool_execution=ToolExecutionSettings(
            approval_mode=ExecutionApprovalMode.WHITELIST_ONLY,
            whitelisted_commands=[],
            auto_approve_read_only=False,
            safe_execution_mode=False,
        )
    )


@pytest.fixture
def stubbed_preferences(monkeypatch):
    stub = _stub_preferences()
    monkeypatch.setattr(
        "api.services.agent_processing.tools.safety.approval_override.load_preferences",
        lambda: stub,
    )
    return stub


def test_resolve_without_override_returns_global_settings(stubbed_preferences):
    settings = resolve_tool_execution_settings(None)
    assert settings is stubbed_preferences.tool_execution
    assert settings.approval_mode == ExecutionApprovalMode.WHITELIST_ONLY


def test_resolve_with_override_layers_without_mutating_global(stubbed_preferences):
    task_id = "task-override-merge"
    register_override(
        task_id,
        ApprovalOverride(approval_mode=ExecutionApprovalMode.ALWAYS_APPROVE),
    )
    try:
        merged = resolve_tool_execution_settings({"agent_task_id": task_id})
        assert merged is not stubbed_preferences.tool_execution
        assert merged.approval_mode == ExecutionApprovalMode.ALWAYS_APPROVE
        assert stubbed_preferences.tool_execution.approval_mode == ExecutionApprovalMode.WHITELIST_ONLY
        assert merged.auto_approve_read_only is False
    finally:
        clear_override(task_id)


def test_registry_size_cap_evicts_oldest():
    registered_ids = [f"cap-test-{idx}" for idx in range(_MAX_OVERRIDES + 5)]
    try:
        for task_id in registered_ids:
            register_override(
                task_id,
                ApprovalOverride(approval_mode=ExecutionApprovalMode.ALWAYS_APPROVE),
            )
        from api.services.agent_processing.tools.safety.approval_override import _OVERRIDES

        assert len(_OVERRIDES) == _MAX_OVERRIDES
        assert registered_ids[0] not in _OVERRIDES
        assert registered_ids[-1] in _OVERRIDES
    finally:
        for task_id in registered_ids:
            clear_override(task_id)


@pytest.mark.asyncio
async def test_evaluate_command_honors_always_approve_override(stubbed_preferences):
    task_id = "task-eval-always-approve"
    register_override(
        task_id,
        ApprovalOverride(approval_mode=ExecutionApprovalMode.ALWAYS_APPROVE),
    )
    try:
        service = ExecutionApprovalService(websocket_manager=None)
        decision = await service.evaluate_command(
            "git status",
            {"agent_task_id": task_id},
        )
        assert decision.needs_approval is False
    finally:
        clear_override(task_id)


@pytest.mark.asyncio
async def test_evaluate_command_without_override_requires_approval(stubbed_preferences):
    service = ExecutionApprovalService(websocket_manager=None)
    decision = await service.evaluate_command(
        "git status",
        {"agent_task_id": "task-no-override"},
    )
    assert decision.needs_approval is True
