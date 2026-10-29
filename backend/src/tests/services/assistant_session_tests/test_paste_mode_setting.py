import pytest
from pydantic import ValidationError

from api.core.models.preference_models.migrations import (
    _migrate_legacy_keys_for_team_identity_rename,
    migrate_assistant_output_paste_mode_in_data,
)
from api.core.models.preference_models.model_settings import ModelSettings
from api.routes.settings_routes.models import ModelSettingsUpdate
from api.services.setup_assistant.action_execution_service import (
    MODEL_SETTINGS_ALLOWLIST,
    validate_model_settings_payload,
)

_REQUIRED_UPDATE_FIELDS = {
    "transcription_model": "t",
    "persistence_duration": 300,
    "vision_model": "",
    "language_model": "l",
    "reasoning_model": "r",
}


def test_default_mode_is_always():
    assert ModelSettings().assistant_output_paste_mode == "always"


@pytest.mark.parametrize("legacy_value, expected", [(True, "always"), (False, "never")])
def test_migrates_legacy_boolean(legacy_value, expected):
    data = {"models": {"auto_paste_assistant_output": legacy_value}}
    migrate_assistant_output_paste_mode_in_data(data)
    assert data["models"] == {"assistant_output_paste_mode": expected}
    assert ModelSettings.model_validate(data["models"]).assistant_output_paste_mode == expected


def test_migration_keeps_existing_mode_and_drops_legacy_key():
    data = {"models": {"auto_paste_assistant_output": False, "assistant_output_paste_mode": "auto"}}
    migrate_assistant_output_paste_mode_in_data(data)
    assert data["models"] == {"assistant_output_paste_mode": "auto"}


def test_migration_is_idempotent_and_ignores_missing_sections():
    data = {"models": {"assistant_output_paste_mode": "never"}}
    migrate_assistant_output_paste_mode_in_data(data)
    migrate_assistant_output_paste_mode_in_data(data)
    assert data["models"] == {"assistant_output_paste_mode": "never"}
    empty = {}
    migrate_assistant_output_paste_mode_in_data(empty)
    assert empty == {}
    malformed = {"models": "not-a-dict"}
    migrate_assistant_output_paste_mode_in_data(malformed)
    assert malformed == {"models": "not-a-dict"}


def test_oldest_legacy_key_chains_through_both_migrations():
    data = {"models": {"auto_paste_suggestion": False}}
    _migrate_legacy_keys_for_team_identity_rename(data)
    migrate_assistant_output_paste_mode_in_data(data)
    assert data["models"] == {"assistant_output_paste_mode": "never"}


def test_update_payload_leaves_mode_unset_when_omitted():
    update = ModelSettingsUpdate(**_REQUIRED_UPDATE_FIELDS)
    assert update.assistant_output_paste_mode is None


def test_update_payload_rejects_unknown_mode():
    with pytest.raises(ValidationError):
        ModelSettingsUpdate(**_REQUIRED_UPDATE_FIELDS, assistant_output_paste_mode="sometimes")


def test_setup_assistant_allows_and_validates_mode():
    assert "assistant_output_paste_mode" in MODEL_SETTINGS_ALLOWLIST
    assert "auto_paste_assistant_output" not in MODEL_SETTINGS_ALLOWLIST
    validate_model_settings_payload({"assistant_output_paste_mode": "auto"})
    validate_model_settings_payload({"use_region_selection": True})
    with pytest.raises(ValueError):
        validate_model_settings_payload({"assistant_output_paste_mode": True})
