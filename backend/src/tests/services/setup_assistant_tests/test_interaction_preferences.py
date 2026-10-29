"""Merging the setup interview's answers into the profile's custom instructions."""

from unittest.mock import AsyncMock, patch

import pytest

from api.core.knowledge.personalization_models import UserProfile
from api.routes.setup_assistant.models import SetupAction, SetupActionKind, SetupExecutionStatus
from api.services.setup_assistant.action_execution_service import SetupAssistantActionExecutionService
from api.services.setup_assistant.interaction_preferences import (
    BLOCK_END,
    BLOCK_START,
    CUSTOM_INSTRUCTIONS_MAX_LENGTH,
    merge_interaction_preferences,
)


def test_appends_a_block_after_existing_freeform_text_without_changing_it():
    merged = merge_interaction_preferences("Always sign off with Thanks.", "Keep answers short.")

    assert merged.startswith("Always sign off with Thanks.\n\n")
    assert f"{BLOCK_START}\nKeep answers short.\n{BLOCK_END}" in merged


def test_creates_the_block_when_nothing_exists():
    assert merge_interaction_preferences(None, "Use bullets.") == f"{BLOCK_START}\nUse bullets.\n{BLOCK_END}"


def test_replaces_only_its_own_block_and_keeps_text_on_both_sides():
    first = merge_interaction_preferences("Before text.", "Use prose.")
    with_after = first + "\n\nAfter text."

    merged = merge_interaction_preferences(with_after, "Use bullets.")

    assert merged.count(BLOCK_START) == 1
    assert "Use prose." not in merged
    assert "Use bullets." in merged
    assert merged.startswith("Before text.")
    assert merged.endswith("After text.")


def test_rejects_empty_text_delimiter_injection_and_oversized_results():
    with pytest.raises(ValueError):
        merge_interaction_preferences("x", "   ")
    with pytest.raises(ValueError):
        merge_interaction_preferences("x", f"sneaky {BLOCK_END} text")
    with pytest.raises(ValueError, match="too long"):
        merge_interaction_preferences("x" * (CUSTOM_INSTRUCTIONS_MAX_LENGTH - 20), "y" * 200)


@pytest.mark.asyncio
async def test_executor_saves_the_merged_block_and_keeps_every_other_profile_field():
    existing = UserProfile(full_name="Ada Lovelace", job_title="Analyst", custom_instructions="Call me Ada.")
    service = AsyncMock()
    service.get_user_profile = AsyncMock(return_value=existing)
    service.create_or_update_user_profile = AsyncMock(return_value=existing)
    action = SetupAction(
        id="a1",
        kind=SetupActionKind.save_profile,
        payload={"updates": {"interaction_preferences": "Short answers. Bullets for lists."}},
        requires_explicit_approval=True,
    )

    with patch("api.core.knowledge.personalization_service.PersonalizationService", return_value=service):
        items = await SetupAssistantActionExecutionService(
            download_manager=None, model_service=None, connection_refresher=None
        )._execute_action(action)

    assert items[0].status == SetupExecutionStatus.applied
    saved = service.create_or_update_user_profile.await_args.args[0]
    assert saved.full_name == "Ada Lovelace"
    assert saved.job_title == "Analyst"
    assert saved.custom_instructions.startswith("Call me Ada.")
    assert "Short answers. Bullets for lists." in saved.custom_instructions


@pytest.mark.asyncio
async def test_executor_rejects_unknown_profile_update_keys():
    action = SetupAction(
        id="a2",
        kind=SetupActionKind.save_profile,
        payload={"updates": {"email": "x@example.com"}},
        requires_explicit_approval=True,
    )

    with pytest.raises(ValueError, match="not allowed"):
        await SetupAssistantActionExecutionService(
            download_manager=None, model_service=None, connection_refresher=None
        )._execute_action(action)
