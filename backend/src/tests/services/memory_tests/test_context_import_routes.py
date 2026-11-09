"""HTTP status mapping and the job flow of the context import routes."""

import json
import time

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes.memory import context_import_routes
from api.routes.memory.context_import_routes import router
from api.services.memory.context_import import service as service_module
from api.services.memory.context_import.models import MAX_IMPORT_CHARS
from api.services.memory.context_import.service import ContextImportService

ANSWER = json.dumps({"items": [{"category": "undated", "title": "Note", "text": "A note about me."}]})


class _Model:
    def __init__(self, *answers):
        self.answers = list(answers)

    async def complete(self, messages):
        return self.answers.pop(0)


def _install(monkeypatch, tmp_path, model=None):
    stub = ContextImportService(
        connection_factory=lambda: (_ for _ in ()).throw(RuntimeError("database unavailable")),
        proposal_store_factory=lambda: None,
        memory_service_factory=lambda: None,
        backup_dir=tmp_path / "backups",
    )
    monkeypatch.setattr(service_module, "_service", stub)

    async def load_settings_model():
        return model or _Model(ANSWER)

    monkeypatch.setattr(context_import_routes, "load_settings_import_model", load_settings_model)
    return stub


def _client():
    app = FastAPI()
    app.include_router(router)
    # The context manager keeps one event loop alive across requests, which a background import job needs.
    return TestClient(app, raise_server_exceptions=False)


def _wait_for_job(client, job_id):
    for _ in range(100):
        payload = client.get(f"/memory/context-import/jobs/{job_id}").json()
        if payload["state"] != "running":
            return payload
        time.sleep(0.02)
    raise AssertionError("the import job never finished")


def test_starting_a_records_job_maps_empty_input_to_422_and_oversized_input_to_413(monkeypatch, tmp_path):
    _install(monkeypatch, tmp_path)
    with _client() as client:
        empty = client.post("/memory/context-import/jobs/records", json={"text": "   "})
        large = client.post("/memory/context-import/jobs/records", json={"text": "a" * (MAX_IMPORT_CHARS + 1)})

    assert empty.status_code == 422
    assert "nothing to import" in empty.json()["detail"]
    assert large.status_code == 413
    assert "Split it" in large.json()["detail"]


def test_a_records_job_can_be_polled_to_a_preview_whose_id_commit_accepts(monkeypatch, tmp_path):
    _install(monkeypatch, tmp_path)
    with _client() as client:
        started = client.post("/memory/context-import/jobs/records", json={"text": "- a note", "filename": "n.md"})
        finished = _wait_for_job(client, started.json()["job_id"])
        bad = client.post("/memory/context-import/commit", json={"preview_id": finished["result"]["preview_id"], "categories": ["nope"]})
        expired = client.post("/memory/context-import/commit", json={"preview_id": "preview-gone", "categories": ["undated"]})

    assert started.status_code == 200
    assert started.json()["chunks_total"] == 1
    assert finished["state"] == "done"
    assert finished["result"]["counts"]["undated"] == 1
    assert bad.status_code == 400
    assert expired.status_code == 404


def test_a_second_import_while_one_is_reading_is_a_409_and_a_job_can_be_canceled(monkeypatch, tmp_path):
    class _SlowModel:
        async def complete(self, messages):
            import asyncio

            await asyncio.sleep(5)
            return ANSWER

    _install(monkeypatch, tmp_path, model=_SlowModel())
    with _client() as client:
        first = client.post("/memory/context-import/jobs/records", json={"text": "- a note"})
        second = client.post("/memory/context-import/jobs/records", json={"text": "- another note"})
        canceled = client.delete(f"/memory/context-import/jobs/{first.json()['job_id']}")

    assert first.status_code == 200
    assert second.status_code == 409
    assert "still reading" in second.json()["detail"]
    assert canceled.status_code == 200
    assert canceled.json()["message"] == "Stopping."


def test_an_unknown_job_is_a_404_for_both_polling_and_canceling(monkeypatch, tmp_path):
    _install(monkeypatch, tmp_path)
    with _client() as client:
        polled = client.get("/memory/context-import/jobs/job-gone")
        canceled = client.delete("/memory/context-import/jobs/job-gone")

    assert polled.status_code == 404
    assert canceled.status_code == 404


def test_a_profile_job_with_an_unconfirmed_setup_route_is_a_400(monkeypatch, tmp_path):
    _install(monkeypatch, tmp_path)
    with _client() as client:
        response = client.post(
            "/memory/context-import/jobs/profile",
            json={"text": "I am a designer.", "model_access": {"mode": "local", "resolved": False}},
        )

    assert response.status_code == 400
    assert "Choose how I should think first" in response.json()["detail"]


def test_profile_commit_and_undo_map_unknown_ids_to_404(monkeypatch, tmp_path):
    _install(monkeypatch, tmp_path)
    with _client() as client:
        commit = client.post("/memory/context-import/profile/commit", json={"draft_id": "draft-gone", "essentials_md": "- a", "user_md": ""})
        undo = client.delete("/memory/context-import/profile/backups/profile-000000000000")
        traversal = client.delete("/memory/context-import/profile/backups/..%2Fescape")

    assert commit.status_code == 404
    assert undo.status_code == 404
    assert traversal.status_code == 404


def test_a_database_failure_is_a_plain_500_not_a_stack_trace(monkeypatch, tmp_path):
    _install(monkeypatch, tmp_path)
    with _client() as client:
        listing = client.get("/memory/context-import/batches")
        undo = client.delete("/memory/context-import/batches/import-x")

    assert listing.status_code == 500
    assert listing.json()["detail"] == "Past imports could not be listed."
    assert undo.status_code == 500
    assert undo.json()["detail"] == "The import could not be undone."
