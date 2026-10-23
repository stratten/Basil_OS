"""Coverage for the approved Setup Assistant appearance (ui) settings action."""

from unittest.mock import patch

import pytest

from api.core.models.preferences import Preferences
from api.routes.setup_assistant.models import SetupExecutionStatus, SetupToolApprovalState, SetupToolCall
from api.services.setup_assistant.action_execution_service import SetupAssistantActionExecutionService
from api.services.setup_assistant.agent_graph.setup_agent_system_prompt import build_setup_agent_system_prompt


def approved_appearance_proposal(ui_updates: dict) -> SetupToolCall:
    return SetupToolCall(
        id="proposal-appearance",
        tool_name="update_basil_settings",
        payload={"settings": {"ui": ui_updates}},
        approval_state=SetupToolApprovalState.approved,
        user_visible_summary="Update appearance colors.",
        mutates_external_state=True,
    )


async def execute_with_preferences(preferences: Preferences, ui_updates: dict):
    saved: dict = {}

    with patch("api.core.preferences.preferences_io.load_preferences", lambda: preferences), \
         patch("api.core.preferences.preferences_io.save_preferences", lambda prefs: saved.update(preferences=prefs)):
        service = SetupAssistantActionExecutionService()
        results = await service.execute_approved_setup_actions(
            actions=[], tool_calls=[approved_appearance_proposal(ui_updates)],
        )
    return results, saved


@pytest.mark.asyncio
async def test_approved_appearance_proposal_applies_partial_ui_update() -> None:
    results, saved = await execute_with_preferences(
        Preferences(), {"background_color_red": 0.2, "background_color_green": 0.2, "background_color_blue": 0.2},
    )

    assert results[0].status == SetupExecutionStatus.applied
    assert "ui.background_color_red" in results[0].result_payload["updated_paths"]
    changes = {c["path"]: c for c in results[0].result_payload["ui_changes"]}
    assert changes["ui.background_color_red"] == {"path": "ui.background_color_red", "old_value": 0.0709251779736389, "new_value": 0.2}
    appearance = results[0].result_payload["appearance_settings"]
    assert appearance["background_color_red"] == 0.2
    assert set(appearance) == {
        "background_color_red", "background_color_green", "background_color_blue",
        "primary_color_red", "primary_color_green", "primary_color_blue",
        "secondary_color_red", "secondary_color_green", "secondary_color_blue",
        "text_color_red", "text_color_green", "text_color_blue",
        "processing_color_red", "processing_color_green", "processing_color_blue",
        "processing_accent_color_red", "processing_accent_color_green", "processing_accent_color_blue",
        "preferred_font",
    }
    assert saved["preferences"].ui.background_color_red == 0.2
    assert saved["preferences"].ui.primary_color_red == Preferences().ui.primary_color_red


@pytest.mark.asyncio
async def test_appearance_proposal_rejects_out_of_range_rgb() -> None:
    results, saved = await execute_with_preferences(Preferences(), {"text_color_red": 1.5})

    assert results[0].status == SetupExecutionStatus.failed
    assert "must be a number from 0.0 through 1.0" in results[0].message
    assert "preferences" not in saved


@pytest.mark.asyncio
async def test_appearance_proposal_rejects_unknown_ui_key() -> None:
    results, saved = await execute_with_preferences(Preferences(), {"border_color_red": 0.5})

    assert results[0].status == SetupExecutionStatus.failed
    assert "is not allowed during setup" in results[0].message
    assert "preferences" not in saved


@pytest.mark.asyncio
async def test_appearance_proposal_rejects_font_outside_catalog() -> None:
    results, saved = await execute_with_preferences(Preferences(), {"preferred_font": "Comic Sans"})

    assert results[0].status == SetupExecutionStatus.failed
    assert "must be one of" in results[0].message
    assert "preferences" not in saved


@pytest.mark.asyncio
async def test_appearance_proposal_accepts_font_in_catalog() -> None:
    results, saved = await execute_with_preferences(Preferences(), {"preferred_font": "Menlo"})

    assert results[0].status == SetupExecutionStatus.applied
    assert saved["preferences"].ui.preferred_font == "Menlo"


@pytest.mark.asyncio
async def test_appearance_proposal_warns_on_low_contrast() -> None:
    preferences = Preferences()
    preferences.ui.text_color_red = preferences.ui.text_color_green = preferences.ui.text_color_blue = 0.5
    results, _ = await execute_with_preferences(
        preferences, {"background_color_red": 1.0, "background_color_green": 1.0, "background_color_blue": 1.0},
    )

    assert "contrast_warning" in results[0].result_payload
    assert "Note:" in results[0].message


@pytest.mark.asyncio
async def test_appearance_proposal_no_warning_when_contrast_sufficient() -> None:
    preferences = Preferences()
    preferences.ui.text_color_red = preferences.ui.text_color_green = preferences.ui.text_color_blue = 0.0
    results, _ = await execute_with_preferences(
        preferences, {"background_color_red": 1.0, "background_color_green": 1.0, "background_color_blue": 1.0},
    )

    assert "contrast_warning" not in results[0].result_payload
    assert "Note:" not in results[0].message


@pytest.mark.asyncio
async def test_duplicate_appearance_approval_is_idempotent() -> None:
    once, twice = Preferences(), Preferences()
    _, once_saved = await execute_with_preferences(once, {"background_color_red": 0.3})
    await execute_with_preferences(twice, {"background_color_red": 0.3})
    twice_results, twice_saved = await execute_with_preferences(twice, {"background_color_red": 0.3})

    assert twice_results[0].status == SetupExecutionStatus.applied
    assert once_saved["preferences"].ui.background_color_red == twice_saved["preferences"].ui.background_color_red == 0.3


def test_setup_agent_prompt_includes_appearance_guidance() -> None:
    prompt = build_setup_agent_system_prompt()

    assert "ui.background_color_red" in prompt
    assert "ui.preferred_font" in prompt
    assert "Helvetica-Light" in prompt
    assert "Automatic" in prompt
