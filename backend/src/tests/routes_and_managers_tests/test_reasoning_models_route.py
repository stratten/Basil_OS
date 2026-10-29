import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

from api.routes.settings_routes.api_models import reasoning_routes


def _preferences(
    *,
    api_enabled: bool,
    anthropic_enabled: bool = False,
    reasoning_fallback_enabled: bool = True,
    reasoning_fallback_model_id: str = "",
) -> SimpleNamespace:
    return SimpleNamespace(
        models=SimpleNamespace(
            use_api_models=api_enabled,
            reasoning_model="Qwen-local",
            anthropic_enabled=anthropic_enabled,
            anthropic_models={"claude-test": True},
            openai_enabled=False,
            openai_models={},
            gemini_enabled=False,
            gemini_models={},
            reasoning_fallback_enabled=reasoning_fallback_enabled,
            reasoning_fallback_model_id=reasoning_fallback_model_id,
        )
    )


def _model_service(*, valid: bool = True) -> MagicMock:
    service = MagicMock()
    service.get_installed_models.return_value = {
        "Qwen": {
            "variants": {
                "local": {
                    "model_id": "Qwen-local",
                    "valid": valid,
                    "name": "Installed Qwen",
                    "capabilities": ["reasoning"],
                }
            }
        }
    }
    return service


def test_reasoning_models_returns_local_models_when_api_access_is_disabled(monkeypatch):
    monkeypatch.setattr(reasoning_routes, "load_preferences", lambda: _preferences(api_enabled=False))
    monkeypatch.setattr(
        reasoning_routes,
        "get_local_reasoning_models",
        lambda: {
            "Qwen-local": {
                "display_name": "Registry Qwen",
                "provider": "qwen",
                "capabilities": ["reasoning"],
            }
        },
    )

    response = asyncio.run(reasoning_routes.get_api_reasoning_models(_model_service()))

    assert response.current_model == "Qwen-local"
    assert response.api_models_enabled is False
    assert [model.id for model in response.models] == ["Qwen-local"]
    assert response.models[0].category == "local"
    assert response.models[0].display_name == "Installed Qwen"


def test_reasoning_models_omits_invalid_local_variants(monkeypatch):
    monkeypatch.setattr(reasoning_routes, "load_preferences", lambda: _preferences(api_enabled=False))
    monkeypatch.setattr(
        reasoning_routes,
        "get_local_reasoning_models",
        lambda: {"Qwen-local": {"provider": "qwen", "capabilities": ["reasoning"]}},
    )

    response = asyncio.run(reasoning_routes.get_api_reasoning_models(_model_service(valid=False)))

    assert response.models == []


def test_reasoning_models_orders_local_api_and_custom_groups(monkeypatch):
    monkeypatch.setattr(reasoning_routes, "load_preferences", lambda: _preferences(api_enabled=True, anthropic_enabled=True))
    monkeypatch.setattr(
        reasoning_routes,
        "get_local_reasoning_models",
        lambda: {"Qwen-local": {"provider": "qwen", "capabilities": ["reasoning"]}},
    )
    monkeypatch.setattr(
        reasoning_routes,
        "_get_models_from_registry_for_provider",
        lambda provider: [("claude-test", {"display_name": "Claude Test"})] if provider == "anthropic" else [],
    )
    monkeypatch.setattr(
        reasoning_routes,
        "get_model_capabilities_from_implementation",
        lambda provider, model_id: ["reasoning"],
    )
    monkeypatch.setattr(
        "api.core.models.models_registry.get_custom_models",
        lambda: {
            "custom-test": {
                "display_name": "Custom Test",
                "capabilities": ["reasoning"],
                "handler": "openai_compatible",
            }
        },
    )

    response = asyncio.run(reasoning_routes.get_api_reasoning_models(_model_service()))

    assert [(model.id, model.category) for model in response.models] == [
        ("Qwen-local", "local"),
        ("claude-test", "api"),
        ("custom-test", "custom"),
    ]


def test_reasoning_models_response_exposes_fallback_settings(monkeypatch):
    monkeypatch.setattr(
        reasoning_routes,
        "load_preferences",
        lambda: _preferences(
            api_enabled=False,
            reasoning_fallback_enabled=True,
            reasoning_fallback_model_id="qwen-local-7b",
        ),
    )
    monkeypatch.setattr(reasoning_routes, "get_local_reasoning_models", lambda: {})

    response = asyncio.run(reasoning_routes.get_api_reasoning_models(_model_service()))

    assert response.fallback_enabled is True
    assert response.fallback_model_id == "qwen-local-7b"


def _api_only_setup(monkeypatch, stored_model_id: str) -> tuple[SimpleNamespace, list]:
    preferences = _preferences(api_enabled=True, anthropic_enabled=True)
    preferences.models.reasoning_model = stored_model_id
    saved = []
    monkeypatch.setattr(reasoning_routes, "load_preferences", lambda: preferences)
    monkeypatch.setattr("api.core.preferences.preferences_io.save_preferences", lambda saved_preferences: saved.append(saved_preferences.models.reasoning_model))
    monkeypatch.setattr(reasoning_routes, "get_local_reasoning_models", lambda: {})
    monkeypatch.setattr(
        reasoning_routes,
        "_get_models_from_registry_for_provider",
        lambda provider: [("claude-test", {"display_name": "Claude Test"})] if provider == "anthropic" else [],
    )
    monkeypatch.setattr(reasoning_routes, "get_model_capabilities_from_implementation", lambda provider, model_id: ["reasoning"])
    monkeypatch.setattr("api.core.models.models_registry.get_custom_models", lambda: {})
    return preferences, saved


def test_reasoning_models_heals_an_unavailable_stored_default_to_the_first_picker_entry(monkeypatch):
    preferences, saved = _api_only_setup(monkeypatch, "qwen/qwen35-9b-q4km")

    response = asyncio.run(reasoning_routes.get_api_reasoning_models(_model_service(valid=False)))

    assert response.current_model == "claude-test"
    assert preferences.models.reasoning_model == "claude-test"
    assert saved == ["claude-test"]


def test_reasoning_models_never_overwrites_an_available_stored_choice(monkeypatch):
    preferences, saved = _api_only_setup(monkeypatch, "claude-test")

    response = asyncio.run(reasoning_routes.get_api_reasoning_models(_model_service(valid=False)))

    assert response.current_model == "claude-test"
    assert saved == []
