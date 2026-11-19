"""The agent's register_local_server action: validation before approval, the approval card, secrets by name only, start and cleanup."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterator, List

import pytest

from api.core.models.preferences import Preferences
from api.core.preferences import preferences_io
from api.services.agent_processing.tools.external_services import external_catalog_tool
from api.services.agent_processing.tools.external_services.external_catalog import descriptions as catalog_descriptions
from api.services.agent_processing.tools.external_services.external_catalog import local_server_register as register_module
from api.services.agent_processing.tools.external_services.external_catalog.local_server_register import (
    describe_local_server_approval,
    register_external_catalog_local_server as register,
)
from api.services.mcp_connectors.companion_supervisor import CompanionSupervisor, get_companion_supervisor, set_companion_supervisor
from api.services.mcp_connectors.local_server_spec import build_local_server_spec

FIXTURE = str(Path(__file__).with_name("stdio_fixture_server.py"))
LISTEN_FOREVER = (
    "import socket, sys, time\n"
    "s = socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)\n"
    "s.bind(('127.0.0.1', int(sys.argv[1]))); s.listen()\n"
    "while True: time.sleep(1)\n"
)
EXIT_AT_ONCE = "raise SystemExit(3)\n"


class _RecordingApprovalService:
    instances: List["_RecordingApprovalService"] = []
    approve = True

    def __init__(self, websocket_manager=None):
        self.requests: List[tuple] = []
        _RecordingApprovalService.instances.append(self)

    async def request_approval(self, command, context=None):
        self.requests.append((command, dict(context or {})))
        return (_RecordingApprovalService.approve, False, "exact")


@pytest.fixture
def approvals(monkeypatch):
    _RecordingApprovalService.instances = []
    _RecordingApprovalService.approve = True
    monkeypatch.setattr(
        "api.services.agent_processing.tools.safety.execution_approval_service.ExecutionApprovalService",
        _RecordingApprovalService,
    )
    return _RecordingApprovalService


@pytest.fixture
def stored_preferences(monkeypatch) -> Dict[str, Preferences]:
    holder = {"value": Preferences()}
    monkeypatch.setattr(preferences_io, "load_preferences", lambda: holder["value"].model_copy(deep=True))
    monkeypatch.setattr(preferences_io, "save_preferences", lambda prefs: holder.__setitem__("value", prefs.model_copy(deep=True)))
    return holder


@pytest.fixture
def supervisor(tmp_path) -> Iterator[CompanionSupervisor]:
    instance = CompanionSupervisor(tmp_path / "local_servers", ready_timeout_seconds=15.0, no_port_grace_seconds=0.3, stop_grace_seconds=3.0)
    set_companion_supervisor(instance)
    yield instance
    set_companion_supervisor(None)


def _arguments(**overrides: Any) -> Dict[str, Any]:
    arguments: Dict[str, Any] = {"command": sys.executable, "args": [FIXTURE]}
    arguments.update(overrides)
    return arguments


def _stored(holder: Dict[str, Preferences]) -> List[Any]:
    return holder["value"].connections.mcp_connections


def _requests(approvals) -> List[tuple]:
    return [request for instance in approvals.instances for request in instance.requests]


@pytest.mark.asyncio
async def test_a_plain_server_is_approved_registered_started_and_its_tools_are_listed(approvals, stored_preferences, supervisor):
    result = await register(_arguments(source_url="https://example.com/readme"), "  Fixture   server ", "Test fixture")

    assert result["ok"] is True, result
    body = result["result"]
    assert body["status"] == "connected"
    assert body["service"] == "Fixture server"
    assert {"echo", "where_am_i"} <= set(body["tool_names"])
    assert body["tool_count"] == len(body["tool_names"])
    stored = _stored(stored_preferences)
    assert len(stored) == 1
    assert stored[0].id == body["connection_id"]
    assert stored[0].description == "Test fixture"
    assert stored[0].stdio.source_url == "https://example.com/readme"
    command, context = _requests(approvals)[0]
    assert command.startswith('register-local-mcp-server "Fixture server"')
    assert FIXTURE in command
    assert context["require_explicit_approval"] is True
    assert context["execution_type"] == "mcp_connection_setup"
    assert context["source"] == register_module.REGISTER_APPROVAL_SOURCE
    assert context["purpose_source"] == "basil"
    assert FIXTURE in context["purpose"]
    assert context["purpose"].endswith("Nothing starts until you approve.")


@pytest.mark.asyncio
async def test_a_server_with_a_background_program_shares_the_port_and_leaves_the_program_running(approvals, stored_preferences, supervisor):
    arguments = _arguments(
        env={"FIXTURE_GREETING": "port-{port}"},
        companion={"command": sys.executable, "args": ["-c", LISTEN_FOREVER, "{port}"]},
    )
    try:
        result = await register(arguments, "Bridge server")

        assert result["ok"] is True, result
        snapshot = get_companion_supervisor().snapshot(result["result"]["connection_id"])
        assert snapshot.running is True
        assert snapshot.port is not None
        _command, context = _requests(approvals)[0]
        assert "background program" in context["purpose"]
        assert "whenever Basil is open" in context["purpose"]
    finally:
        await supervisor.stop_all()


@pytest.mark.asyncio
async def test_a_server_that_needs_secrets_is_saved_but_not_started(approvals, stored_preferences, supervisor, monkeypatch):
    async def must_not_run(connection_id):
        raise AssertionError("a server that is waiting for secrets must not be launched")

    monkeypatch.setattr(register_module, "_refresh_connection", must_not_run)
    arguments = _arguments(secret_env=["API_KEY"], companion={"command": sys.executable, "args": ["-c", LISTEN_FOREVER, "{port}"], "secret_env": ["BRIDGE_TOKEN", "API_KEY"]}, env={"FIXTURE_GREETING": "port-{port}"})

    result = await register(arguments, "Needs keys")

    assert result["ok"] is True, result
    body = result["result"]
    assert body["status"] == "awaiting_secrets"
    assert body["secret_names"] == ["API_KEY", "BRIDGE_TOKEN"]
    assert "Settings → Connections" in body["message"]
    assert "You never see the values" in body["message"]
    stored = _stored(stored_preferences)
    assert [record.id for record in stored] == [body["connection_id"]]
    assert stored[0].stdio.secret_env == ["API_KEY"]
    assert get_companion_supervisor().snapshot(body["connection_id"]).running is False
    _command, context = _requests(approvals)[0]
    assert "API_KEY" in context["purpose"] and "BRIDGE_TOKEN" in context["purpose"]
    assert "Keychain" in context["purpose"]


@pytest.mark.asyncio
async def test_a_denied_approval_stores_and_starts_nothing(approvals, stored_preferences, supervisor):
    approvals.approve = False

    result = await register(_arguments(), "Denied")

    assert result["ok"] is False
    assert result["error"]["kind"] == "permission_denied"
    assert _stored(stored_preferences) == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "arguments",
    [
        None,
        {},
        "not an object",
        _arguments(extra="x"),
        _arguments(friendly_name="Inside"),
        {"args": [FIXTURE]},
        _arguments(command=5),
        _arguments(args="one string"),
        _arguments(args=[FIXTURE, 3]),
        _arguments(cwd=7),
        _arguments(env=["A=1"]),
        _arguments(env={"A": 1}),
        _arguments(source_url=5),
        _arguments(source_url="x" * 501),
        _arguments(secret_env="API_KEY"),
        _arguments(secret_env=["1BAD"]),
        _arguments(env={"API_KEY": "abc"}),
        _arguments(env={"github_token": "abc"}),
        _arguments(env={"DB_PASSWORD": "abc"}),
        _arguments(companion={"command": sys.executable, "args": ["-c", LISTEN_FOREVER, "{port}"], "env": {"BRIDGE_SECRET": "abc"}}),
        _arguments(companion="run it"),
        _arguments(env={"X": "{run_secret}"}),
        _arguments(env={"X": "{port}"}),
        _arguments(command="/no/such/program"),
    ],
)
async def test_an_unusable_definition_is_refused_before_the_user_is_asked(arguments, approvals, stored_preferences, supervisor):
    result = await register(arguments, "Refused")

    assert result["ok"] is False
    assert result["error"]["kind"] == "invalid_arguments"
    assert approvals.instances == []
    assert _stored(stored_preferences) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("name,description", [(None, None), ("", None), ("   ", None), ("n" * 81, None), ("Fine", "d" * 501)])
async def test_a_missing_or_overlong_name_or_description_is_refused_before_the_user_is_asked(name, description, approvals, stored_preferences, supervisor):
    result = await register(_arguments(), name, description)

    assert result["ok"] is False
    assert result["error"]["kind"] == "invalid_arguments"
    assert approvals.instances == []


@pytest.mark.asyncio
async def test_a_credential_like_name_is_refused_with_the_instruction_to_use_secret_env(approvals, stored_preferences, supervisor):
    result = await register(_arguments(env={"API_KEY": "sk-should-not-be-here"}), "Leaky")

    message = result["error"]["message"]
    assert "secret_env" in message
    assert "API_KEY" in message
    assert "sk-should-not-be-here" not in message


@pytest.mark.asyncio
async def test_a_name_that_only_contains_a_credential_word_in_the_middle_is_a_plain_setting(approvals, stored_preferences, supervisor):
    result = await register(_arguments(env={"TOKENIZERS_PARALLELISM": "false", "KEYBOARD_LAYOUT": "us"}), "Plain settings")

    assert result["ok"] is True, result
    assert _stored(stored_preferences)[0].stdio.env == {"TOKENIZERS_PARALLELISM": "false", "KEYBOARD_LAYOUT": "us"}


@pytest.mark.asyncio
async def test_a_server_that_is_already_set_up_is_reported_without_asking_again(approvals, stored_preferences, supervisor):
    first = await register(_arguments(), "First")
    asked = len(_requests(approvals))

    second = await register(_arguments(), "Second name, same command")

    assert first["result"]["status"] == "connected"
    assert second["ok"] is True
    assert second["result"]["status"] == "already_connected"
    assert second["result"]["connection_id"] == first["result"]["connection_id"]
    assert len(_requests(approvals)) == asked
    assert len(_stored(stored_preferences)) == 1


@pytest.mark.asyncio
async def test_a_program_that_cannot_start_is_removed_and_the_reason_is_reported(approvals, stored_preferences, supervisor):
    result = await register({"command": sys.executable, "args": ["-c", "raise SystemExit(1)"]}, "Broken")

    assert result["ok"] is False
    error = result["error"]
    assert error["kind"] == "connection_setup_failed"
    assert error["retryable"] is False
    assert "Nothing was kept" in error["message"]
    assert _stored(stored_preferences) == []


@pytest.mark.asyncio
async def test_a_background_program_that_exits_at_once_removes_the_server_and_names_the_exit_code(approvals, stored_preferences, supervisor):
    result = await register(_arguments(companion={"command": sys.executable, "args": ["-c", EXIT_AT_ONCE, "{port}"]}), "Bad bridge")

    assert result["ok"] is False
    assert result["error"]["kind"] == "connection_setup_failed"
    assert "exit code 3" in result["error"]["message"]
    assert _stored(stored_preferences) == []


@pytest.mark.asyncio
async def test_a_canceled_task_removes_what_it_just_registered(approvals, stored_preferences, supervisor, monkeypatch):
    async def canceled(connection_id):
        raise asyncio.CancelledError()

    monkeypatch.setattr(register_module, "_refresh_connection", canceled)

    with pytest.raises(asyncio.CancelledError):
        await register(_arguments(), "Canceled")

    assert _stored(stored_preferences) == []


def test_the_card_shows_every_part_of_the_definition_and_clips_a_very_long_setting():
    long_value = "v" * 200
    spec = build_local_server_spec(
        command=sys.executable,
        args=[FIXTURE, "two words"],
        cwd=str(Path(FIXTURE).parent),
        env={"MODE": long_value},
        secret_env=["API_KEY"],
        companion={"command": sys.executable, "args": ["-c", "import time; time.sleep(5)"], "start_with_basil": False, "fixed_port": 9123},
    )

    text = describe_local_server_approval("Example", spec)

    assert "'two words'" in text
    assert str(Path(FIXTURE).parent) in text
    assert "MODE=" + "v" * register_module.MAX_SHOWN_SETTING_VALUE + "…" in text
    assert long_value not in text
    assert "API_KEY" in text and "Keychain" in text
    assert "the first time the server is used" in text
    assert "on port 9123" in text


@pytest.mark.asyncio
async def test_the_tool_dispatches_the_action_and_the_schema_and_description_teach_it(monkeypatch):
    seen: Dict[str, Any] = {}

    async def fake(arguments, friendly_name, description):
        seen.update(arguments=arguments, friendly_name=friendly_name, description=description)
        return {"ok": True, "result": {"status": "connected"}}

    monkeypatch.setattr(external_catalog_tool, "_register_local_server", fake)
    raw = await external_catalog_tool._external_catalog_impl(
        action="register_local_server", arguments={"command": "x"}, friendly_name="Name", description="Note"
    )

    assert json.loads(raw)["result"]["status"] == "connected"
    assert seen == {"arguments": {"command": "x"}, "friendly_name": "Name", "description": "Note"}
    properties = external_catalog_tool.ExternalCatalogInput.model_json_schema()["properties"]
    assert "register_local_server" in properties["action"]["enum"]
    assert "register_local_server" in properties["action"]["description"]
    assert "secret_env" in properties["arguments"]["description"]
    full = catalog_descriptions.build_full_external_catalog_description("**CURRENT CONNECTIONS:** none")
    for fragment in ("action='register_local_server'", "secret_env", "{port}", "awaiting_secrets", "you never see it", "Never guess a command"):
        assert fragment in full
    assert len(catalog_descriptions.SLIM_DESCRIPTION) < 2_100


@pytest.mark.asyncio
async def test_the_catalog_tool_runs_the_action_end_to_end(approvals, stored_preferences, supervisor):
    tool = external_catalog_tool.create_external_catalog_tool()

    raw = await tool.coroutine(action="register_local_server", friendly_name="Through the tool", arguments=_arguments())

    assert json.loads(raw)["result"]["status"] == "connected"
    assert len(_stored(stored_preferences)) == 1
