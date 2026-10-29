"""Settings and model-delete routes for local model residency."""

from types import SimpleNamespace

import importlib

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.core.models.preference_models.transcription import ModelPersistenceDuration
from api.core.models.preferences import Preferences
from api.core.models.model_manager import ModelManager
from api.routes.model_routes import management_routes, predefined_routes
from api.dependencies import get_model_service

settings_router_module = importlib.import_module("api.routes.settings_routes.router")


# ---------------------------------------------------------------- settings


@pytest.fixture
def settings_client(monkeypatch):
    state = {"preferences": Preferences(), "applied": 0}
    monkeypatch.setattr(settings_router_module, "load_preferences", lambda: state["preferences"])

    def save(preferences):
        state["preferences"] = preferences

    monkeypatch.setattr(settings_router_module, "save_preferences", save)

    def applied():
        state["applied"] += 1

    monkeypatch.setattr(settings_router_module, "_apply_model_residency_settings", applied)
    app = FastAPI()
    app.include_router(settings_router_module.router)
    return TestClient(app), state


def model_payload(**overrides):
    payload = {
        "transcription_model": "t",
        "persistence_duration": 300,
        "vision_model": "v",
        "language_model": "l",
        "reasoning_model": "r",
    }
    payload.update(overrides)
    return payload


def test_defaults_keep_the_model_while_a_window_is_open_for_five_minutes():
    models = Preferences().models
    assert models.persistence_duration == 300
    assert models.keep_loaded_while_window_open is True


def test_immediately_and_two_hours_are_valid_choices():
    assert ModelPersistenceDuration.from_seconds(0) is ModelPersistenceDuration.IMMEDIATELY
    assert ModelPersistenceDuration.IMMEDIATELY.display_name == "Immediately"
    assert ModelPersistenceDuration.from_seconds(7200) is ModelPersistenceDuration.HOURS_2
    assert ModelPersistenceDuration.HOURS_2.display_name == "2 hours"
    assert ModelPersistenceDuration.HOURS_1.display_name == "1 hour"


def test_delay_and_window_setting_round_trip(settings_client):
    client, state = settings_client

    response = client.put(
        "/settings/models",
        json=model_payload(persistence_duration=0, keep_loaded_while_window_open=False),
    )

    assert response.status_code == 200
    body = response.json()["updated_settings"]
    assert body["persistence_duration"] == 0
    assert body["keep_loaded_while_window_open"] is False
    assert state["applied"] == 1

    fetched = client.get("/settings/models").json()["settings"]
    assert fetched["persistence_duration"] == 0
    assert fetched["keep_loaded_while_window_open"] is False
    aggregated = client.get("/settings/").json()["models"]
    assert aggregated["keep_loaded_while_window_open"] is False


def test_older_clients_that_omit_the_window_setting_leave_it_alone(settings_client):
    client, state = settings_client
    state["preferences"].models.keep_loaded_while_window_open = False

    response = client.put("/settings/models", json=model_payload(persistence_duration=7200))

    assert response.status_code == 200
    assert state["preferences"].models.persistence_duration == 7200
    assert state["preferences"].models.keep_loaded_while_window_open is False


# ------------------------------------------------------------ route layout


def test_model_delete_and_available_routes_are_registered_once():
    routes = [*predefined_routes.router.routes, *management_routes.router.routes]

    def count(method: str, path: str) -> int:
        return sum(
            1
            for route in routes
            if getattr(route, "path", None) == path and method in getattr(route, "methods", set())
        )

    assert count("DELETE", "/models/predefined/{model_type}/{variant}") == 1
    assert count("GET", "/models/available") == 1
    assert count("POST", "/models/recommendations") == 1
    assert count("GET", "/models/system-info") == 1


# ------------------------------------------------------------ delete route


class _Model:
    def __init__(self, events: list) -> None:
        self._events = events

    async def unload(self) -> None:
        self._events.append("unload")


def delete_client(monkeypatch, tmp_path, events, manager):
    model_path = tmp_path / "Qwen-test.gguf"
    model_path.write_bytes(b"gguf")

    class Downloader:
        def _get_model_path_for_id(self, model_id):
            return model_path

        def remove_model(self, model_type, variant):
            events.append("remove_files")
            model_path.unlink()
            return True

    service = SimpleNamespace(
        model_downloader=Downloader(),
        model_manager=manager,
        _active_models={},
    )

    async def unload_model(model_type, variant):
        model_id = f"{model_type}-{variant}"
        if model_id in service._active_models:
            await manager.unload_model(model_id)
            service._active_models.pop(model_id, None)
            return True
        return False

    service.unload_model = unload_model

    def evict(path):
        events.append("evict_native")
        return []

    monkeypatch.setattr(predefined_routes, "evict_llama_cpp_contexts_under", evict)
    app = FastAPI()
    app.include_router(predefined_routes.router)
    app.dependency_overrides[get_model_service] = lambda: service
    return TestClient(app), service, model_path


def test_delete_unloads_and_evicts_before_removing_files(monkeypatch, tmp_path):
    events: list = []
    manager = ModelManager(tmp_path / "models")
    client, service, model_path = delete_client(monkeypatch, tmp_path, events, manager)
    model = _Model(events)
    manager.adopt_model("Qwen-test", model)
    service._active_models["Qwen-test"] = model

    response = client.delete("/models/predefined/Qwen/test")

    assert response.status_code == 200
    assert events == ["unload", "evict_native", "remove_files"]
    assert not model_path.exists()


def test_delete_returns_409_while_a_run_holds_the_model(monkeypatch, tmp_path):
    events: list = []
    manager = ModelManager(tmp_path / "models")
    client, service, model_path = delete_client(monkeypatch, tmp_path, events, manager)
    model = _Model(events)
    manager.adopt_model("Qwen-test", model)
    service._active_models["Qwen-test"] = model
    lease = manager.acquire_lease("Qwen-test", owner="run")

    response = client.delete("/models/predefined/Qwen/test")

    assert response.status_code == 409
    assert "in use" in response.json()["detail"]
    assert events == []
    assert model_path.exists()

    lease.release()
    response = client.delete("/models/predefined/Qwen/test")
    assert response.status_code == 200


def test_an_open_window_does_not_block_a_delete(monkeypatch, tmp_path):
    events: list = []
    manager = ModelManager(tmp_path / "models", keep_for_windows_provider=lambda: True)
    client, service, model_path = delete_client(monkeypatch, tmp_path, events, manager)
    model = _Model(events)
    manager.adopt_model("Qwen-test", model)
    service._active_models["Qwen-test"] = model
    manager.set_window_hold("ws-1", "w1")

    response = client.delete("/models/predefined/Qwen/test")

    assert response.status_code == 200
    assert "unload" in events
