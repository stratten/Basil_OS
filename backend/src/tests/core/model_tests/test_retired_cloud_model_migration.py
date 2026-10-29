"""Coverage for the removal of cloud models that OpenAI, Anthropic, Google, or OpenRouter retire."""

import json
from types import SimpleNamespace

import pytest

from api.core.models import preferences as preferences_model
from api.core.models.models_registry import (
    PROVIDER_ANTHROPIC,
    PROVIDER_GOOGLE,
    PROVIDER_OPENAI,
    get_model,
    get_validation_model_for_provider,
)
from api.core.models.preference_models.migrations import (
    RETIRED_CLOUD_MODEL_REPLACEMENTS,
    RETIRED_LOCAL_MODEL_REPLACEMENTS,
    migrate_retired_cloud_model_ids_in_data,
)
from api.core.services.api_key_validation import call_provider_with_key

RETIRING_REGISTRY_IDS = (
    "gpt-4o",
    "gpt-4o-mini",
    "gpt-4.1",
    "gpt-4.1-mini",
    "gpt-4.1-2025-04-14",
    "gpt-4.1-nano",
    "gpt-4-turbo",
    "o1",
    "o3-mini",
    "o4-mini",
    "gemini-2.5-pro",
    "gemini-2.5-flash",
    "gemini-3-flash",
    "claude-sonnet-4-5-20250929",
    "claude-sonnet-4-6",
    "claude-opus-4-5-20251101",
    "claude-opus-4-6",
    "claude-opus-4-7",
    "claude-opus-4-8",
    "claude-opus-5",
    "claude-haiku-4-5-20251001",
    "gpt-5.2",
    "gpt-5.2-pro",
    "gpt-5.5",
    "gpt-5.5-pro",
    "claude-sonnet-5",
    "claude-fable-5",
    "gemini-3.5-flash",
    "gemini-3.7-flash",
    "gemini-3.1-flash-lite",
)


@pytest.mark.parametrize("model_id", RETIRING_REGISTRY_IDS)
def test_retiring_models_are_no_longer_registry_entries(model_id):
    assert get_model(model_id) is None
    assert model_id in RETIRED_CLOUD_MODEL_REPLACEMENTS


@pytest.mark.parametrize("model_id", ("gpt-5", "gpt-5-mini", "gpt-5-nano", "gpt-5.1", "gpt-5.4-nano"))
def test_models_removed_without_a_migration_are_absent_from_the_registry(model_id):
    assert get_model(model_id) is None
    assert model_id not in RETIRED_CLOUD_MODEL_REPLACEMENTS


def test_openai_has_a_recommended_default_enabled_model():
    from api.core.models.models_registry import get_models_by_provider

    openai_models = get_models_by_provider(PROVIDER_OPENAI)
    assert any(config.get("default_enabled") and config.get("recommended") for config in openai_models.values())


@pytest.mark.parametrize("retired_id", sorted(RETIRED_CLOUD_MODEL_REPLACEMENTS))
def test_every_retired_id_is_absent_from_the_registry(retired_id):
    assert get_model(retired_id) is None


def test_replacements_stay_within_the_retired_models_provider():
    for retired_id, replacement in RETIRED_CLOUD_MODEL_REPLACEMENTS.items():
        expected_provider = (
            PROVIDER_ANTHROPIC
            if retired_id.startswith("claude")
            else PROVIDER_GOOGLE
            if retired_id.startswith("gemini")
            else PROVIDER_OPENAI
        )
        assert get_model(replacement)["provider"] == expected_provider, retired_id


def test_every_replacement_is_a_current_registry_model():
    for replacement in set(RETIRED_CLOUD_MODEL_REPLACEMENTS.values()):
        config = get_model(replacement)
        assert config is not None, replacement
        assert config.get("openrouter_id"), replacement
        assert config.get("supports_openrouter_proxy") is True, replacement


def test_no_replacement_is_itself_retired():
    assert set(RETIRED_CLOUD_MODEL_REPLACEMENTS.values()).isdisjoint(RETIRED_CLOUD_MODEL_REPLACEMENTS)


def test_ambient_evaluation_default_is_not_a_retiring_model():
    settings = preferences_model.Preferences().ambient_suggestions
    assert settings.evaluation_model == "gpt-5.4-mini"
    assert get_model(settings.evaluation_model) is not None


@pytest.mark.parametrize("provider", [PROVIDER_OPENAI, PROVIDER_GOOGLE, PROVIDER_ANTHROPIC])
def test_key_validation_still_has_a_registry_model(provider):
    validation_model = get_validation_model_for_provider(provider)
    assert validation_model is not None
    assert get_model(validation_model) is not None
    assert validation_model not in RETIRED_CLOUD_MODEL_REPLACEMENTS


def test_openai_key_validation_uses_the_responses_api(monkeypatch):
    import openai

    captured = {}

    class Responses:
        def create(self, **kwargs):
            captured.update(kwargs)

    class Client:
        def __init__(self, *, api_key):
            captured["api_key"] = api_key
            self.responses = Responses()

    monkeypatch.setattr(openai, "OpenAI", Client)

    call_provider_with_key("openai", "sk-test", "gpt-6-luna")

    assert captured == {
        "api_key": "sk-test",
        "model": "gpt-6-luna",
        "input": "Hello",
        "max_output_tokens": 16,
    }


def test_saved_background_model_preferences_move_to_replacements():
    data = {
        "models": {"reasoning_model": "claude-sonnet-4-5-20250929", "language_model": "gpt-4o"},
        "activity_capture": {"processing_model": "gpt-4o-mini"},
        "ambient_suggestions": {"evaluation_model": "gpt-4.1-mini"},
        "memory_intelligence": {"memory_processing_model": "gpt-4.1", "skill_processing_model": None},
        "zettel": {"narrative_model": "gpt-4o-mini-2024-07-18"},
    }

    changed = migrate_retired_cloud_model_ids_in_data(data)

    assert changed is True
    assert data["models"] == {"reasoning_model": "claude-sonnet-5-5", "language_model": "gpt-6-luna"}
    assert data["activity_capture"]["processing_model"] == "gpt-5.4-mini"
    assert data["ambient_suggestions"]["evaluation_model"] == "gpt-5.4-mini"
    assert data["memory_intelligence"] == {"memory_processing_model": "gpt-6-luna", "skill_processing_model": None}
    assert data["zettel"]["narrative_model"] == "gpt-5.4-mini"


@pytest.mark.parametrize(
    ("retired_id", "replacement"),
    [
        ("o1", "gpt-5.6-sol"),
        ("o3-mini", "gpt-5.6-sol"),
        ("o4-mini", "gpt-5.6-terra"),
        ("gpt-4.1-nano", "gpt-5.6-luna"),
        ("gpt-4-turbo", "gpt-5.6-sol"),
        ("gemini-2.5-pro", "gemini-3.1-pro-preview"),
        ("gemini-2.5-flash", "gemini-3.8-flash"),
        ("gemini-3-flash", "gemini-3.8-flash"),
        ("claude-sonnet-4-5-20250929", "claude-sonnet-5-5"),
        ("claude-sonnet-4-6", "claude-sonnet-5-5"),
        ("claude-opus-4-5-20251101", "claude-opus-5-5"),
        ("claude-opus-5", "claude-opus-5-5"),
        ("claude-haiku-4-5-20251001", "claude-haiku-5-5"),
        ("gpt-5.2", "gpt-5.6-terra"),
        ("gpt-5.2-pro", "gpt-5.6-sol"),
        ("gpt-5.5", "gpt-5.6-terra"),
        ("gpt-5.5-pro", "gpt-5.6-sol"),
        ("claude-sonnet-5", "claude-sonnet-5-5"),
        ("claude-fable-5", "claude-fable-5-1"),
        ("gemini-3.5-flash", "gemini-3.6-flash"),
        ("gemini-3.7-flash", "gemini-3.8-flash"),
        ("gemini-3.1-flash-lite", "gemini-3.5-flash-lite"),
    ],
)
def test_provider_published_replacements(retired_id, replacement):
    data = {"models": {"reasoning_model": retired_id, "reasoning_fallback_model_id": retired_id}}

    assert migrate_retired_cloud_model_ids_in_data(data) is True
    assert data["models"] == {"reasoning_model": replacement, "reasoning_fallback_model_id": replacement}


def test_migration_is_idempotent_and_leaves_other_models_alone():
    data = {
        "models": {"reasoning_model": "gpt-5.6-terra", "vision_model": ""},
        "activity_capture": {"processing_model": "upstage/SOLAR-10.7B-Instruct-v1.0"},
        "zettel": {"narrative_model": ""},
    }
    before = json.loads(json.dumps(data))

    assert migrate_retired_cloud_model_ids_in_data(data) is False
    assert data == before

    data["ambient_suggestions"] = {"evaluation_model": "gpt-4o-mini"}
    assert migrate_retired_cloud_model_ids_in_data(data) is True
    assert migrate_retired_cloud_model_ids_in_data(data) is False


def test_migration_tolerates_missing_or_malformed_sections():
    data = {"models": "not a dict", "zettel": None, "activity_capture": {"processing_model": 7}}
    assert migrate_retired_cloud_model_ids_in_data(data) is False
    assert migrate_retired_cloud_model_ids_in_data({}) is False


def test_loading_preferences_with_retired_models_persists_the_replacements(tmp_path, monkeypatch):
    settings_file = tmp_path / "preferences.json"
    settings_file.write_text(
        json.dumps(
            {
                "activity_capture": {"processing_model": "gpt-4o-mini"},
                "ambient_suggestions": {"evaluation_model": "gpt-4o-mini"},
                "zettel": {"narrative_model": "gpt-4o-mini"},
            }
        )
    )
    monkeypatch.setattr(preferences_model, "SETTINGS_DIR", tmp_path)
    monkeypatch.setattr(preferences_model, "SETTINGS_FILE", settings_file)

    loaded = preferences_model.Preferences.load()

    assert loaded.activity_capture.processing_model == "gpt-5.4-mini"
    assert loaded.ambient_suggestions.evaluation_model == "gpt-5.4-mini"
    assert loaded.zettel.narrative_model == "gpt-5.4-mini"
    saved = json.loads(settings_file.read_text())
    assert saved["activity_capture"]["processing_model"] == "gpt-5.4-mini"
    assert saved["ambient_suggestions"]["evaluation_model"] == "gpt-5.4-mini"
    assert saved["zettel"]["narrative_model"] == "gpt-5.4-mini"


def test_enabled_state_carries_over_to_the_replacement_model():
    data = {
        "models": {
            "anthropic_models": {"claude-opus-4-8": True, "claude-haiku-4-5-20251001": False, "claude-sonnet-5-5": False},
            "gemini_models": {"gemini-3.5-flash": True},
        }
    }

    assert migrate_retired_cloud_model_ids_in_data(data) is True
    assert data["models"]["anthropic_models"] == {"claude-opus-5-5": True, "claude-sonnet-5-5": False}
    assert data["models"]["gemini_models"] == {"gemini-3.6-flash": True}
    assert migrate_retired_cloud_model_ids_in_data(data) is False


@pytest.mark.parametrize("retired_id", sorted(RETIRED_LOCAL_MODEL_REPLACEMENTS))
def test_every_retired_local_id_is_absent_and_replaced_by_a_registry_model(retired_id):
    replacement = RETIRED_LOCAL_MODEL_REPLACEMENTS[retired_id]
    assert replacement not in RETIRED_LOCAL_MODEL_REPLACEMENTS
    # Slash-form ids are how preferences spell a local model; only the dash form is a registry key.
    if "/" in retired_id:
        assert "/" in replacement
        return
    assert get_model(retired_id) is None
    assert get_model(replacement) is not None, replacement


@pytest.mark.parametrize(
    ("retired_id", "replacement"),
    [
        ("Solar-solar", "Qwen-qwen35-9b-q4km"),
        ("solar/solar", "qwen/qwen35-9b-q4km"),
        ("Mistral-mistral-nemo", "Mistral-ministral3-8b-instruct-q4km"),
        ("Qwen-qwen25vl-3b-instruct-q4km", "Qwen-qwen3vl-4b-instruct-q4km"),
        ("Qwen-qwen25vl-7b-instruct-q4k", "Qwen-qwen3vl-8b-instruct-q4km"),
        ("Qwen-qwen25vl-32b-instruct-q4km", "Qwen-qwen3vl-32b-instruct-q4km"),
    ],
)
def test_saved_local_model_preferences_move_to_replacements(retired_id, replacement):
    data = {"models": {"reasoning_model": retired_id, "local_vision_model_id": retired_id}}

    assert migrate_retired_cloud_model_ids_in_data(data) is True
    assert data["models"] == {"reasoning_model": replacement, "local_vision_model_id": replacement}
    assert migrate_retired_cloud_model_ids_in_data(data) is False


def test_default_local_vision_model_is_a_registry_entry():
    default_id = preferences_model.Preferences().models.local_vision_model_id
    config = get_model(default_id)
    assert config is not None
    assert config["handler"] == "llama_cpp_vision"
    assert default_id not in RETIRED_LOCAL_MODEL_REPLACEMENTS
