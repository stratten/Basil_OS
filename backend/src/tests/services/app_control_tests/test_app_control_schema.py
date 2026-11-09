"""Every preference is classified, and every writable one can be read, parsed, written, and read back."""

import enum

import pytest

from api.core.models.preferences import Preferences
from api.services.app_control.apply_hooks import default_apply_hooks
from api.services.app_control.classification import (
    APPLY_GROUPS,
    DESCRIPTION_OVERRIDES,
    POLICIES,
    REVIEWED_NAME_EXCEPTIONS,
    SENSITIVE_NAME_WORDS,
)
from api.services.app_control.entries import build_default_registry
from api.services.app_control.manifest import Tier
from api.services.app_control.preference_schema import classify_annotation, iter_schema_fields


def _curated_ui_paths(registry):
    return {f"ui.{name}" for entry in registry.all() if entry.key.startswith("appearance.") for name in entry.covers}


def test_every_preference_is_classified_or_curated_and_nothing_else_is():
    registry = build_default_registry()
    fields = {field.path for field in iter_schema_fields()}
    classified = set(POLICIES)
    curated = _curated_ui_paths(registry)
    missing = fields - classified - curated
    assert not missing, f"Classify these new settings in app_control/classification.py: {sorted(missing)}"
    assert not (classified - fields), f"These classified settings no longer exist: {sorted(classified - fields)}"
    assert not (classified & curated), "A setting is both curated and classified"


def test_every_writable_setting_has_a_description_for_the_agent():
    registry = build_default_registry()
    for field in iter_schema_fields():
        policy = POLICIES.get(field.path)
        if policy and policy.tier != Tier.HUMAN_ONLY:
            assert field.description or DESCRIPTION_OVERRIDES.get(field.path), f"{field.path} needs a description"
            assert registry.get(field.path).description


def test_sensitive_names_are_human_only_unless_reviewed():
    for path, policy in POLICIES.items():
        if any(word in path for word in SENSITIVE_NAME_WORDS) and path not in REVIEWED_NAME_EXCEPTIONS:
            assert policy.tier == Tier.HUMAN_ONLY, f"{path} looks security-sensitive but is writable"


def test_the_permission_system_and_accounts_are_entirely_human_only():
    for path, policy in POLICIES.items():
        if path.startswith(("tool_execution.", "auth.", "connections.")):
            assert policy.tier == Tier.HUMAN_ONLY, path


def test_settings_that_leave_the_mac_or_listen_need_the_stronger_tier():
    for path in (
        "models.use_api_models",
        "models.openai_enabled",
        "behavior.enable_voice_listener_at_startup",
        "ambient_suggestions.allow_cloud_evaluation",
        "meeting_detection.enabled",
        "browser_automation.default_session_mode",
    ):
        assert POLICIES[path].tier == Tier.PRIVACY, path


def test_apply_groups_are_known_and_have_a_hook():
    hooks = default_apply_hooks()
    for policy in POLICIES.values():
        assert policy.group in APPLY_GROUPS
        if policy.group:
            assert policy.group in hooks
    assert all(policy.group == "" for policy in POLICIES.values() if policy.tier == Tier.HUMAN_ONLY)


def test_human_only_entries_are_listed_without_a_way_to_write_them():
    registry = build_default_registry()
    for path, policy in POLICIES.items():
        if policy.tier == Tier.HUMAN_ONLY:
            entry = registry.get(path)
            assert entry is not None and not entry.changeable and entry.write is None and entry.parse is None
            assert policy.reason in entry.description


def test_every_writable_setting_round_trips_its_own_current_value():
    registry = build_default_registry()
    for entry in registry.all():
        if not entry.changeable or entry.kind == "color":
            continue  # a hex color is rounded to 8 bits per channel, so it is checked in the engine tests through the journal
        preferences = Preferences()
        current = entry.read(preferences)
        parsed = entry.parse(entry.render(current))
        assert parsed == current or (isinstance(parsed, list) and parsed == [float(x) for x in current]), entry.key
        entry.write(preferences, parsed)
        assert entry.read(preferences) == current, entry.key


def test_kinds_are_classified_from_annotations():
    assert classify_annotation(bool)[0] == "bool"
    assert classify_annotation(int)[0] == "int"
    assert classify_annotation(list)[0] == "complex"
    assert classify_annotation(__import__("typing").Optional[str])[0] == "complex"

    class Mode(str, enum.Enum):
        A = "a"

    assert classify_annotation(Mode) == ("choice", (Mode.A,))


def test_parsers_reject_the_wrong_kind_of_value():
    registry = build_default_registry()
    flag = registry.get("behavior.show_notifications")
    assert flag.parse("off") is False and flag.parse(True) is True
    with pytest.raises(ValueError):
        flag.parse("maybe")
    count = registry.get("zettel.history_days")
    assert count.parse("30") == 30 and count.parse(30.0) == 30
    for bad in (True, 1.5, "x", None, -1, 10_000):
        with pytest.raises(ValueError):
            count.parse(bad)
    text = registry.get("transcription.auto_analyze_custom_instructions")
    assert text.parse("be brief") == "be brief"
    with pytest.raises(ValueError):
        text.parse(5)
    clock = registry.get("zettel.narrative_scheduled_time")
    assert clock.parse(" 04:30 ") == "04:30"
    for bad in ("4:30", "24:00", "04:60", "", 430):
        with pytest.raises(ValueError):
            clock.parse(bad)
    mode = registry.get("zettel.narrative_mode")
    assert mode.parse("Continuous") == "continuous"
    with pytest.raises(ValueError):
        mode.parse("sometimes")
    browser = registry.get("browser_automation.preferred_user_browser")
    assert browser.parse("Safari").value == "safari"
    assert browser.render(browser.parse("safari")) == "safari"
    assert list(browser.allowed) == ["system_default", "chrome", "edge", "safari"]


def test_a_changed_setting_lands_in_the_right_section():
    registry = build_default_registry()
    preferences = Preferences()
    registry.get("meeting_detection.poll_seconds").write(preferences, 30.0)
    registry.get("zettel.narrative_reasoning_effort").write(preferences, "medium")
    assert preferences.meeting_detection.poll_seconds == 30.0
    assert preferences.zettel.narrative_reasoning_effort == "medium"
