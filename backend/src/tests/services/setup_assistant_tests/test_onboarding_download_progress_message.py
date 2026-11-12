"""The setup page shows the backend's waiting line under a download that has not received bytes yet, so the starter progress route must carry it for active downloads only."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from api.main import app

WAITING = "Waiting for Hugging Face to start sending data (20s)..."


def _entry(status: str, message: str, progress: float = 0.0, bytes_downloaded: int = 0, total_bytes: int = 0):
    return SimpleNamespace(
        status=status,
        progress=progress,
        bytes_downloaded=bytes_downloaded,
        total_bytes=total_bytes,
        message=message,
    )


@pytest.fixture
def progress_for():
    """Returns a function that reads the starter progress route while every starter model has the given download entry."""
    from api.routes.onboarding import get_model_service

    had_manager = hasattr(app.state, "download_manager")
    previous_manager = getattr(app.state, "download_manager", None)
    app.state.download_manager = None
    app.dependency_overrides[get_model_service] = lambda: SimpleNamespace(is_model_downloaded=lambda *_: False)

    def read(entry):
        app.state.download_manager = SimpleNamespace(get_by_pair=lambda *_: entry)
        response = TestClient(app).get("/onboarding/download-progress")
        assert response.status_code == 200
        return response.json()["models"]

    yield read

    app.dependency_overrides.pop(get_model_service, None)
    if had_manager:
        app.state.download_manager = previous_manager
    else:
        del app.state.download_manager


@pytest.mark.parametrize("status", ["downloading", "queued"])
def test_an_active_download_carries_its_waiting_line(progress_for, status):
    records = progress_for(_entry(status, WAITING))

    assert records
    assert all(record["message"] == WAITING for record in records.values())


def test_a_download_with_bytes_still_carries_the_current_line_and_its_byte_counts(progress_for):
    records = progress_for(_entry("downloading", "Downloading model.gguf...", progress=0.4, bytes_downloaded=400, total_bytes=1000))

    for record in records.values():
        assert record["message"] == "Downloading model.gguf..."
        assert record["total_downloaded"] == 400
        assert record["total_size"] == 1000


@pytest.mark.parametrize("status", ["failed", "completed", "user_canceled", "skipped_installed"])
def test_a_download_that_is_not_active_carries_no_line(progress_for, status):
    records = progress_for(_entry(status, WAITING))

    assert all("message" not in record for record in records.values())


def test_an_empty_line_is_left_out(progress_for):
    records = progress_for(_entry("downloading", ""))

    assert all("message" not in record for record in records.values())


def test_a_model_with_no_download_entry_carries_no_line(progress_for):
    records = progress_for(None)

    assert all(record["status"] == "pending" for record in records.values())
    assert all("message" not in record for record in records.values())
