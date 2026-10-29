"""Cloud transcription models share the OpenAI provider but must never live in the reasoning model preferences."""

import json

from api.core.models import preferences as preferences_model
from api.core.models.models_registry import (
    PROVIDER_ANTHROPIC,
    PROVIDER_GOOGLE,
    PROVIDER_OPENAI,
    get_cloud_transcription_models,
    get_default_enabled_for_provider,
)


def test_provider_defaults_contain_only_reasoning_models():
    transcription_ids = set(get_cloud_transcription_models())
    assert transcription_ids

    openai_defaults = get_default_enabled_for_provider(PROVIDER_OPENAI)

    assert openai_defaults
    assert transcription_ids.isdisjoint(openai_defaults)
    assert get_default_enabled_for_provider(PROVIDER_ANTHROPIC)
    assert get_default_enabled_for_provider(PROVIDER_GOOGLE)


def test_loading_preferences_removes_stale_transcription_entries_and_keeps_the_rest(tmp_path, monkeypatch):
    settings_file = tmp_path / "preferences.json"
    stale_ids = sorted(get_cloud_transcription_models())
    openai_models = {"gpt-5.6-terra": True, "gpt-5.6-luna": False}
    openai_models.update({model_id: True for model_id in stale_ids})
    settings_file.write_text(json.dumps({"models": {"openai_models": openai_models}}))
    monkeypatch.setattr(preferences_model, "SETTINGS_DIR", tmp_path)
    monkeypatch.setattr(preferences_model, "SETTINGS_FILE", settings_file)

    loaded = preferences_model.Preferences.load()

    assert set(stale_ids).isdisjoint(loaded.models.openai_models)
    assert loaded.models.openai_models["gpt-5.6-terra"] is True
    assert loaded.models.openai_models["gpt-5.6-luna"] is False
    saved = json.loads(settings_file.read_text())
    assert set(stale_ids).isdisjoint(saved["models"]["openai_models"])
    assert set(stale_ids) <= set(saved["models"]["openai_transcription_models"])


def test_loading_preferences_leaves_the_transcription_selection_untouched(tmp_path, monkeypatch):
    settings_file = tmp_path / "preferences.json"
    stale_ids = sorted(get_cloud_transcription_models())
    settings_file.write_text(json.dumps({
        "models": {
            "openai_models": {model_id: True for model_id in stale_ids},
            "openai_transcription_models": {"openai-whisper-1": False, "openai-gpt-4o-transcribe": True},
        }
    }))
    monkeypatch.setattr(preferences_model, "SETTINGS_DIR", tmp_path)
    monkeypatch.setattr(preferences_model, "SETTINGS_FILE", settings_file)

    loaded = preferences_model.Preferences.load()

    assert loaded.models.openai_transcription_models["openai-whisper-1"] is False
    assert loaded.models.openai_transcription_models["openai-gpt-4o-transcribe"] is True
