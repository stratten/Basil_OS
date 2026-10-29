"""Migration coverage for newly introduced default zettel source kinds."""

import json

from api.core.models import preferences as preferences_model
from api.core.models.preference_models.execution_and_connections import (
    ZETTEL_SOURCE_CATALOG_VERSION,
    ZETTEL_SOURCE_KINDS,
)
from api.core.models.preference_models.migrations import (
    migrate_zettel_source_catalog_in_data,
)


def test_legacy_catalog_enables_only_the_new_meeting_source():
    data = {
        "zettel": {
            "enabled_sources": ["agent_task", "screen_block"],
        }
    }

    changed = migrate_zettel_source_catalog_in_data(data)

    assert changed is True
    assert data["zettel"]["enabled_sources"] == [
        "agent_task",
        "screen_block",
        "meeting",
    ]
    assert data["zettel"]["source_catalog_version"] == ZETTEL_SOURCE_CATALOG_VERSION


def test_current_catalog_preserves_a_user_disabled_meeting_source():
    data = {
        "zettel": {
            "enabled_sources": ["agent_task", "screen_block"],
            "source_catalog_version": ZETTEL_SOURCE_CATALOG_VERSION,
        }
    }

    changed = migrate_zettel_source_catalog_in_data(data)

    assert changed is False
    assert data["zettel"]["enabled_sources"] == ["agent_task", "screen_block"]


def test_new_preferences_enable_meetings_by_default():
    assert "meeting" in ZETTEL_SOURCE_KINDS


def test_loading_a_legacy_catalog_persists_the_one_time_migration(tmp_path, monkeypatch):
    settings_file = tmp_path / "preferences.json"
    settings_file.write_text(
        json.dumps({"zettel": {"enabled_sources": ["agent_task", "screen_block"]}})
    )
    monkeypatch.setattr(preferences_model, "SETTINGS_DIR", tmp_path)
    monkeypatch.setattr(preferences_model, "SETTINGS_FILE", settings_file)

    loaded = preferences_model.Preferences.load()

    persisted = json.loads(settings_file.read_text())
    assert "meeting" in loaded.zettel.enabled_sources
    assert persisted["zettel"]["source_catalog_version"] == ZETTEL_SOURCE_CATALOG_VERSION
    assert "meeting" in persisted["zettel"]["enabled_sources"]
