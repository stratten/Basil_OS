"""The per-task auto-approve switch in the approval service: what it approves, and what it never does."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from api.core.models.preferences import ExecutionApprovalMode, ToolExecutionSettings
from api.services.agent_processing.shared.agent_runtime_context import (
    reset_current_agent_context,
    set_current_agent_context,
)
from api.services.agent_processing.tools.safety.execution_approval_service import ExecutionApprovalService
from api.services.agent_processing.tools.safety.task_auto_approve import (
    clear_all_task_auto_approve,
    set_task_auto_approve,
)

UNKNOWN_COMMAND = "touch notes.txt"
BLOCKED_COMMAND = "sudo rm -rf /"


@pytest.fixture(autouse=True)
def _clean_switches():
    clear_all_task_auto_approve()
    yield
    clear_all_task_auto_approve()


@pytest.fixture
def use_settings(monkeypatch):
    def apply(**overrides):
        values = dict(
            approval_mode=ExecutionApprovalMode.WHITELIST_ONLY,
            whitelisted_commands=[],
            auto_approve_read_only=False,
            safe_execution_mode=False,
        )
        values.update(overrides)
        stub = SimpleNamespace(tool_execution=ToolExecutionSettings(**values))
        monkeypatch.setattr(
            "api.services.agent_processing.tools.safety.approval_override.load_preferences",
            lambda: stub,
        )

    apply()
    return apply


async def _evaluate(command, context):
    return await ExecutionApprovalService().evaluate_command(command, context)


def _shell_context(**extra):
    return {"source": "shell_service", "agent_task_id": "turn-2", "root_task_id": "root-1", **extra}


@pytest.mark.asyncio
async def test_a_command_asks_while_the_switch_is_off(use_settings):
    decision = await _evaluate(UNKNOWN_COMMAND, _shell_context())

    assert decision.needs_approval is True


@pytest.mark.asyncio
async def test_a_command_runs_unasked_while_the_switch_is_on_for_its_task(use_settings):
    set_task_auto_approve("root-1", True)

    decision = await _evaluate(UNKNOWN_COMMAND, _shell_context())

    assert decision.needs_approval is False
    assert decision.is_blocked is False
    assert decision.reason == "Auto-approve is on for this task"


@pytest.mark.asyncio
async def test_the_switch_is_per_task(use_settings):
    set_task_auto_approve("root-1", True)

    other = await _evaluate(UNKNOWN_COMMAND, _shell_context(root_task_id="root-2", agent_task_id="turn-9"))

    assert other.needs_approval is True


@pytest.mark.asyncio
async def test_a_follow_up_turn_shares_its_chains_switch(use_settings):
    set_task_auto_approve("root-1", True)

    follow_up = await _evaluate(UNKNOWN_COMMAND, _shell_context(agent_task_id="turn-7"))

    assert follow_up.needs_approval is False


@pytest.mark.asyncio
async def test_the_root_comes_from_the_running_agent_when_the_caller_does_not_name_it(use_settings):
    set_task_auto_approve("root-1", True)
    token = set_current_agent_context({"agent_task_id": "turn-2", "root_task_id": "root-1"})
    try:
        decision = await _evaluate(UNKNOWN_COMMAND, {"source": "shell_service"})
    finally:
        reset_current_agent_context(token)

    assert decision.needs_approval is False


@pytest.mark.asyncio
async def test_a_single_turn_task_is_its_own_root(use_settings):
    set_task_auto_approve("solo-1", True)

    decision = await _evaluate(UNKNOWN_COMMAND, {"source": "shell_service", "agent_task_id": "solo-1"})

    assert decision.needs_approval is False


@pytest.mark.asyncio
async def test_a_command_with_no_task_at_all_still_asks(use_settings):
    set_task_auto_approve("root-1", True)

    decision = await _evaluate(UNKNOWN_COMMAND, {"source": "shell_service"})

    assert decision.needs_approval is True


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", [ExecutionApprovalMode.ALWAYS_PROMPT, ExecutionApprovalMode.WHITELIST_ONLY])
async def test_the_switch_overrides_always_prompt_and_whitelist_only(use_settings, mode):
    use_settings(approval_mode=mode)
    set_task_auto_approve("root-1", True)

    decision = await _evaluate(UNKNOWN_COMMAND, _shell_context())

    assert decision.needs_approval is False


@pytest.mark.asyncio
async def test_the_switch_overrides_safe_execution_mode(use_settings):
    use_settings(safe_execution_mode=True)
    set_task_auto_approve("root-1", True)

    decision = await _evaluate(UNKNOWN_COMMAND, _shell_context())

    assert decision.needs_approval is False


@pytest.mark.asyncio
async def test_a_dangerous_command_stays_blocked_with_the_switch_on(use_settings):
    set_task_auto_approve("root-1", True)

    decision = await _evaluate(BLOCKED_COMMAND, _shell_context())

    assert decision.is_blocked is True
    assert decision.needs_approval is False


@pytest.mark.asyncio
async def test_a_dangerous_command_stays_blocked_in_safe_execution_mode_with_the_switch_on(use_settings):
    use_settings(safe_execution_mode=True)
    set_task_auto_approve("root-1", True)

    decision = await _evaluate(BLOCKED_COMMAND, _shell_context())

    assert decision.is_blocked is True


@pytest.mark.asyncio
async def test_turning_off_the_blocking_setting_is_the_users_own_choice_and_is_respected(use_settings):
    use_settings(block_dangerous_patterns=False)
    set_task_auto_approve("root-1", True)

    decision = await _evaluate(BLOCKED_COMMAND, _shell_context())

    assert decision.is_blocked is False
    assert decision.needs_approval is False


@pytest.mark.asyncio
async def test_a_trust_granting_action_still_asks_with_the_switch_on(use_settings):
    set_task_auto_approve("root-1", True)

    decision = await _evaluate(UNKNOWN_COMMAND, _shell_context(require_explicit_approval=True))

    assert decision.needs_approval is True
    assert decision.reason == "This action always needs the user's explicit approval"


@pytest.mark.asyncio
async def test_a_connected_tool_keeps_its_own_ask_policy_with_the_switch_on(use_settings):
    set_task_auto_approve("root-1", True)

    decision = await _evaluate("mcp:slack.post_message(channel='general')", _shell_context())

    assert decision.needs_approval is True


@pytest.mark.asyncio
async def test_an_applescript_is_covered_by_the_switch(use_settings):
    set_task_auto_approve("root-1", True)

    decision = await _evaluate("AppleScript: tell application \"Finder\" to activate", _shell_context(execution_type="applescript"))

    assert decision.needs_approval is False


@pytest.mark.asyncio
async def test_a_command_that_touches_the_protected_runtime_is_refused_with_the_switch_on(use_settings, monkeypatch):
    monkeypatch.setattr(
        "api.services.agent_processing.tools.safety.execution_approval_service.references_protected_runtime_path",
        lambda command: True,
    )
    set_task_auto_approve("root-1", True)

    decision = await _evaluate(UNKNOWN_COMMAND, _shell_context())

    assert decision.is_blocked is True


def test_the_exclusions_are_exposed_for_the_waiting_card_check():
    service = ExecutionApprovalService
    assert service.task_auto_approve_may_apply(UNKNOWN_COMMAND, {}) is True
    assert service.task_auto_approve_may_apply(UNKNOWN_COMMAND, {"require_explicit_approval": True}) is False
    assert service.task_auto_approve_may_apply("mcp:slack.post_message()", {}) is False
    assert service.task_auto_approve_may_apply(UNKNOWN_COMMAND, None) is True
