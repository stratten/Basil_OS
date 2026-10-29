"""The live notetaker's local engine is always Whisper Base, whatever transcription model is saved for files and retranscription."""

from types import SimpleNamespace

import pytest

from api.routes.meetings import live_transcription_routes
from api.services.live_transcription.config_mapper import map_basil_config_to_upstream

PARAKEET_DISPLAY_NAME = "Parakeet TDT 0.6B v3 — Full Precision (NVIDIA, multilingual)"


def _preferences(transcription_model: str) -> SimpleNamespace:
    return SimpleNamespace(
        models=SimpleNamespace(transcription_model=transcription_model),
        behavior=SimpleNamespace(transcription_language="en"),
    )


async def _registered_live_config(monkeypatch, transcription_model: str) -> dict:
    captured: dict = {}

    async def capture_registration(app, **config) -> bool:
        captured.update(config)
        return True

    monkeypatch.setattr(live_transcription_routes, "is_registered", False)
    monkeypatch.setattr(live_transcription_routes.Preferences, "load", staticmethod(lambda: _preferences(transcription_model)))
    monkeypatch.setattr(live_transcription_routes.whisper_live_service, "register_with_app", capture_registration)
    await live_transcription_routes.startup_event()
    return captured


@pytest.mark.asyncio
async def test_a_parakeet_transcription_model_never_reaches_the_live_path(monkeypatch) -> None:
    config = await _registered_live_config(monkeypatch, PARAKEET_DISPLAY_NAME)

    assert config["model"] == "Base"


@pytest.mark.asyncio
async def test_a_whisper_transcription_model_does_not_change_the_live_model(monkeypatch) -> None:
    config = await _registered_live_config(monkeypatch, "Large V3")

    assert config["model"] == "Base"


@pytest.mark.asyncio
async def test_a_missing_transcription_model_still_gives_whisper_base(monkeypatch) -> None:
    config = await _registered_live_config(monkeypatch, "")

    assert config["model"] == "Base"


@pytest.mark.asyncio
async def test_the_registered_live_config_maps_to_whisper_simulstreaming_not_parakeet(monkeypatch) -> None:
    config = await _registered_live_config(monkeypatch, PARAKEET_DISPLAY_NAME)

    upstream = map_basil_config_to_upstream(config)

    assert upstream["model_size"] == "base"
    assert upstream["backend_policy"] == "simulstreaming"
    assert upstream.get("backend") != "parakeet"
