"""Tests for the reasoning-model local-fallback helpers in model_usage_service.py."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from api.services.model_usage_service import (
    ModelUsageService,
    is_model_unreachable_error,
)
from api.core.models.model_types import ModelCapability


@pytest.mark.parametrize(
    "error",
    [
        ConnectionError("Connection refused"),
        Exception("nodename nor servname provided, or not known"),
        type("AuthenticationError", (Exception,), {})("bad credentials"),
        Exception("invalid x-api-key provided"),
    ],
)
def test_is_model_unreachable_error_classifies_network_and_auth_failures(error):
    assert is_model_unreachable_error(error) is True


def test_is_model_unreachable_error_returns_false_for_unrelated_errors():
    assert is_model_unreachable_error(ValueError("bad prompt")) is False


@pytest.mark.asyncio
async def test_get_designated_local_fallback_model_returns_none_when_disabled():
    mock_model_service = MagicMock()
    mock_model_service.load_model_by_id = AsyncMock()
    service = ModelUsageService(mock_model_service)

    mock_prefs = MagicMock()
    mock_prefs.models.reasoning_fallback_enabled = False
    mock_prefs.models.reasoning_fallback_model_id = "some-local-model"

    with patch("api.services.model_usage_service.Preferences.load", return_value=mock_prefs):
        result = await service.get_designated_local_fallback_model({ModelCapability.REASONING})

    assert result is None
    mock_model_service.load_model_by_id.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_designated_local_fallback_model_returns_none_when_model_id_empty():
    mock_model_service = MagicMock()
    mock_model_service.load_model_by_id = AsyncMock()
    service = ModelUsageService(mock_model_service)

    mock_prefs = MagicMock()
    mock_prefs.models.reasoning_fallback_enabled = True
    mock_prefs.models.reasoning_fallback_model_id = ""

    with patch("api.services.model_usage_service.Preferences.load", return_value=mock_prefs):
        result = await service.get_designated_local_fallback_model({ModelCapability.REASONING})

    assert result is None
    mock_model_service.load_model_by_id.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_designated_local_fallback_model_loads_designated_model():
    mock_model_service = MagicMock()
    loaded_model = AsyncMock()
    mock_model_service.load_model_by_id = AsyncMock(return_value=loaded_model)
    service = ModelUsageService(mock_model_service)

    mock_prefs = MagicMock()
    mock_prefs.models.reasoning_fallback_enabled = True
    mock_prefs.models.reasoning_fallback_model_id = "qwen-local-7b"

    with patch("api.services.model_usage_service.Preferences.load", return_value=mock_prefs), \
         patch("api.core.models.models_registry.get_custom_models", return_value={}):
        result = await service.get_designated_local_fallback_model({ModelCapability.REASONING})

    assert result is loaded_model
    mock_model_service.load_model_by_id.assert_awaited_once()
    args, _ = mock_model_service.load_model_by_id.call_args
    assert args[0] == "qwen-local-7b"


@pytest.mark.asyncio
async def test_get_designated_local_fallback_model_returns_none_when_load_fails():
    mock_model_service = MagicMock()
    mock_model_service.load_model_by_id = AsyncMock(side_effect=RuntimeError("model missing on disk"))
    service = ModelUsageService(mock_model_service)

    mock_prefs = MagicMock()
    mock_prefs.models.reasoning_fallback_enabled = True
    mock_prefs.models.reasoning_fallback_model_id = "qwen-local-7b"

    with patch("api.services.model_usage_service.Preferences.load", return_value=mock_prefs), \
         patch("api.core.models.models_registry.get_custom_models", return_value={}):
        result = await service.get_designated_local_fallback_model({ModelCapability.REASONING})

    assert result is None
