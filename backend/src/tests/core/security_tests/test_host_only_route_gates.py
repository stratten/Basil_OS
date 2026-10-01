"""Tests that every host-only mutation rejects the web view credential on the production app."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.core.security.backend_credentials import BACKEND_TOKEN_HEADER, get_backend_credential_store
from api.main import app

HOST_ONLY_ROUTES = [
    ("POST", "/api/v1/agent-tasks/approval/settings"),
    ("POST", "/api/v1/agent-tasks/whitelist"),
    ("PUT", "/api/v1/agent-tasks/whitelist/pattern-1"),
    ("POST", "/settings/provider-profiles"),
    ("PUT", "/settings/provider-profiles/profile-1"),
    ("POST", "/settings/provider-profiles/profile-1/enable"),
    ("POST", "/settings/provider-profiles/profile-1/workspace-grants"),
    ("PUT", "/settings/provider-profiles/profile-1/workspace-grants/grant-1"),
    ("POST", "/settings/connections/manual_token"),
    ("PUT", "/settings/connections/connection-1/policy"),
]


@pytest.mark.parametrize(("method", "path"), HOST_ONLY_ROUTES)
def test_host_only_routes_reject_the_webview_credential(method: str, path: str) -> None:
    webview_token = get_backend_credential_store().current().webview_token
    client = TestClient(app, headers={BACKEND_TOKEN_HEADER: webview_token})

    response = client.request(method, path, json={})

    assert response.status_code == 403
    assert response.json() == {"detail": "host_credential_required"}


@pytest.mark.parametrize(("method", "path"), HOST_ONLY_ROUTES)
def test_host_only_routes_admit_the_host_credential_to_validation(method: str, path: str) -> None:
    client = TestClient(app, raise_server_exceptions=False)

    response = client.request(method, path, json={})

    assert response.status_code != 403
    assert response.status_code != 401
