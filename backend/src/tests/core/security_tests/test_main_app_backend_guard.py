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
    foreign_origin = client.options(
        "/api/v1/agent-tasks/approval/settings",
        headers={"Origin": "http://attacker.example", **preflight_headers},
    )

    assert file_origin.status_code == 200
    assert file_origin.headers["access-control-allow-origin"] == "null"
    assert foreign_origin.status_code == 400
    assert "access-control-allow-origin" not in foreign_origin.headers
