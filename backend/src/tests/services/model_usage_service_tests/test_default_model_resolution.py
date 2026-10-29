"""A stale stored default or stale explicit model id must never be a dead end when a usable model is enabled."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api.core.models.model_types import ModelCapability
from api.core.models.preferences import Preferences
from api.services.model_usage_service import ModelUsageService
from api.services.reasoning_model_catalog import choose_effective_reasoning_model_id

STALE_LOCAL_DEFAULT = "qwen/qwen35-9b-q4km"


def _preferences(*, use_api_models: bool = True) -> Preferences:
    preferences = Preferences()
    preferences.models.reasoning_model = STALE_LOCAL_DEFAULT
    preferences.models.use_api_models = use_api_models
    preferences.models.anthropic_enabled = True
    preferences.models.anthropic_models = {"claude-sonnet-5-5": True, "claude-opus-5-5": True}
    preferences.models.openai_enabled = False
    preferences.models.gemini_enabled = False
    return preferences


class _ModelService:
    """Mirrors the real ModelService contract: API variants are prefixed with their provider."""

    def __init__(self, failing_ids=()):
        self.loaded = []
        self._failing_ids = set(failing_ids)

    def get_installed_models(self):
        return {}

    async def load_model(self, model_type, variant, capabilities, registry_model_id=None):
        model_id = f"{model_type}-{variant}"
        self.loaded.append(model_id)
        if model_id in self._failing_ids:
            raise ValueError(f"cannot load {model_id}")
        return SimpleNamespace(model_id=model_id)

    async def load_model_by_id(self, model_id, capabilities):
        if model_id == STALE_LOCAL_DEFAULT:
            raise ValueError("local model is not installed")
        if model_id in {"claude-sonnet-5-5", "claude-opus-5-5"}:
            self.loaded.append(model_id)
            return SimpleNamespace(model_id=model_id)
        return None


async def _resolve(service, preferences, **kwargs):
    with patch("api.services.model_usage_service.Preferences.load", return_value=preferences):
        return await service.get_model_for_task({ModelCapability.REASONING}, **kwargs)


@pytest.mark.asyncio
async def test_stale_stored_default_resolves_to_the_first_enabled_api_model_without_a_double_prefix():
    model_service = _ModelService()

    model = await _resolve(ModelUsageService(model_service), _preferences())

    assert model is not None
    assert model.model_id == "claude-sonnet-5-5"
    assert not any(loaded.startswith("claude-claude-") for loaded in model_service.loaded)


@pytest.mark.asyncio
async def test_stale_explicit_model_id_falls_back_instead_of_returning_nothing():
    model_service = _ModelService()

    model = await _resolve(ModelUsageService(model_service), _preferences(), explicit_model_id=STALE_LOCAL_DEFAULT)

    assert model is not None
    assert model.model_id == "claude-sonnet-5-5"


@pytest.mark.asyncio
async def test_available_explicit_model_id_is_honored_and_never_replaced():
    model_service = _ModelService()

    model = await _resolve(ModelUsageService(model_service), _preferences(), explicit_model_id="claude-opus-5-5")

    assert model.model_id == "claude-opus-5-5"


@pytest.mark.asyncio
async def test_a_failed_first_candidate_does_not_stop_the_search():
    model_service = _ModelService(failing_ids={"claude-claude-sonnet-5-5", "claude-sonnet-5-5"})
    service = ModelUsageService(model_service)
    preferences = _preferences()

    async def load_by_id(model_id, capabilities):
        if model_id == "claude-opus-5-5":
            return SimpleNamespace(model_id=model_id)
        raise ValueError("unavailable")

    model_service.load_model_by_id = load_by_id

    model = await _resolve(service, preferences)

    assert model is not None
    assert model.model_id == "claude-opus-5-5"


@pytest.mark.asyncio
async def test_failures_are_recorded_so_callers_can_explain_them():
    model_service = _ModelService()
    model_service.load_model_by_id = AsyncMock(side_effect=ValueError("No Anthropic API key available"))
    model_service.load_model = AsyncMock(side_effect=ValueError("No Anthropic API key available"))
    service = ModelUsageService(model_service)

    model = await _resolve(service, _preferences())

    assert model is None
    assert "No Anthropic API key available" in service.describe_model_failures()


def test_effective_model_keeps_an_available_stored_choice():
    models = [{"id": "claude-sonnet-5-5", "is_api_model": True}, {"id": "claude-opus-5-5", "is_api_model": True}]

    assert choose_effective_reasoning_model_id("claude-opus-5-5", models, True) == "claude-opus-5-5"


def test_effective_model_replaces_an_unavailable_stored_choice_with_the_first_picker_entry():
    models = [{"id": "claude-sonnet-5-5", "is_api_model": True}, {"id": "claude-opus-5-5", "is_api_model": True}]

    assert choose_effective_reasoning_model_id(STALE_LOCAL_DEFAULT, models, True) == "claude-sonnet-5-5"


def test_effective_model_prefers_the_kind_the_user_selected_and_keeps_stored_when_nothing_is_available():
    mixed = [{"id": "local-a", "is_api_model": False}, {"id": "claude-sonnet-5-5", "is_api_model": True}]

    assert choose_effective_reasoning_model_id("gone", mixed, False) == "local-a"
    assert choose_effective_reasoning_model_id("gone", mixed, True) == "claude-sonnet-5-5"
    assert choose_effective_reasoning_model_id("gone", [], True) == "gone"
