"""The Setup Assistant's allowlists live beside the registry, and no setting it allows is unclassified or silently more powerful than the registry says."""

import pytest

from api.services.app_control.classification import POLICIES
from api.services.app_control.entries import AVAILABLE_FONTS, build_default_registry
from api.services.app_control.manifest import Tier
from api.services.app_control.setup_assistant_policy import (
    SETUP_ASSISTANT_ALLOWLISTS,
    SETUP_ASSISTANT_EXCEPTIONS,
    SETUP_ASSISTANT_FONTS,
)


def _allowed_paths():
    return {f"{section}.{name}" for section, names in SETUP_ASSISTANT_ALLOWLISTS.items() for name in names}


def test_every_setting_the_setup_assistant_allows_is_classified_or_curated():
    registry = build_default_registry()
    curated = {f"ui.{name}" for entry in registry.all() if entry.key.startswith("appearance.") for name in entry.covers}
    for path in _allowed_paths():
        assert path in POLICIES or path in curated, f"{path} is allowed in setup but not classified"


def test_a_setting_the_registry_keeps_human_only_is_allowed_in_setup_only_as_a_listed_exception():
    human_only = {path for path in _allowed_paths() if path in POLICIES and POLICIES[path].tier == Tier.HUMAN_ONLY}
    assert human_only == set(SETUP_ASSISTANT_EXCEPTIONS)
    assert all(reason.strip() for reason in SETUP_ASSISTANT_EXCEPTIONS.values())


def test_the_permission_widening_setting_is_a_listed_exception():
    assert "tool_execution.auto_approve_read_only" in SETUP_ASSISTANT_EXCEPTIONS


def test_the_setup_assistant_uses_the_same_font_list_as_the_registry():
    from api.routes.setup_assistant import models  # noqa: F401  (imports in the order the app does)
    from api.services.setup_assistant import action_execution_service as service

    assert SETUP_ASSISTANT_FONTS == set(AVAILABLE_FONTS)
    assert service.UI_AVAILABLE_FONTS == set(AVAILABLE_FONTS)
    assert service.UI_SETTINGS_ALLOWLIST == set(SETUP_ASSISTANT_ALLOWLISTS["ui"])
    assert service.MODEL_SETTINGS_ALLOWLIST == set(SETUP_ASSISTANT_ALLOWLISTS["models"])
    assert service.TOOL_EXECUTION_SETTINGS_ALLOWLIST == {"auto_approve_read_only"}


@pytest.mark.asyncio
async def test_the_settings_changed_event_carries_keys_and_sections_but_no_values(monkeypatch):
    sent = []

    async def capture(payload):
        sent.append(payload)

    from api.services import settings_changed_broadcast

    monkeypatch.setattr(settings_changed_broadcast, "broadcast_json_text", capture)
    first = await settings_changed_broadcast.broadcast_settings_changed(["zettel.history_days", "appearance.text_scale", "zettel.history_days", ""])
    second = await settings_changed_broadcast.broadcast_settings_changed(["behavior.hold_duration"])
    assert second == first + 1
    assert sent[0] == {
        "event_type": "settings_changed",
        "revision": first,
        "keys": ["appearance.text_scale", "zettel.history_days"],
        "sections": ["appearance", "zettel"],
    }
    assert sent[1]["sections"] == ["behavior"]
