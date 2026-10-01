"""Tests for the loopback credential guard middleware."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

import httpx
import pytest
from fastapi import Depends, FastAPI, WebSocket
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from api.core.security.backend_credentials import BACKEND_TOKEN_HEADER, BackendCredentialStore
from api.core.security.backend_request_guard import (
    BackendRequestGuardMiddleware,
    current_credential_type,
    is_loopback_bind_host,
    require_host_credential,
    resolve_loopback_bind_host,
)

HOST_TOKEN = "a" * 64
WEBVIEW_TOKEN = "b" * 64


@pytest.fixture
def credential_store(tmp_path: Path) -> BackendCredentialStore:
    path = tmp_path / "backend_credentials.json"
    path.write_text(
        json.dumps({"version": 1, "host_token": HOST_TOKEN, "webview_token": WEBVIEW_TOKEN}),
        encoding="utf-8",
    )
    os.chmod(path, 0o600)
    return BackendCredentialStore(path)


class _UnavailableCredentialStore(BackendCredentialStore):
    def classify(self, token: Optional[str]):
        raise OSError("credentials volume unavailable")


def _build_app(credential_store: BackendCredentialStore) -> FastAPI:
    app = FastAPI()
    app.add_middleware(BackendRequestGuardMiddleware, credential_store=credential_store)

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    @app.get("/validation/probe")
    async def validation_probe() -> dict:
        return {"ok": True}

    @app.get("/whoami")
    async def whoami(credential_type: Optional[str] = Depends(current_credential_type)) -> dict:
        return {"credential_type": credential_type}

    @app.post("/host-only", dependencies=[Depends(require_host_credential)])
    async def host_only() -> dict:
        return {"ok": True}

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket) -> None:
        await websocket.accept()
        await websocket.send_json({"credential_type": websocket.scope.get("basil.credential_type")})
        await websocket.close()

    return app


def _client(app: FastAPI, token: str) -> TestClient:
    return TestClient(app, headers={BACKEND_TOKEN_HEADER: token})


def test_health_and_validation_paths_do_not_require_a_token(credential_store) -> None:
    client = _client(_build_app(credential_store), "")

    assert client.get("/health").status_code == 200
    assert client.get("/validation/probe").status_code == 200


def test_missing_and_unknown_tokens_are_rejected(credential_store) -> None:
    app = _build_app(credential_store)

    missing = _client(app, "").get("/whoami")
    unknown = _client(app, "c" * 64).get("/whoami")

    assert missing.status_code == 401
    assert missing.json() == {"detail": "backend_token_required"}
    assert unknown.status_code == 401


def test_host_and_webview_tokens_are_classified(credential_store) -> None:
    app = _build_app(credential_store)

    assert _client(app, HOST_TOKEN).get("/whoami").json() == {"credential_type": "host"}
    assert _client(app, WEBVIEW_TOKEN).get("/whoami").json() == {"credential_type": "webview"}


def test_host_only_dependency_rejects_the_webview_credential(credential_store) -> None:
    app = _build_app(credential_store)

    webview_response = _client(app, WEBVIEW_TOKEN).post("/host-only")

    assert _client(app, HOST_TOKEN).post("/host-only").status_code == 200
    assert webview_response.status_code == 403
    assert webview_response.json() == {"detail": "host_credential_required"}


def test_websocket_accepts_the_header_token(credential_store) -> None:
    with _client(_build_app(credential_store), HOST_TOKEN).websocket_connect("/ws") as websocket:
        assert websocket.receive_json() == {"credential_type": "host"}


def test_websocket_accepts_the_subprotocol_token_and_echoes_only_the_basil_protocol(credential_store) -> None:
    client = _client(_build_app(credential_store), "")

    with client.websocket_connect("/ws", subprotocols=["basil.v1", f"basil.token.{WEBVIEW_TOKEN}"]) as websocket:
        assert websocket.accepted_subprotocol == "basil.v1"
        assert websocket.receive_json() == {"credential_type": "webview"}


def test_websocket_token_without_the_basil_protocol_is_accepted_without_a_subprotocol(credential_store) -> None:
    client = _client(_build_app(credential_store), "")

    with client.websocket_connect("/ws", subprotocols=[f"basil.token.{WEBVIEW_TOKEN}"]) as websocket:
        assert websocket.accepted_subprotocol is None
        assert websocket.receive_json() == {"credential_type": "webview"}


def test_websocket_without_a_token_is_closed_with_policy_violation(credential_store) -> None:
    client = _client(_build_app(credential_store), "")

    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect("/ws"):
            pass

    assert exc_info.value.code == 1008


def test_unavailable_credentials_fail_closed_except_for_exempt_paths(tmp_path: Path) -> None:
    client = _client(_build_app(_UnavailableCredentialStore(tmp_path / "unused.json")), HOST_TOKEN)

    guarded = client.get("/whoami")

    assert guarded.status_code == 503
    assert guarded.json() == {"detail": "backend_credentials_unavailable"}
    assert client.get("/health").status_code == 200


def test_cors_preflight_is_passed_through_without_a_token(credential_store) -> None:
    response = _client(_build_app(credential_store), "").options(
        "/whoami",
        headers={"Origin": "null", "Access-Control-Request-Method": "GET"},
    )

    assert response.status_code == 405


@pytest.mark.asyncio
async def test_non_loopback_peer_is_rejected_even_on_exempt_paths(credential_store) -> None:
    transport = httpx.ASGITransport(app=_build_app(credential_store), client=("192.168.1.20", 50000))
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as client:
        response = await client.get("/health", headers={BACKEND_TOKEN_HEADER: HOST_TOKEN})

    assert response.status_code == 403
    assert response.json() == {"detail": "loopback_required"}


@pytest.mark.asyncio
async def test_foreign_host_header_is_rejected(credential_store) -> None:
    transport = httpx.ASGITransport(app=_build_app(credential_store))
    async with httpx.AsyncClient(transport=transport, base_url="http://attacker.example:8000") as client:
        response = await client.get("/whoami", headers={BACKEND_TOKEN_HEADER: HOST_TOKEN})

    assert response.status_code == 403
    assert response.json() == {"detail": "host_not_allowed"}


@pytest.mark.asyncio
async def test_host_header_port_must_match_the_bound_port(credential_store) -> None:
    transport = httpx.ASGITransport(app=_build_app(credential_store))
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as client:
        response = await client.get(
            "/whoami",
            headers={BACKEND_TOKEN_HEADER: HOST_TOKEN, "Host": "127.0.0.1:9999"},
        )

    assert response.status_code == 403
    assert response.json() == {"detail": "host_not_allowed"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("peer", "base_url"),
    [
        (("127.0.0.1", 50000), "http://localhost:8000"),
        (("127.0.0.1", 50000), "http://127.0.0.1:8000"),
        (("::ffff:127.0.0.1", 50000), "http://127.0.0.1:8000"),
        (("::1", 50000), "http://[::1]:8000"),
    ],
)
async def test_loopback_peers_with_loopback_hosts_are_accepted(credential_store, peer, base_url) -> None:
    transport = httpx.ASGITransport(app=_build_app(credential_store), client=peer)
    async with httpx.AsyncClient(transport=transport, base_url=base_url) as client:
        response = await client.get("/whoami", headers={BACKEND_TOKEN_HEADER: HOST_TOKEN})

    assert response.status_code == 200
    assert response.json() == {"credential_type": "host"}


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1", "[::1]"])
def test_loopback_bind_hosts_are_allowed(host: str) -> None:
    assert is_loopback_bind_host(host)
    assert resolve_loopback_bind_host(host, allow_lan_bind=True) == host


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.5", "::", "basil.local"])
def test_non_loopback_bind_hosts_are_refused(host: str) -> None:
    with pytest.raises(SystemExit) as refused:
        resolve_loopback_bind_host(host, allow_lan_bind=False)
    with pytest.raises(SystemExit) as refused_with_lan_flag:
        resolve_loopback_bind_host(host, allow_lan_bind=True)

    assert "non-loopback" in str(refused.value)
    assert "BASIL_ALLOW_LAN_BIND" in str(refused_with_lan_flag.value)
