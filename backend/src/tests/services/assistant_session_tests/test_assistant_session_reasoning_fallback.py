"""Tests for AssistantSessionService's one-time local fallback retry when the
preferred reasoning model is completely unreachable on the first call."""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api.services.assistant_sessions.assistant_session_service import AssistantSessionService
from api.core.models.model_types import ModelCapability


@pytest.fixture
def service():
    ocr_service = MagicMock()
    transcription_service = MagicMock()
    model_usage_service = MagicMock()
    instance = AssistantSessionService(
        ocr_service=ocr_service,
        transcription_service=transcription_service,
        model_usage_service=model_usage_service,
    )
    instance.context_enhancer.enhance_suggestion_context = AsyncMock(
        return_value={
            "enhanced_prompt": "Enhanced prompt",
            "system_prompt": "System prompt",
            "context_type": "generic",
            "metadata": {},
        }
    )
    return instance


def _make_session(service: AssistantSessionService) -> str:
    session_id = "session-1"
    service.sessions[session_id] = {
        "created_at": datetime.now(),
        "ocr_result": SimpleNamespace(cleaned_text="screen text"),
        "transcription": "summarize this",
    }
    return session_id


@pytest.mark.asyncio
async def test_generate_suggestion_retries_local_fallback_on_unreachable_model(service):
    session_id = _make_session(service)

    primary_model = AsyncMock()
    service.model_usage_service.get_model_for_task = AsyncMock(return_value=primary_model)

    fallback_model = AsyncMock()
    fallback_model.model_name = "local-fallback-model"
    service.model_usage_service.get_designated_local_fallback_model = AsyncMock(
        return_value=fallback_model
    )

    call_count = {"n": 0}

    async def fake_call_model_with_prompt(model, **kwargs):
        call_count["n"] += 1
        if model is primary_model:
            raise ConnectionError("nodename nor servname provided, or not known")
        assert model is fallback_model
        return "Suggestion from local fallback model"

    with patch(
        "api.services.assistant_sessions.assistant_session_service.call_model_with_prompt",
        side_effect=fake_call_model_with_prompt,
    ):
        result = await service.generate_suggestion(session_id)

    assert result["suggestion"] == "Suggestion from local fallback model"
    assert service.sessions[session_id]["fallback_model_used"] == "local-fallback-model"
    assert call_count["n"] == 2
    service.model_usage_service.get_designated_local_fallback_model.assert_awaited_once_with(
        {ModelCapability.REASONING}
    )


@pytest.mark.asyncio
async def test_generate_suggestion_does_not_fallback_for_unrelated_errors(service):
    session_id = _make_session(service)

    primary_model = AsyncMock()
    service.model_usage_service.get_model_for_task = AsyncMock(return_value=primary_model)
    service.model_usage_service.get_designated_local_fallback_model = AsyncMock()

    async def fake_call_model_with_prompt(model, **kwargs):
        raise ValueError("bad prompt")

    with patch(
        "api.services.assistant_sessions.assistant_session_service.call_model_with_prompt",
        side_effect=fake_call_model_with_prompt,
    ):
        with pytest.raises(ValueError):
            await service.generate_suggestion(session_id)

    service.model_usage_service.get_designated_local_fallback_model.assert_not_awaited()
    assert "fallback_model_used" not in service.sessions[session_id]
