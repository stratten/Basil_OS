"""The register route with a background program and secrets, the control routes, the delete cleanup, and the route classification."""

from __future__ import annotations

import sys
import uuid
from pathlib import Path
from typing import Any, Dict, Iterator, List

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.core.models.preferences import Preferences
from api.core.preferences import preferences_io
from api.core.security.backend_request_guard import require_host_credential
from api.dependencies import get_sqlite_knowledge_service
from api.routes.connections import routes as connection_routes
from api.routes.connections.routes import router
from api.services.app_control.route_classification import HUMAN_ONLY, classify_route
from api.services.mcp_connectors import local_server_launch, local_server_lifecycle
from api.services.mcp_connectors.companion_supervisor import CompanionSupervisor, set_companion_supervisor
from api.services.mcp_connectors.local_server_secrets import SecretResolution
from api.services.mcp_connectors.port_allocation import port_accepts_connections

FIXTURE = str(Path(__file__).with_name("stdio_fixture_server.py"))
LISTEN_FOREVER = (
    "import socket, sys, time\n"
    "s = socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)\n"
    "s.bind(('127.0.0.1', int(sys.argv[1]))); s.listen()\n"
    "while True: time.sleep(1)\n"
)
EXIT_AT_ONCE = "raise SystemExit(3)\n"
BASE = "/settings/connections"


class _FakeCallLog:
    async def delete_for_connection(self, connection_id: str) -> None:
        return None


class _FakeKnowledge:
    mcp_call_log_repository = _FakeCallLog()


@pytest.fixture
def stored_preferences(monkeypatch) -> Dict[str, Preferences]:
    holder = {"value": Preferences()}
    monkeypatch.setattr(preferences_io, "load_preferences", lambda: holder["value"].model_copy(deep=True))
    monkeypatch.setattr(preferences_io, "save_preferences", lambda prefs: holder.__setitem__("value", prefs.model_copy(deep=True)))
    return holder


@pytest.fixture
def keychain(monkeypatch) -> Dict[str, Any]:
    """Secret values the fake app holds, plus what the backend asked it to delete."""
    state: Dict[str, Any] = {"values": {"API_KEY": "k-123", "BRIDGE_TOKEN": "t-456"}, "deleted": [], "pushed_deletes": []}

    async def _resolve(connection_id: str, names: Any, *, wait_for_host: bool = False) -> SecretResolution:
        values = {name: state["values"][name] for name in names if name in state["values"]}
        return SecretResolution(values=values, missing=[name for name in names if name not in state["values"]])

    async def _delete(connection_id: str, names: Any) -> None:
        state["deleted"].extend(f"{connection_id}.env.{name}" for name in names)

    async def _push_delete(connection_id: str) -> None:
        state["pushed_deletes"].append(connection_id)

    from api.services.mcp_connectors import companion_supervisor

    monkeypatch.setattr(local_server_launch, "resolve_secret_env", _resolve)
    monkeypatch.setattr(companion_supervisor, "resolve_secret_env", _resolve)
    monkeypatch.setattr(local_server_lifecycle, "delete_secret_values", _delete)
    monkeypatch.setattr(connection_routes, "_push_token_delete_to_swift", _push_delete)
    return state


@pytest.fixture
def client(tmp_path, stored_preferences, keychain) -> Iterator[TestClient]:
    supervisor = CompanionSupervisor(tmp_path / "local_servers", ready_timeout_seconds=15.0, no_port_grace_seconds=0.3, stop_grace_seconds=3.0)
    set_companion_supervisor(supervisor)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_host_credential] = lambda: None
    app.dependency_overrides[get_sqlite_knowledge_service] = lambda: _FakeKnowledge()
    with TestClient(app) as test_client:
        yield test_client
        test_client.portal.call(supervisor.stop_all)
    set_companion_supervisor(None)


def _body(**overrides: Any) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "friendly_name": "Bridge server",
        "command": sys.executable,
        "args": [FIXTURE],
        "env": {"FIXTURE_GREETING": "port-{port}"},
        "secret_env": ["API_KEY"],
        "companion": {"command": sys.executable, "args": ["-c", LISTEN_FOREVER, "{port}"], "secret_env": ["BRIDGE_TOKEN"]},
        "connection_id": str(uuid.uuid4()),
    }
    body.update(overrides)
    return body


def _stored(holder: Dict[str, Preferences]) -> List[Any]:
    return holder["value"].connections.mcp_connections


def test_registering_a_server_with_a_background_program_starts_both_and_reports_the_status(client, stored_preferences):
    body = _body()

    response = client.post(f"{BASE}/local_server", json=body)

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["id"] == body["connection_id"]
    assert data["auth_kind"] == "local"
    assert {tool["name"] for tool in data["tools"]} >= {"echo", "where_am_i"}
    local = data["local_server"]
    assert local["secret_env"] == ["API_KEY"]
    assert local["companion"]["status"] == "running"
    assert local["companion"]["secret_env"] == ["BRIDGE_TOKEN"]
    assert local["companion"]["start_with_basil"] is True
    assert local["companion"]["log_tail"] == ""
    assert len(_stored(stored_preferences)) == 1


def test_a_background_program_that_exits_at_once_leaves_nothing_behind(client, stored_preferences, keychain):
    body = _body(companion={"command": sys.executable, "args": ["-c", EXIT_AT_ONCE, "{port}"]})

    response = client.post(f"{BASE}/local_server", json=body)

    assert response.status_code == 502
    assert "exit code 3" in response.json()["detail"]["message"]
    assert _stored(stored_preferences) == []
    assert set(keychain["deleted"]) == {f"{body['connection_id']}.env.API_KEY"}


def test_secret_values_that_were_not_entered_stop_the_registration_and_clean_up(client, stored_preferences, keychain):
    keychain["values"].pop("BRIDGE_TOKEN")
    body = _body()

    response = client.post(f"{BASE}/local_server", json=body)

    assert response.status_code == 502
    assert "BRIDGE_TOKEN" in response.json()["detail"]["message"]
    assert _stored(stored_preferences) == []


def test_the_control_routes_start_stop_and_switch_the_background_program(client, stored_preferences):
    body = _body()
    created = client.post(f"{BASE}/local_server", json=body).json()
    connection_id = created["id"]

    stopped = client.post(f"{BASE}/local_server/{connection_id}/companion/stop")
    assert stopped.status_code == 200
    assert stopped.json()["local_server"]["companion"]["status"] == "stopped"

    started = client.post(f"{BASE}/local_server/{connection_id}/companion/start")
    assert started.status_code == 200
    assert started.json()["local_server"]["companion"]["status"] == "running"

    switched = client.put(f"{BASE}/local_server/{connection_id}/companion", json={"start_with_basil": False})
    assert switched.status_code == 200
    assert switched.json()["local_server"]["companion"]["start_with_basil"] is False
    assert _stored(stored_preferences)[0].stdio.companion.start_with_basil is False


def test_the_control_routes_refuse_a_server_without_a_background_program_and_an_unknown_one(client, stored_preferences):
    plain = client.post(f"{BASE}/local_server", json={"friendly_name": "Plain", "command": sys.executable, "args": [FIXTURE, "plain"]}).json()

    for method, path, kwargs in (
        ("post", f"{BASE}/local_server/{plain['id']}/companion/start", {}),
        ("post", f"{BASE}/local_server/{plain['id']}/companion/stop", {}),
        ("put", f"{BASE}/local_server/{plain['id']}/companion", {"json": {"start_with_basil": True}}),
    ):
        response = getattr(client, method)(path, **kwargs)
        assert response.status_code == 409, path
    assert client.post(f"{BASE}/local_server/{uuid.uuid4()}/companion/start").status_code == 404


def test_removing_the_connection_stops_the_program_and_deletes_every_saved_secret(client, stored_preferences, keychain):
    body = _body()
    created = client.post(f"{BASE}/local_server", json=body).json()
    port = created["local_server"]["companion"]["port"]
    assert port is not None
    assert client.portal.call(port_accepts_connections, port) is True

    response = client.delete(f"{BASE}/{created['id']}")

    assert response.status_code == 200
    assert client.portal.call(port_accepts_connections, port) is False
    assert set(keychain["deleted"]) == {f"{created['id']}.env.API_KEY", f"{created['id']}.env.BRIDGE_TOKEN"}
    assert keychain["pushed_deletes"] == [created["id"]]
    assert _stored(stored_preferences) == []


def test_a_duplicate_and_a_bad_spec_are_still_refused_before_anything_starts(client, stored_preferences):
    assert client.post(f"{BASE}/local_server", json=_body()).status_code == 200

    duplicate = client.post(f"{BASE}/local_server", json=_body(friendly_name="Again", connection_id=str(uuid.uuid4())))
    bad = client.post(f"{BASE}/local_server", json=_body(args=[FIXTURE, "other"], secret_env=["1BAD"], connection_id=str(uuid.uuid4())))

    assert duplicate.status_code == 409
    assert bad.status_code == 422
    assert len(_stored(stored_preferences)) == 1


@pytest.mark.parametrize(
    "method,path",
    [
        ("POST", "/settings/connections/local_server"),
        ("POST", "/settings/connections/local_server/{connection_id}/companion/start"),
        ("POST", "/settings/connections/local_server/{connection_id}/companion/stop"),
        ("PUT", "/settings/connections/local_server/{connection_id}/companion"),
    ],
)
def test_every_local_server_route_is_human_only(method, path):
    rule = classify_route(method, path)

    assert rule is not None and rule.disposition == HUMAN_ONLY
