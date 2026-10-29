"""Coverage for approved Setup Assistant `activity_capture` settings changes and the settings tool name."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError

from api.core.models.preferences import Preferences
from api.routes.setup_assistant.models import SetupExecutionStatus, SetupToolApprovalState, SetupToolCall
from api.services.setup_assistant.action_execution_service import SetupAssistantActionExecutionService
from api.services.setup_assistant.agent_graph.setup_agent_system_prompt import build_setup_agent_system_prompt
from api.services.setup_assistant.agent_graph.setup_agent_tooling.schemas import SetupProposeConsentReceiptInput


def approved_settings_proposal(settings: dict) -> SetupToolCall:
    return SetupToolCall(
        id="proposal-activity-capture",
        tool_name="update_basil_settings",
        payload={"settings": settings},
        approval_state=SetupToolApprovalState.approved,
        user_visible_summary="Turn on activity capture.",
        mutates_external_state=True,
    )


async def execute_with_preferences(preferences: Preferences, settings: dict, scheduler=None):
    saved: dict = {}
    scheduler_module = "api.services.capture.automatic.activity_capture_runtime.get_activity_capture_scheduler"

    with patch("api.core.preferences.preferences_io.load_preferences", lambda: preferences), \
         patch("api.core.preferences.preferences_io.save_preferences", lambda prefs: saved.update(preferences=prefs)), \
         patch(scheduler_module, lambda: scheduler):
        service = SetupAssistantActionExecutionService()
        results = await service.execute_approved_setup_actions(
            actions=[], tool_calls=[approved_settings_proposal(settings)],
        )
    return results, saved


@pytest.mark.asyncio
async def test_enabling_activity_capture_persists_and_explains_that_capture_has_not_started() -> None:
    results, saved = await execute_with_preferences(
        Preferences(), {"activity_capture": {"enabled": True, "start_at_startup": True, "frequency_minutes": 10}},
    )

    assert results[0].status == SetupExecutionStatus.applied
    assert results[0].result_payload["updated_paths"] == [
        "activity_capture.enabled", "activity_capture.start_at_startup", "activity_capture.frequency_minutes",
    ]
    assert "Activity Capture item now appears in the Basil menu" in results[0].message
    assert "next time Basil launches" in results[0].message
    capture = saved["preferences"].activity_capture
    assert capture.enabled is True
    assert capture.start_at_startup is True
    assert capture.frequency_minutes == 10


@pytest.mark.asyncio
async def test_approved_activity_capture_change_tells_clients_to_refresh_their_menu() -> None:
    with patch(
        "api.services.activity_capture_broadcast.broadcast_json_text", new_callable=AsyncMock
    ) as send:
        await execute_with_preferences(Preferences(), {"activity_capture": {"enabled": True}})

    send.assert_awaited_once_with({"event_type": "activity_capture_updated"})


@pytest.mark.asyncio
async def test_failed_activity_capture_change_does_not_broadcast() -> None:
    with patch(
        "api.services.activity_capture_broadcast.broadcast_json_text", new_callable=AsyncMock
    ) as send:
        await execute_with_preferences(Preferences(), {"activity_capture": {"frequency_minutes": 0.1}})

    send.assert_not_awaited()


@pytest.mark.asyncio
async def test_disabling_activity_capture_stops_the_running_scheduler() -> None:
    scheduler = SimpleNamespace(stop_activity_capture=AsyncMock(), configure_activity_capture_frequency=AsyncMock())
    preferences = Preferences()
    preferences.activity_capture.enabled = True

    results, saved = await execute_with_preferences(preferences, {"activity_capture": {"enabled": False}}, scheduler)

    assert results[0].status == SetupExecutionStatus.applied
    assert "Any running capture was stopped" in results[0].message
    assert saved["preferences"].activity_capture.enabled is False
    scheduler.stop_activity_capture.assert_awaited_once()


@pytest.mark.asyncio
async def test_activity_capture_can_be_combined_with_another_settings_section() -> None:
    results, saved = await execute_with_preferences(
        Preferences(),
        {"behavior": {"enable_voice_listener_at_startup": True}, "activity_capture": {"enabled": True}},
    )

    assert results[0].status == SetupExecutionStatus.applied
    assert results[0].result_payload["updated_paths"] == [
        "behavior.enable_voice_listener_at_startup", "activity_capture.enabled",
    ]
    assert saved["preferences"].behavior.enable_voice_listener_at_startup is True
    assert saved["preferences"].activity_capture.enabled is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "updates",
    [
        {"unknown_key": True},
        {"frequency_minutes": 0.1},
        {"frequency_minutes": 5000},
        {"processing_mode": "continuous"},
        {"scheduled_processing_time": "25:99"},
        {"enabled": "yes"},
        {},
    ],
)
async def test_invalid_activity_capture_updates_fail_without_saving(updates: dict) -> None:
    results, saved = await execute_with_preferences(Preferences(), {"activity_capture": updates})

    assert results[0].status == SetupExecutionStatus.failed
    assert "preferences" not in saved


@pytest.mark.parametrize("updates", [{"unknown_key": True}, {"frequency_minutes": 0}, {"processing_mode": "x"}])
def test_proposal_time_validation_rejects_bad_activity_capture_payloads(updates: dict) -> None:
    with pytest.raises(ValidationError):
        SetupProposeConsentReceiptInput(
            title="Turn on activity capture",
            rationale="You asked for it.",
            mutation_tool_name="update_basil_settings",
            mutation_payload={"settings": {"activity_capture": updates}},
        )


def test_proposal_time_validation_accepts_a_valid_activity_capture_payload() -> None:
    proposal = SetupProposeConsentReceiptInput(
        title="Turn on activity capture",
        rationale="You asked for it.",
        mutation_tool_name="update_basil_settings",
        mutation_payload={"settings": {"activity_capture": {"enabled": True, "start_at_startup": True}}},
    )

    assert proposal.mutation_payload["settings"]["activity_capture"]["enabled"] is True


def test_every_mutation_tool_named_in_the_system_prompt_exists_in_the_setup_catalog() -> None:
    import re

    from api.services.setup_assistant.context_catalog_service import SetupAssistantContextCatalogService

    prompt = build_setup_agent_system_prompt()
    catalog_names = {tool.name for tool in SetupAssistantContextCatalogService().build_available_tools()}

    named_in_prompt = set(re.findall(r'mutation_tool_name="([a-z_]+)"', prompt))
    assert named_in_prompt, "the prompt should name at least one mutation tool"
    assert named_in_prompt <= catalog_names, sorted(named_in_prompt - catalog_names)
    assert "update_settings" not in prompt.replace("there is no `update_settings` tool", "")


def test_tool_name_rejection_lists_the_valid_names_so_the_agent_can_recover() -> None:
    from api.services.setup_assistant.agent_graph.setup_agent_tooling.proposal_tools import validate_setup_tool_name
    from api.services.setup_assistant.context_catalog_service import SetupAssistantContextCatalogService

    factory = SimpleNamespace(context_catalog_service=SetupAssistantContextCatalogService())

    with pytest.raises(ValueError) as error:
        validate_setup_tool_name(factory, "update_settings")

    assert "not available for approval" in str(error.value)
    assert "'update_basil_settings'" in str(error.value)
    assert "'start_model_downloads'" in str(error.value)
    validate_setup_tool_name(factory, "update_basil_settings")


def test_system_prompt_names_the_real_settings_tool_and_the_activity_capture_keys() -> None:
    prompt = build_setup_agent_system_prompt()

    assert 'mutation_tool_name="update_basil_settings"' in prompt
    assert "use `update_settings` for" not in prompt
    for key in ("enabled", "start_at_startup", "frequency_minutes", "processing_mode", "scheduled_processing_time"):
        assert f"`{key}`" in prompt
