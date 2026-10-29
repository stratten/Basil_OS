import asyncio
from types import SimpleNamespace

from api.core.models.models_registry import get_cloud_transcription_models
from api.routes.settings_routes.api_models import helpers, model_settings_routes


def _preferences() -> SimpleNamespace:
    return SimpleNamespace(
        models=SimpleNamespace(
            anthropic_enabled=False,
            anthropic_models={},
            openai_enabled=True,
            openai_models={},
            gemini_enabled=False,
            gemini_models={},
            use_api_models=True,
            api_extended_thinking=False,
            reasoning_model="",
            vision_model="",
            language_model="",
        )
    )


def test_registry_listing_excludes_cloud_transcription_models_from_openai() -> None:
    transcription_ids = set(get_cloud_transcription_models())
    assert transcription_ids, "the transcription registry must define models for this test to mean anything"

    listed_ids = {model_id for model_id, _ in helpers._get_models_from_registry_for_provider("openai")}

    assert listed_ids, "OpenAI reasoning models must still be listed"
    assert listed_ids.isdisjoint(transcription_ids)


def test_registry_listing_keeps_every_reasoning_model_for_each_provider() -> None:
    for provider in ("anthropic", "openai", "gemini"):
        for model_id, _ in helpers._get_models_from_registry_for_provider(provider):
            assert "reasoning" in helpers.get_model_capabilities_from_implementation(provider, model_id)


def test_api_models_route_has_no_transcription_models_under_openai(monkeypatch) -> None:
    monkeypatch.setattr(model_settings_routes, "load_preferences", _preferences)

    response = asyncio.run(model_settings_routes.get_api_models())

    openai = response.api_models["openai"]
    transcription_ids = set(get_cloud_transcription_models())
    assert transcription_ids.isdisjoint(openai["models"])
    assert transcription_ids.isdisjoint(openai["model_order"])
    assert openai["model_order"], "OpenAI reasoning models must still be listed"
