"""Tests for the meeting post-processing automation transcription settings (2B).

Covers model defaults/round-trip and the GET/PUT route handlers persisting the
new auto-retranscribe / auto-analyze fields.
"""

import pytest

from api.core.models.preferences import Preferences
from api.core.models.preference_models.transcription import (
    TranscriptionSettings,
    TranscriptionTextReplacement,
)
from api.routes.settings_routes import widget_routes


def test_defaults_are_behavior_preserving() -> None:
    settings = TranscriptionSettings()
    assert settings.auto_retranscribe_on_stop is False
    assert settings.auto_analyze_on_complete is False
    assert settings.auto_analyze_modes == []
    assert settings.auto_analyze_custom_instructions == ""
    assert settings.auto_analyze_timing == "after"
    assert settings.text_replacements == []


def test_model_round_trip_preserves_fields() -> None:
    settings = TranscriptionSettings(
        auto_retranscribe_on_stop=True,
        auto_analyze_on_complete=True,
        auto_analyze_modes=["summary", "action_items"],
        auto_analyze_custom_instructions="Focus on risks.",
        auto_analyze_timing="before",
    )
    restored = TranscriptionSettings(**settings.model_dump())
    assert restored.auto_retranscribe_on_stop is True
    assert restored.auto_analyze_modes == ["summary", "action_items"]
    assert restored.auto_analyze_custom_instructions == "Focus on risks."
    assert restored.auto_analyze_timing == "before"


def test_invalid_timing_rejected() -> None:
    with pytest.raises(Exception):
        TranscriptionSettings(auto_analyze_timing="sideways")


@pytest.mark.asyncio
async def test_route_get_put_round_trip(monkeypatch) -> None:
    store = {"prefs": Preferences()}

    monkeypatch.setattr(widget_routes, "load_preferences", lambda: store["prefs"])
    monkeypatch.setattr(
        widget_routes, "save_preferences", lambda p: store.update(prefs=p)
    )

    # GET reflects defaults.
    initial = await widget_routes.get_transcription_settings()
    assert initial.settings.auto_retranscribe_on_stop is False
    assert initial.settings.auto_analyze_timing == "after"

    # PUT persists the new automation fields onto preferences.
    incoming = TranscriptionSettings(
        selected_model=store["prefs"].models.transcription_model,
        auto_retranscribe_on_stop=True,
        auto_analyze_on_complete=True,
        auto_analyze_modes=["suggested_actions"],
        auto_analyze_custom_instructions="Draft follow-ups.",
        auto_analyze_timing="before",
    )
    await widget_routes.update_transcription_settings(incoming)

    persisted = store["prefs"].transcription
    assert persisted.auto_retranscribe_on_stop is True
    assert persisted.auto_analyze_on_complete is True
    assert persisted.auto_analyze_modes == ["suggested_actions"]
    assert persisted.auto_analyze_custom_instructions == "Draft follow-ups."
    assert persisted.auto_analyze_timing == "before"
    assert persisted.text_replacements == []

    # A subsequent GET surfaces the persisted values.
    after = await widget_routes.get_transcription_settings()
    assert after.settings.auto_retranscribe_on_stop is True
    assert after.settings.auto_analyze_modes == ["suggested_actions"]
    assert after.settings.text_replacements == []


def test_text_replacements_normalize_sources_and_reject_duplicates() -> None:
    rule = TranscriptionTextReplacement(
        source="  new   line  ",
        replacement="\n",
    )
    assert rule.source == "new line"

    with pytest.raises(Exception):
        TranscriptionSettings(
            text_replacements=[
                TranscriptionTextReplacement(source="slash", replacement="/"),
                TranscriptionTextReplacement(source="Slash", replacement="//"),
            ]
        )

    with pytest.raises(Exception):
        TranscriptionTextReplacement(source="   ", replacement="/")

    with pytest.raises(Exception):
        TranscriptionTextReplacement(source="x" * 121, replacement="/")

    with pytest.raises(Exception):
        TranscriptionTextReplacement(source="slash", replacement="x" * 501)

    with pytest.raises(Exception):
        TranscriptionSettings(
            text_replacements=[
                TranscriptionTextReplacement(source=f"rule {index}", replacement="")
                for index in range(101)
            ]
        )


@pytest.mark.asyncio
async def test_route_get_put_round_trip_persists_text_replacements(
    monkeypatch,
) -> None:
    store = {"prefs": Preferences()}

    monkeypatch.setattr(widget_routes, "load_preferences", lambda: store["prefs"])
    monkeypatch.setattr(
        widget_routes, "save_preferences", lambda preferences: store.update(prefs=preferences)
    )

    incoming = TranscriptionSettings(
        selected_model=store["prefs"].models.transcription_model,
        text_replacements=[
            TranscriptionTextReplacement(source="slash", replacement="/"),
            TranscriptionTextReplacement(source="new line", replacement="\n"),
        ],
    )
    await widget_routes.update_transcription_settings(incoming)

    persisted = store["prefs"].transcription
    assert persisted.text_replacements == incoming.text_replacements

    after = await widget_routes.get_transcription_settings()
    assert after.settings.text_replacements == incoming.text_replacements


@pytest.mark.asyncio
async def test_live_transcription_default_is_on_and_round_trips(monkeypatch) -> None:
    assert TranscriptionSettings().live_transcription_by_default is True
    store = {"prefs": Preferences()}
    monkeypatch.setattr(widget_routes, "load_preferences", lambda: store["prefs"])
    monkeypatch.setattr(widget_routes, "save_preferences", lambda p: store.update(prefs=p))

    initial = await widget_routes.get_transcription_settings()
    assert initial.settings.live_transcription_by_default is True
    incoming = TranscriptionSettings(
        selected_model=store["prefs"].models.transcription_model,
        live_transcription_by_default=False,
    )
    await widget_routes.update_transcription_settings(incoming)
    assert store["prefs"].transcription.live_transcription_by_default is False
    after = await widget_routes.get_transcription_settings()
    assert after.settings.live_transcription_by_default is False
