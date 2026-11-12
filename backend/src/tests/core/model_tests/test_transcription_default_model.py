"""The default transcription model must be one the first-run download installs and the Settings picker can list."""

import pytest

from api.core.models.models_registry import get_cloud_transcription_models, get_transcription_models
from api.core.models.preference_models.defaults import (
    LEGACY_BASE_TRANSCRIPTION_MODEL_NAME,
    STARTER_TRANSCRIPTION_MODEL_REGISTRY_ID,
    _get_default_transcription_model_name,
)
from api.core.models.preference_models.migrations import migrate_legacy_transcription_model_in_data
from api.core.models.preference_models.model_settings import ModelSettings
from api.core.models.preference_models.transcription import TranscriptionSettings
from api.routes.onboarding import _TRANSCRIPTION_STARTER_MODELS
from api.services.transcription.local_model import model_lifecycle
from api.services.transcription.local_model.whisper_source_resolver import resolve_whisper_source


def _install_whisper_base(models_dir) -> None:
    base_dir = models_dir / "whisper-base"
    base_dir.mkdir(parents=True)
    (base_dir / "config.json").write_text("{}")


@pytest.fixture
def models_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("api.settings.get_models_dir", lambda: tmp_path)
    return tmp_path


def test_the_default_is_the_display_name_of_a_starter_pack_model() -> None:
    default_name = ModelSettings().transcription_model

    starter_ids = {f"{entry['model_type']}-{entry['variant']}" for entry in _TRANSCRIPTION_STARTER_MODELS}
    assert STARTER_TRANSCRIPTION_MODEL_REGISTRY_ID in starter_ids
    assert default_name == get_transcription_models()[STARTER_TRANSCRIPTION_MODEL_REGISTRY_ID]["display_name"]
    assert default_name == _get_default_transcription_model_name()


def test_the_default_resolves_in_the_local_loader_without_falling_back() -> None:
    source = resolve_whisper_source(ModelSettings().transcription_model)

    assert source.local_dir.name == "whisper-tiny.en"


def test_the_default_is_not_a_cloud_model() -> None:
    assert ModelSettings().transcription_model not in get_cloud_transcription_models()


def test_legacy_base_becomes_the_starter_model_when_whisper_base_is_not_installed(models_dir) -> None:
    data = {"models": {"transcription_model": "base"}}

    assert migrate_legacy_transcription_model_in_data(data) is True

    assert data["models"]["transcription_model"] == _get_default_transcription_model_name()


def test_legacy_base_keeps_whisper_base_when_it_is_installed(models_dir) -> None:
    _install_whisper_base(models_dir)
    data = {"models": {"transcription_model": "base"}}

    assert migrate_legacy_transcription_model_in_data(data) is True

    assert data["models"]["transcription_model"] == LEGACY_BASE_TRANSCRIPTION_MODEL_NAME


def test_an_empty_saved_value_is_replaced(models_dir) -> None:
    data = {"models": {"transcription_model": "  "}}

    assert migrate_legacy_transcription_model_in_data(data) is True

    assert data["models"]["transcription_model"] == _get_default_transcription_model_name()


@pytest.mark.parametrize(
    "saved",
    ["Whisper Base", "Whisper Large V3 Turbo", "OpenAI-whisper", "Parakeet TDT 0.6B v3", "gpt-4o-transcribe"],
)
def test_a_real_selection_is_never_rewritten(models_dir, saved) -> None:
    data = {"models": {"transcription_model": saved}}

    assert migrate_legacy_transcription_model_in_data(data) is False

    assert data["models"]["transcription_model"] == saved


@pytest.mark.parametrize("data", [{}, {"models": None}, {"models": {}}, {"models": {"transcription_model": 7}}])
def test_missing_or_malformed_sections_are_left_alone(models_dir, data) -> None:
    assert migrate_legacy_transcription_model_in_data(data) is False


def test_the_migration_is_idempotent(models_dir) -> None:
    data = {"models": {"transcription_model": "base"}}

    assert migrate_legacy_transcription_model_in_data(data) is True
    assert migrate_legacy_transcription_model_in_data(data) is False


def test_the_loader_falls_back_to_the_default_for_a_stale_unregistered_name() -> None:
    source = model_lifecycle.ModelManager._resolve_source_or_default("base")

    assert source.display_name == model_lifecycle._DEFAULT_MODEL_DISPLAY_NAME


def test_the_loader_still_resolves_a_registered_name() -> None:
    source = model_lifecycle.ModelManager._resolve_source_or_default("Whisper Tiny (English)")

    assert source.local_dir.name == "whisper-tiny.en"


def test_the_transcription_settings_choice_defaults_to_the_starter_model_not_the_removed_base() -> None:
    assert TranscriptionSettings().selected_model == _get_default_transcription_model_name()
    assert TranscriptionSettings().selected_model != LEGACY_BASE_TRANSCRIPTION_MODEL_NAME


def test_a_stale_base_in_the_transcription_settings_choice_is_replaced_too(models_dir) -> None:
    data = {"models": {"transcription_model": "Whisper Large V3 Turbo"}, "transcription": {"selected_model": "base"}}

    assert migrate_legacy_transcription_model_in_data(data) is True

    assert data["transcription"]["selected_model"] == _get_default_transcription_model_name()
    assert data["models"]["transcription_model"] == "Whisper Large V3 Turbo"


def test_both_stale_fields_get_the_same_replacement(models_dir) -> None:
    _install_whisper_base(models_dir)
    data = {"models": {"transcription_model": "base"}, "transcription": {"selected_model": "base"}}

    assert migrate_legacy_transcription_model_in_data(data) is True

    assert data["models"]["transcription_model"] == LEGACY_BASE_TRANSCRIPTION_MODEL_NAME
    assert data["transcription"]["selected_model"] == LEGACY_BASE_TRANSCRIPTION_MODEL_NAME


def test_a_real_transcription_settings_choice_is_never_rewritten(models_dir) -> None:
    data = {"transcription": {"selected_model": "Whisper Large V3 Turbo"}}

    assert migrate_legacy_transcription_model_in_data(data) is False
    assert data["transcription"]["selected_model"] == "Whisper Large V3 Turbo"
