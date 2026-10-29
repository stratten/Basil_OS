"""Read-only AppleScripts run without a prompt when the user allows it; everything else still asks."""

from __future__ import annotations

import pytest

from api.core.models.preference_models.execution_and_connections import ExecutionApprovalMode
from api.core.models.preferences import Preferences
from api.services.agent_processing.tools.direct_application_interactions.applescript_automation import generic_applescript_service
from api.services.agent_processing.tools.direct_application_interactions.applescript_automation.generic_applescript_service import (
    GenericAppleScriptService,
)

READ_ONLY_SCRIPT = 'tell application "Mail" to get subject of every message of inbox'
MUTATING_SCRIPT = 'tell application "Mail" to delete (first message of inbox)'


class _Approval:
    def __init__(self) -> None:
        self.requests = 0

    async def request_approval(self, summary, context=None):
        self.requests += 1
        return False, False, None


def _service() -> tuple[GenericAppleScriptService, _Approval]:
    service = GenericAppleScriptService()
    approval = _Approval()
    service._approval_service = approval
    return service, approval


def _preferences(monkeypatch, *, auto_approve: bool, mode: ExecutionApprovalMode = ExecutionApprovalMode.WHITELIST_ONLY) -> None:
    preferences = Preferences()
    preferences.tool_execution.auto_approve_read_only = auto_approve
    preferences.tool_execution.approval_mode = mode
    monkeypatch.setattr("api.core.preferences.preferences_io.load_preferences", lambda: preferences)


def test_a_read_only_script_gets_an_auto_approval_reason_when_the_setting_is_on(monkeypatch):
    _preferences(monkeypatch, auto_approve=True)

    assert GenericAppleScriptService()._read_only_auto_approval_reason(READ_ONLY_SCRIPT)


@pytest.mark.parametrize(
    ("script", "auto_approve", "mode"),
    [
        (READ_ONLY_SCRIPT, False, ExecutionApprovalMode.WHITELIST_ONLY),
        (READ_ONLY_SCRIPT, True, ExecutionApprovalMode.ALWAYS_PROMPT),
        (MUTATING_SCRIPT, True, ExecutionApprovalMode.WHITELIST_ONLY),
        ('display dialog "hi"', True, ExecutionApprovalMode.WHITELIST_ONLY),
    ],
)
def test_no_auto_approval_when_off_prompt_always_or_the_script_is_not_read_only(monkeypatch, script, auto_approve, mode):
    _preferences(monkeypatch, auto_approve=auto_approve, mode=mode)

    assert GenericAppleScriptService()._read_only_auto_approval_reason(script) is None


def test_a_preference_read_failure_keeps_the_prompt(monkeypatch):
    def broken():
        raise RuntimeError("preferences unreadable")

    monkeypatch.setattr("api.core.preferences.preferences_io.load_preferences", broken)

    assert GenericAppleScriptService()._read_only_auto_approval_reason(READ_ONLY_SCRIPT) is None


@pytest.mark.asyncio
async def test_execution_skips_the_prompt_for_a_read_only_script_and_keeps_it_for_a_mutating_one(monkeypatch):
    _preferences(monkeypatch, auto_approve=True)

    async def stop_before_running(*args, **kwargs):
        raise RuntimeError("stop before osascript")

    monkeypatch.setattr(generic_applescript_service.safe_spawn, "create_subprocess_exec", stop_before_running)

    read_only_service, read_only_approval = _service()
    await read_only_service.execute_applescript(READ_ONLY_SCRIPT, context={"task_description": "Read the inbox"})
    assert read_only_approval.requests == 0

    mutating_service, mutating_approval = _service()
    result = await mutating_service.execute_applescript(MUTATING_SCRIPT, context={"task_description": "Delete mail"})
    assert mutating_approval.requests == 1
    assert result.approval_denied is True


@pytest.mark.asyncio
async def test_the_dangerous_pattern_block_still_runs_before_auto_approval(monkeypatch):
    _preferences(monkeypatch, auto_approve=True)
    service, approval = _service()

    result = await service.execute_applescript('do shell script "rm -rf /"', context={"task_description": "Clean up"})

    assert result.success is False
    assert approval.requests == 0
    assert "dangerous" in (result.error or "").lower() or result.approval_denied is True
