from __future__ import annotations

import pytest
from pydantic import ValidationError

from api.core.models.models_registry import custom_models_registry as registry
from api.core.services.custom_models import CustomModelCreate, CustomModelUpdate


def _create(**overrides):
    values = {
        "model_id": "local-qwen",
        "display_name": "Local Qwen",
        "handler": "openai_compatible",
        "base_url": "http://localhost:11434/v1",
        "model_identifier": "qwen2.5:1.5b",
        "context_window": 16384,
        "max_output_tokens": 1024,
    }
    values.update(overrides)
    return CustomModelCreate(**values)


def test_create_accepts_both_server_types_and_defaults_to_none():
    assert _create().server_type is None
    assert _create(server_type="openai_compatible").server_type == "openai_compatible"
    assert _create(server_type="ollama").server_type == "ollama"


@pytest.mark.parametrize("server_type", ["lmstudio", "OLLAMA ", ""])
def test_create_rejects_unknown_server_types(server_type):
    with pytest.raises(ValidationError):
        _create(server_type=server_type)


def test_create_rejects_ollama_for_non_openai_handlers():
    with pytest.raises(ValidationError, match="ollama"):
        _create(handler="anthropic_compatible", server_type="ollama")


def test_update_validates_server_type():
    assert CustomModelUpdate(server_type="ollama").server_type == "ollama"
    with pytest.raises(ValidationError):
        CustomModelUpdate(server_type="vllm")


@pytest.fixture
def isolated_registry(monkeypatch, tmp_path):
    monkeypatch.setattr(registry, "CUSTOM_MODELS_DIR", tmp_path)
    monkeypatch.setattr(registry, "CUSTOM_MODELS_FILE", tmp_path / "custom_models.json")
    monkeypatch.setattr(registry, "CUSTOM_MODELS_LOCK", tmp_path / "custom_models.json.lock")
    monkeypatch.setattr(registry, "_custom_models_cache", None)
    yield tmp_path
    registry._invalidate_cache()


def _config(**overrides):
    config = {
        "handler": "openai_compatible",
        "location": "local",
        "provider": "custom",
        "display_name": "Local Qwen",
        "base_url": "http://localhost:11434/v1",
        "model_identifier": "qwen2.5:1.5b",
        "context_window": 16384,
        "max_output_tokens": 1024,
        "server_type": "ollama",
    }
    config.update(overrides)
    return config


def test_registry_persists_a_valid_server_type(isolated_registry):
    registry.add_custom_model("local-qwen", _config())
    registry._invalidate_cache()

    assert registry.get_custom_model("local-qwen")["server_type"] == "ollama"


def test_registry_rejects_invalid_server_types_on_add(isolated_registry):
    with pytest.raises(ValueError, match="server_type must be"):
        registry.add_custom_model("local-qwen", _config(server_type="lmstudio"))
    with pytest.raises(ValueError, match="requires the openai_compatible handler"):
        registry.add_custom_model("local-qwen", _config(handler="anthropic_compatible"))

    assert registry.get_custom_models() == {}


def test_registry_rejects_invalid_server_types_on_update(isolated_registry):
    registry.add_custom_model("local-qwen", _config(server_type=None))

    with pytest.raises(ValueError, match="requires the openai_compatible handler"):
        registry.update_custom_model("local-qwen", _config(handler="anthropic_compatible"))

    assert registry.get_custom_model("local-qwen")["handler"] == "openai_compatible"


@pytest.fixture
def route_store(monkeypatch):
    from api.routes.model_routes import custom_routes

    store = {"local-qwen": _config()}
    saved = {}
    monkeypatch.setattr(custom_routes, "get_custom_models", lambda: dict(store))
    monkeypatch.setattr(custom_routes, "registry_update_custom_model", lambda model_id, config: saved.update({model_id: config}))
    return custom_routes, saved


@pytest.mark.asyncio
async def test_update_route_switching_to_anthropic_drops_a_stored_ollama_server_type(route_store):
    custom_routes, saved = route_store

    response = await custom_routes.update_custom_model_endpoint("local-qwen", CustomModelUpdate(handler="anthropic_compatible"))

    assert "server_type" not in response.config
    assert "server_type" not in saved["local-qwen"]


@pytest.mark.asyncio
async def test_update_route_rejects_an_explicit_ollama_on_anthropic(route_store):
    from fastapi import HTTPException

    custom_routes, saved = route_store

    with pytest.raises(HTTPException) as raised:
        await custom_routes.update_custom_model_endpoint(
            "local-qwen", CustomModelUpdate(handler="anthropic_compatible", server_type="ollama")
        )

    assert raised.value.status_code == 400
    assert saved == {}


@pytest.mark.asyncio
async def test_update_route_can_switch_back_to_a_generic_server(route_store):
    custom_routes, saved = route_store

    await custom_routes.update_custom_model_endpoint("local-qwen", CustomModelUpdate(server_type="openai_compatible"))

    assert saved["local-qwen"]["server_type"] == "openai_compatible"
