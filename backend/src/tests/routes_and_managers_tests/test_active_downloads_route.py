"""Coverage for the global model-download progress endpoint."""

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.core.services.model_download_manager import DownloadEntry
from api.routes.model_routes.predefined_routes import router as models_router


def test_active_downloads_returns_full_progress_for_all_manager_entries() -> None:
    active = DownloadEntry(
        model_id="Qwen-qwen3-8b-instruct-q4km",
        model_type="Qwen",
        variant="qwen3-8b-instruct-q4km",
        status="downloading",
        progress=0.42,
        bytes_downloaded=420,
        total_bytes=1_000,
        current_file="model.safetensors",
        current_file_percent=0.61,
        files_completed=1,
        total_files=3,
        message="Downloading model.safetensors",
    )
    completed = DownloadEntry(
        model_id="OpenAI-whisper-tiny.en",
        model_type="OpenAI",
        variant="whisper-tiny.en",
        status="completed",
        progress=1.0,
    )
    app = FastAPI()
    app.state.download_manager = SimpleNamespace(list_all=lambda: [active, completed])
    app.include_router(models_router)

    response = TestClient(app).get("/models/download/active")

    assert response.status_code == 200
    assert response.json() == {
        "downloads": [
            {
                "model_id": "Qwen-qwen3-8b-instruct-q4km",
                "model_type": "Qwen",
                "variant": "qwen3-8b-instruct-q4km",
                "progress": 0.42,
                "status": "downloading",
                "total_downloaded": 420,
                "total_size": 1_000,
                "message": "Downloading model.safetensors",
                "current_file": "model.safetensors",
                "current_file_percent": 0.61,
                "files_completed": 1,
                "total_files": 3,
            },
            {
                "model_id": "OpenAI-whisper-tiny.en",
                "model_type": "OpenAI",
                "variant": "whisper-tiny.en",
                "progress": 1.0,
                "status": "completed",
                "total_downloaded": 0,
                "total_size": 0,
                "message": "",
                "current_file": "",
                "current_file_percent": 0.0,
                "files_completed": 0,
                "total_files": 0,
            },
        ]
    }
