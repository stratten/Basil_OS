"""Launch preparation for a local server with a background program and secrets, against a real fixture server and real programs."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, Iterator, List

import pytest

from api.core.models.preferences import MCPStdioSpec, Preferences
from api.core.preferences import preferences_io
from api.services.mcp_connectors import local_server_launch
from api.services.mcp_connectors.companion_supervisor import CompanionSupervisor, set_companion_supervisor
from api.services.mcp_connectors.local_server_launch import prepare_stdio_launch
from api.services.mcp_connectors.local_server_registration import register_local_server_record
from api.services.mcp_connectors.local_server_secrets import SecretResolution
from api.services.mcp_connectors.stdio_transport import run_stdio_session

FIXTURE = str(Path(__file__).with_name("stdio_fixture_server.py"))
LISTEN_FOREVER = (
    "import socket, sys, time\n"
    "s = socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)\n"
    "s.bind(('127.0.0.1', int(sys.argv[1]))); s.listen()\n"
    "while True: time.sleep(1)\n"
)
EXIT_AT_ONCE = "raise SystemExit(3)\n"


@pytest.fixture
def stored_preferences(monkeypatch) -> Dict[str, Preferences]:
    holder = {"value": Preferences()}
    monkeypatch.setattr(preferences_io, "load_preferences", lambda: holder["value"].model_copy(deep=True))
    monkeypatch.setattr(preferences_io, "save_preferences", lambda prefs: holder.__setitem__("value", prefs.model_copy(deep=True)))
    return holder


@pytest.fixture
def supervisor(tmp_path, stored_preferences) -> Iterator[CompanionSupervisor]:
    instance = CompanionSupervisor(tmp_path / "local_servers", ready_timeout_seconds=15.0, no_port_grace_seconds=0.3, stop_grace_seconds=3.0)
    set_companion_supervisor(instance)
    yield instance
    set_companion_supervisor(None)


def _secrets(values: Dict[str, str], missing: List[str] | None = None, blocked: str | None = None):
    async def _resolve(connection_id: str, names: Any, *, wait_for_host: bool = False) -> SecretResolution:
        return SecretResolution(values={name: values[name] for name in names if name in values}, missing=list(missing or []), blocked_message=blocked)

    return _resolve


def _register(**overrides: Any):
    fields: Dict[str, Any] = {"friendly_name": "Bridge", "command": sys.executable, "args": [FIXTURE]}
    fields.update(overrides)
    return register_local_server_record(**fields)


@pytest.mark.asyncio
async def test_the_port_is_recorded_for_the_run_and_filled_into_the_server_environment(supervisor, stored_preferences, monkeypatch):
    record = _register(
        env={"FIXTURE_GREETING": "http://127.0.0.1:{port}"},
        companion={"command": sys.executable, "args": ["-c", LISTEN_FOREVER, "{port}"]},
    )
    assert record.stdio is not None
    try:
        prepared = await prepare_stdio_launch(record.stdio, record.id)

        assert prepared.error is None and prepared.parameters is not None
        port = supervisor.snapshot(record.id).port
        assert port is not None
        assert prepared.parameters.env["FIXTURE_GREETING"] == f"http://127.0.0.1:{port}"
    finally:
        await supervisor.stop_all()


@pytest.mark.asyncio
async def test_a_session_reaches_the_server_with_the_port_and_a_keychain_secret_in_its_environment(supervisor, stored_preferences, monkeypatch):
    monkeypatch.setattr(local_server_launch, "resolve_secret_env", _secrets({"BRIDGE_TOKEN": "hello-secret"}))
    record = _register(
        env={"FIXTURE_GREETING": "port-{port}"},
        secret_env=["BRIDGE_TOKEN"],
        companion={"command": sys.executable, "args": ["-c", LISTEN_FOREVER, "{port}"]},
    )
    assert record.stdio is not None
    try:
        async def _op(session):
            await session.initialize()
            result = await session.call_tool("where_am_i", {})
            return result.content[0].text

        text = await run_stdio_session(record.stdio, _op, timeout_seconds=30, envelope_success=False, connection_id=record.id)

        port = supervisor.snapshot(record.id).port
        assert text.endswith(f"|port-{port}")
    finally:
        await supervisor.stop_all()


@pytest.mark.asyncio
async def test_a_secret_declared_by_the_server_alone_is_injected_without_any_background_program(supervisor, stored_preferences, monkeypatch):
    monkeypatch.setattr(local_server_launch, "resolve_secret_env", _secrets({"FIXTURE_GREETING": "from-keychain"}))
    record = _register(secret_env=["FIXTURE_GREETING"])
    assert record.stdio is not None

    prepared = await prepare_stdio_launch(record.stdio, record.id)

    assert prepared.parameters is not None
    assert prepared.parameters.env["FIXTURE_GREETING"] == "from-keychain"
    assert supervisor.snapshot(record.id).status == "stopped"


@pytest.mark.asyncio
async def test_a_background_program_that_will_not_start_returns_an_error_envelope_not_an_exception(supervisor, stored_preferences):
    record = _register(companion={"command": sys.executable, "args": ["-c", EXIT_AT_ONCE]})
    assert record.stdio is not None

    prepared = await prepare_stdio_launch(record.stdio, record.id)

    assert prepared.parameters is None and prepared.error is not None
    assert prepared.error["ok"] is False
    assert "exit code 3" in prepared.error["error"]["message"]


@pytest.mark.asyncio
async def test_missing_secret_values_point_the_person_to_settings(supervisor, stored_preferences, monkeypatch):
    monkeypatch.setattr(local_server_launch, "resolve_secret_env", _secrets({}, missing=["API_KEY"]))
    record = _register(secret_env=["API_KEY"])
    assert record.stdio is not None

    prepared = await prepare_stdio_launch(record.stdio, record.id)

    assert prepared.error is not None
    assert "API_KEY" in prepared.error["error"]["message"]
    assert "Settings" in prepared.error["error"]["user_action_required"]


@pytest.mark.asyncio
async def test_no_connected_app_is_reported_as_such(supervisor, stored_preferences, monkeypatch):
    monkeypatch.setattr(local_server_launch, "resolve_secret_env", _secrets({}, blocked="No Basil client is connected to provide the external service token."))
    record = _register(secret_env=["API_KEY"])
    assert record.stdio is not None

    prepared = await prepare_stdio_launch(record.stdio, record.id)

    assert prepared.error is not None and "No Basil client" in prepared.error["error"]["message"]


@pytest.mark.asyncio
async def test_a_plain_server_still_launches_exactly_as_before_even_with_a_connection_id(supervisor, stored_preferences):
    spec = MCPStdioSpec(command=sys.executable, args=[FIXTURE])

    async def _op(session):
        await session.initialize()
        result = await session.call_tool("echo", {"text": "hi"})
        return result.content[0].text

    text = await run_stdio_session(spec, _op, timeout_seconds=30, envelope_success=False, connection_id="plain-connection")

    assert text == "echo: hi"
    assert supervisor.snapshot("plain-connection").status == "stopped"
