"""Tests that the production FastAPI app is wired with the loopback credential guard."""

from __future__ import annotations

from fastapi.testclient import TestClient

from api.core.security.backend_credentials import BACKEND_TOKEN_HEADER, get_backend_credential_store
from api.main import app


def test_main_app_requires_a_token_for_api_routes_but_not_for_health() -> None:
    client = TestClient(app, headers={BACKEND_TOKEN_HEADER: ""})

    rejected = client.get("/api/v1/agent-tasks/approval/settings")

    assert rejected.status_code == 401
    assert rejected.json() == {"detail": "backend_token_required"}
    assert client.get("/health").status_code == 200


def test_main_app_accepts_the_host_token() -> None:
    client = TestClient(app)

    assert client.get("/api/v1/agent-tasks/approval/settings").status_code == 200


def test_main_app_rejects_webview_writes_to_approval_settings() -> None:
    webview_token = get_backend_credential_store().current().webview_token
    client = TestClient(app, headers={BACKEND_TOKEN_HEADER: webview_token})

    response = client.post("/api/v1/agent-tasks/approval/settings", json={"approval_mode": "always_approve"})

    assert response.status_code == 403
    assert response.json() == {"detail": "host_credential_required"}


def test_main_app_cors_allows_only_the_file_origin() -> None:
    client = TestClient(app, headers={BACKEND_TOKEN_HEADER: ""})
    preflight_headers = {"Access-Control-Request-Method": "GET", "Access-Control-Request-Headers": "x-basil-token"}

    file_origin = client.options("/api/v1/agent-tasks/approval/settings", headers={"Origin": "null", **preflight_headers})
    shared_file_origin = client.options("/api/v1/agent-tasks/approval/settings", headers={"Origin": "file://", **preflight_headers})
    foreign_origin = client.options(
        "/api/v1/agent-tasks/approval/settings",
        headers={"Origin": "http://attacker.example", **preflight_headers},
    )

    assert file_origin.status_code == 200
    assert file_origin.headers["access-control-allow-origin"] == "null"
    assert shared_file_origin.status_code == 200
    assert shared_file_origin.headers["access-control-allow-origin"] == "file://"
    assert foreign_origin.status_code == 400
    assert "access-control-allow-origin" not in foreign_origin.headers


_SETUP_LOCAL_DOWNLOAD_PATHS = (
    ("POST", "/models/download"),
    ("GET", "/models/predefined/Qwen/qwen35-9b-q4km/download/progress"),
    ("GET", "/setup-assistant/model-access/options"),
)


def test_setup_local_model_download_paths_pass_cors_preflight_from_bundled_pages() -> None:
    client = TestClient(app, headers={BACKEND_TOKEN_HEADER: ""})

    for method, path in _SETUP_LOCAL_DOWNLOAD_PATHS:
        for origin in ("file://", "null"):
            response = client.options(
                path,
                headers={
                    "Origin": origin,
                    "Access-Control-Request-Method": method,
                    "Access-Control-Request-Headers": "content-type,x-basil-token",
                },
            )
            assert response.status_code == 200, (method, path, origin)
            assert response.headers["access-control-allow-origin"] == origin


def test_setup_local_model_download_paths_accept_the_webview_credential() -> None:
    webview_token = get_backend_credential_store().current().webview_token
    client = TestClient(app, headers={BACKEND_TOKEN_HEADER: webview_token})

    options = client.get("/setup-assistant/model-access/options")
    start = client.post(
        "/models/download",
        json={"request": {"model_type": "Qwen", "variant": "qwen35-9b-q4km"}},
    )
    progress = client.get("/models/predefined/Qwen/qwen35-9b-q4km/download/progress")

    assert options.status_code == 200
    # The download manager attaches during the FastAPI lifespan, which TestClient without a context manager does not run, so 503 is the expected guard-passed answer here.
    assert start.status_code not in (401, 403)
    assert progress.status_code not in (401, 403)
