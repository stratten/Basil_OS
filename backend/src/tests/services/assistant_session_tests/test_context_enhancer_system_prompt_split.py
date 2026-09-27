from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from api.services.assistant_sessions.context_enhancers.assistant_session_context_enhancer import (
    AssistantSessionContextEnhancer,
)


@pytest.fixture
def enhancer():
    instance = AssistantSessionContextEnhancer()
    instance.personalization_service = None  # force the generic-enhancement path
    return instance


@pytest.mark.asyncio
async def test_generic_enhancement_separates_system_prompt_from_user_prompt(enhancer):
    result = await enhancer.enhance_suggestion_context(
        content="some screen text", instruction="summarize this"
    )
    assert "You are Basil" in result["system_prompt"]
    assert "ABSOLUTE RULES" in result["system_prompt"]
    assert "You are Basil" not in result["enhanced_prompt"]


@pytest.mark.asyncio
async def test_custom_instructions_are_appended_to_system_prompt_not_user_prompt(enhancer):
    fake_profile = SimpleNamespace(custom_instructions="Do not use em dashes.")
    enhancer._get_personalization_context = AsyncMock(
        return_value={"profile": fake_profile, "style": None, "writing_samples": [], "contact": None, "signature": None}
    )
    result = await enhancer.enhance_suggestion_context(content="plain text", instruction="rewrite this")
    assert "Do not use em dashes." in result["system_prompt"]
    assert "USER'S STANDING COMMUNICATION INSTRUCTIONS" in result["system_prompt"]
    assert "Do not use em dashes." not in result["enhanced_prompt"]


@pytest.mark.asyncio
async def test_no_custom_instructions_omits_the_standing_instructions_section(enhancer):
    fake_profile = SimpleNamespace(custom_instructions="   ")
    enhancer._get_personalization_context = AsyncMock(
        return_value={"profile": fake_profile, "style": None, "writing_samples": [], "contact": None, "signature": None}
    )
    result = await enhancer.enhance_suggestion_context(content="plain text", instruction="rewrite this")
    assert "STANDING COMMUNICATION INSTRUCTIONS" not in result["system_prompt"]


@pytest.mark.asyncio
async def test_selected_text_suggestions_include_custom_instructions(enhancer):
    fake_profile = SimpleNamespace(custom_instructions="Use sentence case.")
    enhancer._get_personalization_context = AsyncMock(
        return_value={"profile": fake_profile, "style": None, "writing_samples": [], "contact": None, "signature": None}
    )
    result = await enhancer.enhance_suggestion_context(
        content="plain text",
        instruction="rewrite this",
        text_selection={"has_selection": True, "selected_text": "selected copy"},
    )
    assert "Use sentence case." in result["system_prompt"]
    assert "Use sentence case." not in result["enhanced_prompt"]
