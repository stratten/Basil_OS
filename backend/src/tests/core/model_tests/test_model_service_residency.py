"""ModelService stays in step with the manager's idle unloads, including vision."""

import asyncio
from pathlib import Path

import pytest

from api.core.models import model_manager as manager_module
from api.core.models.base_model import ModelState
from api.core.models.model_types import ModelCapability
from api.core.services import model_service as model_service_module
from api.core.services.model_service import ModelService
from api.services.agent_processing.tools.vision.local_qwen_vl_loader import (
    _LocalQwenVlLlamaWrapper,
)

VISION_ID = "Qwen-qwen3vl-8b-instruct-q4km"


class FakeLlama:
    def __init__(self) -> None:
        self.closed = 0

    def close(self) -> None:
        self.closed += 1

    def create_chat_completion(self, **kwargs):
        return {"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]}


@pytest.fixture
def vision_service(monkeypatch, tmp_path: Path):
    llama = FakeLlama()
    loads = []

    def fake_loader(models_dir, model_id, required_capabilities=None):
        loads.append(model_id)
        return (
            _LocalQwenVlLlamaWrapper(
                llama, tmp_path / "vl.gguf", 8192, model_id=model_id,
                required_capabilities=required_capabilities,
            ),
            None,
        )

    monkeypatch.setattr(
        "api.services.agent_processing.tools.vision.local_qwen_vl_loader.load_local_vision_wrapper",
        fake_loader,
    )
    monkeypatch.setattr(manager_module, "MIN_UNLEASED_GRACE_SECONDS", 0.05)
    monkeypatch.setattr(model_service_module, "_model_persistence_seconds", lambda: 0)
    monkeypatch.setattr(model_service_module, "_keep_loaded_while_window_open", lambda: False)
    service = ModelService(tmp_path)
    service.model_manager._idle_seconds_provider = lambda: 0
    service.model_manager._keep_for_windows_provider = lambda: False
    return service, llama, loads


@pytest.mark.asyncio
async def test_vision_model_is_tracked_by_the_manager_and_idle_unloads(vision_service):
    service, llama, loads = vision_service

    wrapper = await service.load_model_by_id(VISION_ID, {ModelCapability.VISION})
    assert service.model_manager.model_name_for(wrapper) == VISION_ID

    # Loading again reuses the same wrapper instead of loading a second copy.
    assert await service.load_model_by_id(VISION_ID, {ModelCapability.VISION}) is wrapper
    assert loads == [VISION_ID]

    await asyncio.sleep(0.3)
    assert llama.closed == 1  # the native context was really closed
    assert wrapper.state == ModelState.UNLOADED
    assert VISION_ID not in service._active_models  # no stale "ready" wrapper left behind

    # After an idle unload the next request loads it fresh.
    again = await service.load_model_by_id(VISION_ID, {ModelCapability.VISION})
    assert again is not wrapper
    assert loads == [VISION_ID, VISION_ID]
    service.model_manager._models[VISION_ID].unload_task.cancel()


@pytest.mark.asyncio
async def test_a_lease_keeps_the_vision_model_through_an_analysis(vision_service):
    service, llama, _ = vision_service
    wrapper = await service.load_model_by_id(VISION_ID, {ModelCapability.VISION})
    lease = service.model_manager.acquire_lease_for_model(wrapper, owner="vision_analysis_tool")

    await asyncio.sleep(0.3)
    assert llama.closed == 0
    assert VISION_ID in service._active_models

    lease.release()
    await asyncio.sleep(0.2)
    assert llama.closed == 1


@pytest.mark.asyncio
async def test_explicit_unload_through_the_service_closes_the_context(vision_service):
    service, llama, _ = vision_service
    await service.load_model_by_id(VISION_ID, {ModelCapability.VISION})

    ok = await service.unload_model("Qwen", "qwen3vl-8b-instruct-q4km")

    assert ok is True
    assert llama.closed == 1
    assert VISION_ID not in service._active_models


@pytest.mark.asyncio
async def test_acquire_local_vision_llm_returns_an_adapter_and_a_lease(vision_service, monkeypatch):
    from api.services.agent_processing.tools.vision.local_qwen_vl_loader import (
        acquire_local_vision_llm,
    )

    service, llama, _ = vision_service
    monkeypatch.setattr(model_service_module, "get_model_service", lambda: service)

    adapter, lease = await acquire_local_vision_llm(VISION_ID)

    assert adapter is not None
    assert service.model_manager.is_leased(VISION_ID)
    lease.release()
    assert not service.model_manager.is_leased(VISION_ID)
    await asyncio.sleep(0.2)
    assert llama.closed == 1


def test_residency_settings_are_cached_briefly(monkeypatch):
    reads = []

    class FakeModels:
        persistence_duration = 120
        keep_loaded_while_window_open = False

    class FakePreferences:
        models = FakeModels()

        @classmethod
        def load(cls):
            reads.append(1)
            return cls()

    monkeypatch.setattr("api.core.models.preferences.Preferences", FakePreferences)
    model_service_module.reset_residency_settings_cache()

    assert model_service_module._model_persistence_seconds() == 120
    assert model_service_module._keep_loaded_while_window_open() is False
    assert len(reads) == 1  # both reads share one disk read

    model_service_module.reset_residency_settings_cache()
    model_service_module._model_persistence_seconds()
    assert len(reads) == 2
    model_service_module.reset_residency_settings_cache()
