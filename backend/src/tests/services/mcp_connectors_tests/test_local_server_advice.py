"""The advice that tells the agent when a server needs its background program registered as a companion, and that the recommended definition is accepted."""

from __future__ import annotations

import os
import stat
from types import SimpleNamespace

import pytest

from api.services.agent_processing.tools.external_services.external_catalog import actions as external_catalog_actions

from api.services.agent_processing.tools.external_services.external_catalog.local_server_register import unmanaged_background_program_advice
from api.services.mcp_connectors.local_server_spec import build_local_server_spec

SERVER_ARGS = ["--directory", "/Users/someone/mcp/example-server", "run", "main.py"]


def _spec(env=None, args=None, companion=None):
    return build_local_server_spec(command="uv", args=args if args is not None else SERVER_ARGS, cwd=None, env=env or {}, secret_env=None, companion=companion)


def test_advice_names_the_address_and_the_replacement_steps():
    advice = unmanaged_background_program_advice(_spec(env={"EXAMPLE_API_URL": "http://localhost:8080/api"}))
    assert advice is not None
    assert "http://localhost:8080/api" in advice
    assert "arguments.replace" in advice
    assert "Stop the hand-started copy first" in advice
    assert "{port}" in advice and "{run_secret}" in advice
    assert "companion.probe" in advice
    assert "launch agent" in advice


@pytest.mark.parametrize("address", ["http://127.0.0.1:9000", "https://localhost/api", "http://0.0.0.0:3000/x", "http://[::1]:4000", "HTTP://LOCALHOST:8080"])
def test_every_localhost_spelling_is_noticed_in_the_environment(address):
    assert unmanaged_background_program_advice(_spec(env={"BASE_URL": address})) is not None


def test_a_localhost_address_in_the_arguments_is_noticed():
    assert unmanaged_background_program_advice(_spec(args=["run", "main.py", "--api", "http://127.0.0.1:8080/api"])) is not None


@pytest.fixture()
def bridge_folder(tmp_path):
    """A folder holding an executable background program, as the validator requires one that exists."""
    folder = tmp_path / "example-bridge"
    folder.mkdir()
    program = folder / "bridge"
    program.write_text("#!/bin/sh\nexit 0\n")
    os.chmod(program, program.stat().st_mode | stat.S_IXUSR)
    return str(folder)


@pytest.mark.parametrize(
    "env",
    [{}, {"PATH": "/opt/homebrew/bin:/usr/bin"}, {"EXAMPLE_API_URL": "https://api.example.com/v1"}, {"DATABASE_URL": "postgresql://localhost:5432/app"}, {"NOTE": "not localhost.example.com"}],
)
def test_servers_with_nothing_local_to_run_get_no_advice(env):
    assert unmanaged_background_program_advice(_spec(env=env)) is None


def test_a_server_that_already_has_a_companion_gets_no_advice(bridge_folder):
    companion = {"command": f"{bridge_folder}/bridge", "args": [], "cwd": bridge_folder, "env": {"EXAMPLE_PORT": "{port}"}}
    spec = _spec(env={"EXAMPLE_API_URL": "http://127.0.0.1:{port}/api"}, companion=companion)
    assert unmanaged_background_program_advice(spec) is None


def test_no_spec_gets_no_advice():
    assert unmanaged_background_program_advice(None) is None


def test_the_recommended_replacement_is_accepted_by_the_validator(bridge_folder):
    """The definition the advice asks for: the same server command, plus a companion in the folder the program already runs from, a shared port and token, and a status probe."""
    companion = {
        "command": f"{bridge_folder}/bridge",
        "args": [],
        "cwd": bridge_folder,
        "env": {"EXAMPLE_PORT": "{port}", "EXAMPLE_TOKEN": "{run_secret}"},
        "probe": {
            "url": "http://127.0.0.1:{port}/api/connection",
            "auth": "bearer_run_secret",
            "state_path": "state",
            "states": {"connected": "ready", "pairing": "needs_action", "connecting": "starting", "logged_out": "failed"},
            "message_path": "message",
            "action_kind": "qr",
            "action_path": "qrCode",
            "expires_path": "qrExpiresAt",
        },
    }
    spec = _spec(env={"EXAMPLE_API_URL": "http://127.0.0.1:{port}/api", "EXAMPLE_TOKEN": "{run_secret}"}, companion=companion)
    assert spec.companion is not None
    assert spec.companion.cwd == bridge_folder
    assert spec.companion.probe is not None
    assert unmanaged_background_program_advice(spec) is None


def _install_describe(monkeypatch, record):
    prefs = SimpleNamespace(connections=SimpleNamespace(mcp_connections=[record]))

    async def fake_token(connection_id):
        return SimpleNamespace(access_token="tok")

    async def fake_audit(**kwargs):
        return None

    async def fake_schema_guard(*args, **kwargs):
        return None

    class FakeClient:
        async def list_tools(self, server_url, access_token):
            return {"ok": True, "result": {"server": {}, "tools": []}}

    monkeypatch.setattr(external_catalog_actions, "load_external_catalog_preferences", lambda: prefs)
    monkeypatch.setattr(external_catalog_actions, "resolve_external_catalog_access_token", fake_token)
    monkeypatch.setattr(external_catalog_actions, "record_external_catalog_audit", fake_audit)
    monkeypatch.setattr(external_catalog_actions, "get_external_catalog_mcp_client", lambda: FakeClient())
    monkeypatch.setattr(external_catalog_actions, "ensure_tool_schema_surfaced", fake_schema_guard, raising=False)


def _record(spec):
    return SimpleNamespace(
        id="local-1", friendly_name="Example", description=None, server_url="basil-stdio://local-1", enabled=True, cached_tools=[], tool_policies={}, last_connection_status="healthy", stdio=spec
    )


@pytest.mark.asyncio
async def test_describe_server_carries_the_advice_for_an_unmanaged_program(monkeypatch):
    _install_describe(monkeypatch, _record(_spec(env={"EXAMPLE_API_URL": "http://localhost:8080/api"})))
    envelope = await external_catalog_actions.describe_external_catalog_server("local-1")
    assert envelope["ok"] is True
    assert "arguments.replace" in envelope["result"]["advice"]


@pytest.mark.asyncio
async def test_describe_server_has_no_advice_for_an_ordinary_server(monkeypatch):
    _install_describe(monkeypatch, _record(_spec(env={"PATH": "/usr/bin"})))
    envelope = await external_catalog_actions.describe_external_catalog_server("local-1")
    assert envelope["ok"] is True
    assert "advice" not in envelope["result"]


@pytest.mark.asyncio
async def test_describe_server_still_works_for_a_connection_without_a_local_definition(monkeypatch):
    record = _record(None)
    del record.stdio
    _install_describe(monkeypatch, record)
    envelope = await external_catalog_actions.describe_external_catalog_server("local-1")
    assert envelope["ok"] is True
    assert "advice" not in envelope["result"]
