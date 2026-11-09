"""Hex colors, the Appearance entries, and the coverage test that stops a new Appearance setting shipping unclassified."""

import pytest

from api.core.models.preferences import Preferences
from api.routes.settings_routes.appearance_routes import AppearanceSettings
from api.services.app_control.colors import format_hex_color, parse_hex_color
from api.services.app_control.entries import (
    AVAILABLE_FONTS,
    NOT_AGENT_CONTROLLABLE,
    build_default_registry,
)
from api.services.app_control.manifest import Tier


def test_hex_round_trip_and_formats():
    assert format_hex_color(parse_hex_color("#ff69b4")) == "#FF69B4"
    assert format_hex_color(parse_hex_color("FF69B4")) == "#FF69B4"
    assert parse_hex_color(" #000000 ") == [0.0, 0.0, 0.0]


@pytest.mark.parametrize("value", ["", "#12345", "#GGGGGG", "pink", "#1234567", None, 5, ["#FFFFFF"]])
def test_malformed_colors_are_rejected_with_a_message(value):
    with pytest.raises(ValueError):
        parse_hex_color(value)


def test_every_appearance_field_is_covered_or_explained():
    registry = build_default_registry()
    covered = {name for entry in registry.all() for name in entry.covers}
    unclassified = set(AppearanceSettings.model_fields) - covered - set(NOT_AGENT_CONTROLLABLE)
    assert not unclassified, f"Classify these Appearance fields in app_control/entries.py: {sorted(unclassified)}"


def test_no_entry_covers_a_field_that_does_not_exist():
    registry = build_default_registry()
    covered = {name for entry in registry.all() if entry.key.startswith("appearance.") for name in entry.covers}
    assert covered <= set(AppearanceSettings.model_fields)


def test_registry_keys_are_unique_and_human_only_entries_cannot_change():
    registry = build_default_registry()
    keys = [entry.key for entry in registry.all()]
    assert len(keys) == len(set(keys))
    for entry in registry.all():
        if entry.tier == Tier.HUMAN_ONLY:
            assert not entry.changeable


def test_the_chain_expansion_setting_is_the_behavioral_example():
    assert build_default_registry().get("appearance.agent_task_chain_expansion").tier == Tier.BEHAVIORAL


def test_font_choices_match_the_native_list_and_are_case_insensitive():
    entry = build_default_registry().get("appearance.preferred_font")
    assert tuple(entry.allowed) == AVAILABLE_FONTS
    assert entry.parse("menlo") == "Menlo"
    with pytest.raises(ValueError):
        entry.parse("Comic Sans")


def test_text_scale_accepts_only_the_steps():
    entry = build_default_registry().get("appearance.text_scale")
    assert entry.parse(1.25) == 1.25
    assert entry.parse("1.4") == 1.4
    for bad in (1.2, "big", None, float("nan")):
        with pytest.raises(ValueError):
            entry.parse(bad)


def test_color_entries_read_and_write_the_raw_floats():
    entry = build_default_registry().get("appearance.primary_color")
    preferences = Preferences()
    entry.write(preferences, [1.0, 0.0, 0.5])
    assert entry.read(preferences) == [1.0, 0.0, 0.5]
    assert preferences.ui.primary_color_blue == 0.5


def test_search_matches_every_word():
    registry = build_default_registry()
    assert {entry.key for entry in registry.search("text size")} == {"appearance.text_scale"}
    assert registry.search("zzzz") == []
