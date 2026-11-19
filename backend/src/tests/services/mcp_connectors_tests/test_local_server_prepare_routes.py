"""The prepare, cancel, install-requirement and status routes, the install section of the connection response, and what registering a server with a recipe does."""

from __future__ import annotations

import hashlib
import sys
import time
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
from api.routes.connections.routes import router
from api.services.app_control.route_classification import HUMAN_ONLY, classify_route
from api.services.mcp_connectors.companion_supervisor import CompanionSupervisor, set_companion_supervisor
from api.services.mcp_connectors.local_server_commands import CommandResult
from api.services.mcp_connectors.local_server_prepare import LocalServerPreparer, set_local_server_preparer

FIXTURE = str(Path(__file__).with_name("stdio_fixture_server.py"))
BASE = "/settings/connections"
PROGRAM = (
    f"#!{sys.executable}\n"
    "import socket, sys, time\n"
    "s = socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)\n"
    "s.bind(('127.0.0.1', int(sys.argv[1]))); s.listen()\n"
    "while True: time.sleep(1)\n"
).encode()
PROGRAM_SHA = hashlib.sha256(PROGRAM).hexdigest()
URL = "https://example.test/releases/bridge"


class _FakeCallLog:
    async def delete_for_connection(self, connection_id: str) -> None:
        return None


class _FakeKnowledge:
    mcp_call_log_repository = _FakeCallLog()


class World:
    """What the fake Mac has installed and what the fake download serves."""

    def __init__(self) -> None:
        self.installed = False
        self.commands: List[List[str]] = []
        self.downloads: List[str] = []

    async def run(self, argv, **kwargs: Any) -> CommandResult:
        self.commands.append(list(argv))
        if argv[0] == "xtool":
            return CommandResult(0 if self.installed else 127, "")
        if argv[0] == "xinstall":
            self.installed = True
        return CommandResult(0, "")

    async def download(self, url: str, destination: Path, **kwargs: Any) -> str:
        self.downloads.append(url)
        destination.write_bytes(PROGRAM)
        return PROGRAM_SHA


@pytest.fixture
def world() -> World:
    return World()


@pytest.fixture
def stored_preferences(monkeypatch) -> Dict[str, Preferences]:
    holder = {"value": Preferences()}
    monkeypatch.setattr(preferences_io, "load_preferences", lambda: holder["value"].model_copy(deep=True))
    monkeypatch.setattr(preferences_io, "save_preferences", lambda prefs: holder.__setitem__("value", prefs.model_copy(deep=True)))
    return holder


@pytest.fixture
def client(tmp_path, stored_preferences, world) -> Iterator[TestClient]:
    supervisor = CompanionSupervisor(tmp_path / "local_servers", ready_timeout_seconds=15.0, no_port_grace_seconds=0.3, stop_grace_seconds=3.0)
    set_companion_supervisor(supervisor)
    set_local_server_preparer(LocalServerPreparer(run=world.run, download=world.download))
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_host_credential] = lambda: None
    app.dependency_overrides[get_sqlite_knowledge_service] = lambda: _FakeKnowledge()
    with TestClient(app) as test_client:
        yield test_client
        test_client.portal.call(supervisor.stop_all)
    set_local_server_preparer(None)
    set_companion_supervisor(None)


def _install(**overrides: Any) -> Dict[str, Any]:
    recipe: Dict[str, Any] = {
        "requirements": [{"name": "Xtool", "reason": "The bridge needs it.", "check": ["xtool"], "install": ["xinstall", "xtool"], "for_method": "any"}],
        "artifacts": [{"name": "Bridge", "expects": "bin/bridge", "methods": [{"kind": "download", "url": URL, "sha256": PROGRAM_SHA}]}],
    }
    recipe.update(overrides)
    return recipe


def _body(**overrides: Any) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "friendly_name": "Recipe server",
        "command": sys.executable,
        "args": [FIXTURE],
        "companion": {"command": "{install_dir}/bin/bridge", "args": ["{port}"]},
        "install": _install(),
        "connection_id": str(uuid.uuid4()),
    }
    body.update(overrides)
    return body


def _eventually(check, timeout: float = 15.0) -> Any:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = check()
        if value:
            return value
        time.sleep(0.05)
    raise AssertionError("the condition never became true")


def _install_of(client: TestClient, connection_id: str) -> Dict[str, Any]:
    return client.get(f"{BASE}/local_server/{connection_id}/status").json()["local_server"]["install"]


def test_registering_a_server_with_a_recipe_stores_it_and_waits_for_the_person_to_prepare_it(client, stored_preferences, world):
    body = _body()

    response = client.post(f"{BASE}/local_server", json=body)

    assert response.status_code == 200, response.text
    local = response.json()["local_server"]
    assert local["companion"]["status"] == "stopped" and response.json()["tools"] == []
    install = local["install"]
    assert (install["phase"], install["ready"], install["active"]) == ("idle", False, False)
    assert install["requirements"] == [{"name": "Xtool", "reason": "The bridge needs it.", "for_method": "any", "install_command": "xinstall xtool"}]
    assert install["artifacts"][0]["ready"] is False
    assert install["artifacts"][0]["sources"] == [f"Download {URL} (SHA-256 {PROGRAM_SHA})"]
    assert len(stored_preferences["value"].connections.mcp_connections) == 1
    assert world.downloads == [] and world.commands == []


def test_a_recipe_the_backend_refuses_stores_nothing(client, stored_preferences):
    bad = _install(artifacts=[{"name": "Bridge", "expects": "../escape", "methods": [{"kind": "download", "url": "http://plain.test/x", "sha256": PROGRAM_SHA}]}])

    response = client.post(f"{BASE}/local_server", json=_body(install=bad))

    assert response.status_code == 422
    assert stored_preferences["value"].connections.mcp_connections == []


def test_preparing_stops_for_a_requirement_then_continues_and_starts_the_background_program(client, world):
    connection_id = client.post(f"{BASE}/local_server", json=_body()).json()["id"]

    started = client.post(f"{BASE}/local_server/{connection_id}/prepare")
    assert started.status_code == 200

    waiting = _eventually(lambda: (lambda install: install if install["phase"] == "needs_requirement" else None)(_install_of(client, connection_id)))
    assert (waiting["requirement"], waiting["can_install"]) == ("Xtool", True)
    assert world.downloads == [] and ["xinstall", "xtool"] not in world.commands

    wrong = client.post(f"{BASE}/local_server/{connection_id}/requirements/install", json={"name": "Xtool", "command": "xinstall something-else"})
    assert wrong.status_code == 409 and "not the one in this server's recipe" in wrong.json()["detail"]
    assert ["xinstall", "xtool"] not in world.commands
    unknown = client.post(f"{BASE}/local_server/{connection_id}/requirements/install", json={"name": "Nope", "command": "xinstall xtool"})
    assert unknown.status_code == 409

    installing = client.post(f"{BASE}/local_server/{connection_id}/requirements/install", json={"name": "Xtool", "command": "xinstall xtool"})
    assert installing.status_code == 200
    _eventually(lambda: _install_of(client, connection_id)["phase"] == "idle" and world.installed)

    client.post(f"{BASE}/local_server/{connection_id}/prepare")
    ready = _eventually(lambda: (lambda install: install if install["phase"] == "ready" else None)(_install_of(client, connection_id)))
    assert ready["ready"] is True and ready["artifacts"][0]["ready"] is True

    running = _eventually(lambda: (lambda local: local if local["companion"]["status"] == "running" else None)(client.get(f"{BASE}/local_server/{connection_id}/status").json()["local_server"]))
    assert running["companion"]["port"] is not None


def test_preparing_again_once_everything_is_in_place_downloads_nothing_new_and_keeps_the_program_running(client, world):
    world.installed = True
    first = client.post(f"{BASE}/local_server", json=_body()).json()["id"]
    client.post(f"{BASE}/local_server/{first}/prepare")
    _eventually(lambda: _install_of(client, first)["ready"])
    again = client.post(f"{BASE}/local_server/{first}/prepare")

    assert again.status_code == 200
    assert world.downloads == [URL]
    assert _eventually(lambda: client.get(f"{BASE}/local_server/{first}/status").json()["local_server"]["companion"]["status"] == "running")


def test_cancel_returns_the_connection_and_leaves_it_unprepared(client, world):
    connection_id = client.post(f"{BASE}/local_server", json=_body()).json()["id"]
    client.post(f"{BASE}/local_server/{connection_id}/prepare")
    _eventually(lambda: _install_of(client, connection_id)["phase"] == "needs_requirement")

    response = client.post(f"{BASE}/local_server/{connection_id}/prepare/cancel")

    assert response.status_code == 200 and _install_of(client, connection_id)["ready"] is False


def test_the_routes_refuse_a_server_without_a_recipe_and_an_unknown_server(client):
    plain = client.post(f"{BASE}/local_server", json={"friendly_name": "Plain", "command": sys.executable, "args": [FIXTURE, "plain"]}).json()
    assert plain["local_server"]["install"] is None

    for path, kwargs in (
        (f"{BASE}/local_server/{plain['id']}/prepare", {}),
        (f"{BASE}/local_server/{plain['id']}/prepare/cancel", {}),
        (f"{BASE}/local_server/{plain['id']}/requirements/install", {"json": {"name": "X", "command": "x"}}),
    ):
        assert client.post(path, **kwargs).status_code == 409, path
    assert client.get(f"{BASE}/local_server/{plain['id']}/status").status_code == 200
    assert client.get(f"{BASE}/local_server/{uuid.uuid4()}/status").status_code == 404
    assert client.post(f"{BASE}/local_server/{uuid.uuid4()}/prepare").status_code == 404


def test_removing_a_prepared_server_deletes_its_files(client, world, tmp_path):
    world.installed = True
    connection_id = client.post(f"{BASE}/local_server", json=_body()).json()["id"]
    client.post(f"{BASE}/local_server/{connection_id}/prepare")
    _eventually(lambda: _install_of(client, connection_id)["ready"])
    folder = tmp_path / "local_servers" / "connections" / connection_id
    assert (folder / "install" / "bin" / "bridge").exists()

    assert client.delete(f"{BASE}/{connection_id}").status_code == 200

    assert not folder.exists()


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/settings/connections/local_server/{connection_id}/status"),
        ("POST", "/settings/connections/local_server/{connection_id}/prepare"),
        ("POST", "/settings/connections/local_server/{connection_id}/prepare/cancel"),
        ("POST", "/settings/connections/local_server/{connection_id}/requirements/install"),
    ],
)
def test_every_new_local_server_route_is_human_only(method, path):
    rule = classify_route(method, path)

    assert rule is not None and rule.disposition == HUMAN_ONLY
