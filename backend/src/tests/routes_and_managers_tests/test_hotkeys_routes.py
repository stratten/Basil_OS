"""Tests for the home-board hotkey preferences and settings endpoint."""

import importlib
import json

import pytest
from fastapi.testclient import TestClient

from api.core.models.preferences import HotkeySettings, Preferences
from api.main import app


pytestmark = pytest.mark.use_temp_home

client = TestClient(app)


def test_home_board_toggle_default_is_control_option_b():
    binding = HotkeySettings().home_board_toggle

    assert binding.enabled is True
    assert binding.key == "B"
    assert binding.modifiers == ["control", "option"]
    assert binding.is_double_press is False


def test_loading_existing_preferences_backfills_home_board_toggle():
    preferences_module = importlib.import_module("api.core.models.preferences")
    preferences = Preferences()
    stored = preferences.model_dump(mode="json")
    stored["hotkeys"].pop("home_board_toggle")
    preferences_module.SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
    preferences_module.SETTINGS_FILE.write_text(json.dumps(stored))

    loaded = Preferences.load()

    assert "home_board_toggle" in loaded.hotkeys
    assert loaded.hotkeys["home_board_toggle"].enabled is True
    assert loaded.hotkeys["home_board_toggle"].key == "B"
    assert loaded.hotkeys["home_board_toggle"].modifiers == ["control", "option"]


def test_hotkey_settings_put_persists_home_board_toggle():
    original = Preferences.load()
    try:
        response = client.get("/settings/hotkeys")
        assert response.status_code == 200
        payload = response.json()["settings"]
        payload["home_board_toggle"] = {
            "key": "F9",
            "modifiers": [],
            "enabled": True,
            "description": "Show or hide the Basil Home board",
            "is_double_press": False,
            "double_press_key": None,
        }

        response = client.put("/settings/hotkeys", json=payload)
        assert response.status_code == 200

        response = client.get("/settings/hotkeys")
        assert response.status_code == 200
        saved = response.json()["settings"]["home_board_toggle"]
        assert saved["enabled"] is True
        assert saved["key"] == "F9"
    finally:
        original.save()
