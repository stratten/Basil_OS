"""Coverage for loading the retranscription model before a recording opens its live streams."""

from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from api.routes.meetings import post_processing_routes, router as meetings_router
from api.routes.meetings.models import PrepareRetranscriptionModelConfig
from api.services.whisper_live_core.post_processing.transcription_processor import (
    TranscriptionProcessor,
)


class FakeParakeetService:
    instances = []

    def __init__(self, model_id=None):
        self.model_id = model_id
        self.loaded = False
        self.load_thread_ids = []
        FakeParakeetService.instances.append(self)

    def load_model(self):
        import threading

        self.load_thread_ids.append(threading.get_ident())
        self.loaded = True

    def is_model_loaded(self):
        return self.loaded


@pytest.fixture(autouse=True)
def reset_fake_service():
    FakeParakeetService.instances = []
    yield


def _processor_with_config(monkeypatch, config, model_id="parakeet-id"):
    processor = TranscriptionProcessor(Path("."), 0.0, "Parakeet Display Name")
    monkeypatch.setattr(processor, "_resolve_model_config", lambda: (model_id, config))
    return processor


@pytest.mark.asyncio
async def test_parakeet_model_is_loaded_in_an_executor_thread(monkeypatch):
    import threading

    from api.services.transcription.backends import parakeet_service

    monkeypatch.setattr(parakeet_service, "ParakeetTranscriptionService", FakeParakeetService)
    processor = _processor_with_config(monkeypatch, {"handler": "parakeet", "location": "local"})

    status = await processor.preload_selected_model()

    assert status == TranscriptionProcessor.PRELOAD_STATUS_READY
    service = FakeParakeetService.instances[0]
    assert service.model_id == "parakeet-id"
    assert service.loaded
    assert service.load_thread_ids and service.load_thread_ids[0] != threading.get_ident()


@pytest.mark.asyncio
async def test_cloud_model_is_skipped_without_touching_parakeet(monkeypatch):
    from api.services.transcription.backends import parakeet_service

    monkeypatch.setattr(parakeet_service, "ParakeetTranscriptionService", FakeParakeetService)
    processor = _processor_with_config(monkeypatch, {"handler": "parakeet", "location": "cloud"})

    assert await processor.preload_selected_model() == TranscriptionProcessor.PRELOAD_STATUS_SKIPPED_CLOUD
    assert FakeParakeetService.instances == []


@pytest.mark.asyncio
async def test_non_parakeet_local_model_is_skipped(monkeypatch):
    from api.services.transcription.backends import parakeet_service

    monkeypatch.setattr(parakeet_service, "ParakeetTranscriptionService", FakeParakeetService)
    processor = _processor_with_config(monkeypatch, {"handler": "whisper", "location": "local"})

    assert await processor.preload_selected_model() == TranscriptionProcessor.PRELOAD_STATUS_SKIPPED_NOT_PARAKEET
    assert FakeParakeetService.instances == []


@pytest.mark.asyncio
async def test_a_load_that_leaves_the_model_unloaded_is_an_error(monkeypatch):
    from api.services.transcription.backends import parakeet_service

    class NeverLoads(FakeParakeetService):
        def load_model(self):
            self.loaded = False

    monkeypatch.setattr(parakeet_service, "ParakeetTranscriptionService", NeverLoads)
    processor = _processor_with_config(monkeypatch, {"handler": "parakeet", "location": "local"})

    with pytest.raises(RuntimeError, match="did not finish loading"):
        await processor.preload_selected_model()


@pytest.mark.asyncio
async def test_unregistered_model_raises_runtime_error():
    processor = TranscriptionProcessor(Path("."), 0.0, "definitely-not-a-registered-model")
    with pytest.raises(RuntimeError, match="not registered"):
        await processor.preload_selected_model()


@pytest.mark.asyncio
async def test_route_returns_the_processor_status(monkeypatch):
    async def fake_preload(self):
        return TranscriptionProcessor.PRELOAD_STATUS_READY

    monkeypatch.setattr(TranscriptionProcessor, "preload_selected_model", fake_preload)
    result = await post_processing_routes.prepare_retranscription_model(
        PrepareRetranscriptionModelConfig(model="Parakeet")
    )
    assert result == {"model": "Parakeet", "status": "ready"}


@pytest.mark.asyncio
async def test_route_maps_an_unregistered_model_to_422(monkeypatch):
    async def fake_preload(self):
        raise RuntimeError("Transcription model is not registered: nope")

    monkeypatch.setattr(TranscriptionProcessor, "preload_selected_model", fake_preload)
    with pytest.raises(HTTPException) as error:
        await post_processing_routes.prepare_retranscription_model(
            PrepareRetranscriptionModelConfig(model="nope")
        )
    assert error.value.status_code == 422


@pytest.mark.asyncio
async def test_route_maps_an_unexpected_failure_to_500(monkeypatch):
    async def fake_preload(self):
        raise ValueError("disk exploded")

    monkeypatch.setattr(TranscriptionProcessor, "preload_selected_model", fake_preload)
    with pytest.raises(HTTPException) as error:
        await post_processing_routes.prepare_retranscription_model(
            PrepareRetranscriptionModelConfig(model="Parakeet")
        )
    assert error.value.status_code == 500


def test_post_to_the_static_path_reaches_the_preload_handler_not_a_meeting_id_route(monkeypatch):
    seen_models = []

    async def fake_preload(self):
        seen_models.append(self.model_name)
        return TranscriptionProcessor.PRELOAD_STATUS_READY

    monkeypatch.setattr(TranscriptionProcessor, "preload_selected_model", fake_preload)
    app = FastAPI()
    app.include_router(meetings_router)
    client = TestClient(app)

    response = client.post("/meetings/prepare-retranscription-model", json={"model": "Parakeet"})

    assert response.status_code == 200
    assert response.json() == {"model": "Parakeet", "status": "ready"}
    assert seen_models == ["Parakeet"]


def test_request_without_a_model_is_rejected_before_any_load(monkeypatch):
    async def fail_if_called(self):
        raise AssertionError("preload must not run for an invalid request")

    monkeypatch.setattr(TranscriptionProcessor, "preload_selected_model", fail_if_called)
    app = FastAPI()
    app.include_router(meetings_router)

    response = TestClient(app).post("/meetings/prepare-retranscription-model", json={})

    assert response.status_code == 422
