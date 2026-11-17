"""The setup model list shows every visible model and marks the ones the person switched on in Settings."""

from types import SimpleNamespace
from unittest.mock import patch

from api.routes.setup_assistant import model_access_routes

REGISTRY = {
    "claude-a": {"provider": "anthropic", "capabilities": ["reasoning"], "display_order": 1, "recommended_for_onboarding": True},
    "claude-b": {"provider": "anthropic", "capabilities": ["reasoning"], "display_order": 2},
    "claude-hidden": {"provider": "anthropic", "capabilities": ["reasoning"], "display_order": 3, "visible": False},
    "gemini-a": {"provider": "google", "capabilities": ["reasoning"], "display_order": 1},
}


def _preferences(*, anthropic_enabled=True, anthropic_models=None, gemini_enabled=True, gemini_models=None):
    models = SimpleNamespace(
        anthropic_enabled=anthropic_enabled,
        anthropic_models=anthropic_models or {},
        openai_enabled=True,
        openai_models={},
        gemini_enabled=gemini_enabled,
        gemini_models=gemini_models or {},
    )
    return SimpleNamespace(load=lambda: SimpleNamespace(models=models))


def _choices(provider, preferences):
    with patch.object(model_access_routes, "CLOUD_REASONING_MODELS", REGISTRY), patch.object(
        model_access_routes, "Preferences", preferences
    ):
        return {choice.model_id: choice for choice in model_access_routes._provider_model_choices(provider)}


def test_every_visible_model_is_listed_and_only_the_switched_on_ones_are_marked():
    choices = _choices("anthropic", _preferences(anthropic_models={"claude-a": True, "claude-b": False}))

    assert set(choices) == {"claude-a", "claude-b"}
    assert choices["claude-a"].enabled is True
    assert choices["claude-b"].enabled is False


def test_a_person_with_nothing_switched_on_still_gets_the_full_list():
    choices = _choices("anthropic", _preferences(anthropic_models={"claude-a": False, "claude-b": False}))

    assert set(choices) == {"claude-a", "claude-b"}
    assert not any(choice.enabled for choice in choices.values())


def test_a_provider_switched_off_in_settings_marks_nothing():
    choices = _choices("anthropic", _preferences(anthropic_enabled=False, anthropic_models={"claude-a": True}))

    assert set(choices) == {"claude-a", "claude-b"}
    assert not any(choice.enabled for choice in choices.values())


def test_a_model_hidden_in_the_registry_is_not_listed_even_when_switched_on():
    choices = _choices("anthropic", _preferences(anthropic_models={"claude-hidden": True}))

    assert "claude-hidden" not in choices


def test_google_in_setup_reads_the_gemini_settings():
    choices = _choices("google", _preferences(gemini_models={"gemini-a": True}))

    assert choices["gemini-a"].enabled is True


def test_the_recommended_model_is_still_flagged_independently_of_enabled():
    choices = _choices("anthropic", _preferences(anthropic_models={"claude-b": True}))

    assert choices["claude-a"].recommended is True and choices["claude-a"].enabled is False
    assert choices["claude-b"].recommended is False and choices["claude-b"].enabled is True
