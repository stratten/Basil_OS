from types import SimpleNamespace

from api.core.models.base_model import ModelState
from api.core.services.model_service import ModelService


def service_with(active_models):
    service = ModelService.__new__(ModelService)
    service._active_models = active_models
    return service


def test_ready_model_is_found_by_registry_id_or_slash_id():
    ready = SimpleNamespace(state=ModelState.READY)
    service = service_with({"Qwen-qwen3-8b-instruct-q4km": ready})
    assert service.get_ready_model_if_active("Qwen-qwen3-8b-instruct-q4km") is ready
    assert service.get_ready_model_if_active("qwen/qwen3-8b-instruct-q4km") is ready


def test_missing_or_unready_models_are_not_returned():
    service = service_with({
        "local-a": SimpleNamespace(state=ModelState.UNLOADED),
        "local-b": SimpleNamespace(state=ModelState.LOADING),
    })
    assert service.get_ready_model_if_active("local-a") is None
    assert service.get_ready_model_if_active("local-b") is None
    assert service.get_ready_model_if_active("absent") is None
