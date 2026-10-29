"""Read-only auto-approval is the only tool-execution setting the setup assistant may change, and it is on by default."""

from unittest.mock import patch

import pytest
from pydantic import ValidationError

from api.core.models.preferences import Preferences
from api.routes.setup_assistant.models import SetupExecutionStatus, SetupToolApprovalState, SetupToolCall
from api.services.setup_assistant.action_execution_service import SetupAssistantActionExecutionService
from api.services.setup_assistant.agent_graph.setup_agent_system_prompt import build_setup_agent_system_prompt
from api.services.setup_assistant.agent_graph.setup_agent_tooling.schemas import SetupProposeConsentReceiptInput


def _call(settings: dict) -> SetupToolCall:
    return SetupToolCall(
        id="proposal-tool-execution",
        tool_name="update_basil_settings",
        payload={"settings": settings},
        approval_state=SetupToolApprovalState.approved,
        user_visible_summary="Change read-only auto-approval.",
        mutates_external_state=True,
    )


async def _execute(preferences: Preferences, settings: dict):
    saved: dict = {}
    with patch("api.core.preferences.preferences_io.load_preferences", lambda: preferences), \
         patch("api.core.preferences.preferences_io.save_preferences", lambda prefs: saved.update(preferences=prefs)):
        results = await SetupAssistantActionExecutionService().execute_approved_setup_actions(actions=[], tool_calls=[_call(settings)])
    return results, saved


def test_a_fresh_install_auto_approves_read_only_commands():
    assert Preferences().tool_execution.auto_approve_read_only is True


def test_a_persisted_false_is_not_overwritten_by_the_new_default():
    restored = Preferences.model_validate({"tool_execution": {"auto_approve_read_only": False}})

    assert restored.tool_execution.auto_approve_read_only is False


@pytest.mark.asyncio
async def test_the_executor_turns_read_only_auto_approval_off_and_reports_the_path():
    results, saved = await _execute(Preferences(), {"tool_execution": {"auto_approve_read_only": False}})

    assert results[0].status == SetupExecutionStatus.applied
    assert results[0].result_payload["updated_paths"] == ["tool_execution.auto_approve_read_only"]
    assert saved["preferences"].tool_execution.auto_approve_read_only is False


@pytest.mark.asyncio
async def test_the_executor_refuses_every_other_tool_execution_key():
    results, saved = await _execute(Preferences(), {"tool_execution": {"block_dangerous_patterns": False}})

    assert results[0].status == SetupExecutionStatus.failed
    assert "not allowed" in results[0].message
    assert "preferences" not in saved


@pytest.mark.asyncio
async def test_the_executor_refuses_a_non_boolean_value():
    results, _ = await _execute(Preferences(), {"tool_execution": {"auto_approve_read_only": "yes"}})

    assert results[0].status == SetupExecutionStatus.failed
    assert "true or false" in results[0].message


def test_proposal_time_validation_rejects_a_bad_tool_execution_receipt():
    with pytest.raises(ValidationError):
        SetupProposeConsentReceiptInput(
            title="Turn off safety",
            rationale="x",
            mutation_tool_name="update_basil_settings",
            mutation_payload={"settings": {"tool_execution": {"dangerous_patterns": []}}},
        )


def test_proposal_time_validation_accepts_the_read_only_switch():
    receipt = SetupProposeConsentReceiptInput(
        title="Run read-only scripts without asking",
        rationale="x",
        mutation_tool_name="update_basil_settings",
        mutation_payload={"settings": {"tool_execution": {"auto_approve_read_only": True}}},
    )

    assert receipt.mutation_payload["settings"]["tool_execution"] == {"auto_approve_read_only": True}


def test_the_prompt_names_the_section_and_key():
    prompt = build_setup_agent_system_prompt()

    assert "`tool_execution`" in prompt
    assert "auto_approve_read_only" in prompt
