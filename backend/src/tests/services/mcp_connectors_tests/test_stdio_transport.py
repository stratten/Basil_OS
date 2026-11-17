"""The local stdio MCP transport: launch parameters, a real session against a fixture server, the deadline, and process cleanup."""

from __future__ import annotations

import os
import stat
import sys
import time
from pathlib import Path

import pytest

from api.core.models.preferences import MCPStdioSpec
from api.services.mcp_connectors import stdio_transport
from api.services.mcp_connectors.mcp_client_service import MCPClientService
from api.services.mcp_connectors.stdio_transport import (
    StdioSpecError,
    build_parameters,
    connection_id_from_url,
    is_stdio_url,
    resolve_command,
    search_path,
    stdio_server_url,
    validate_spec_fields,
)

FIXTURE = str(Path(__file__).with_name("stdio_fixture_server.py"))


def _spec(**overrides) -> MCPStdioSpec:
    values = dict(command=sys.executable, args=[FIXTURE])
    values.update(overrides)
    return MCPStdioSpec(**values)


@pytest.fixture
def client_with_spec(monkeypatch):
    """A client whose stdio connection `basil-stdio://fixture` resolves to the spec a test sets."""
    holder = {"spec": _spec()}
    from api.services.mcp_connectors import mcp_client_service

    monkeypatch.setattr(mcp_client_service, "load_stdio_spec", lambda url: holder["spec"])
    return MCPClientService(default_timeout_seconds=20.0), holder


def test_the_sentinel_url_round_trips_the_connection_id():
    url = stdio_server_url("abc-123")

    assert url == "basil-stdio://abc-123"
    assert is_stdio_url(url) and not is_stdio_url("https://example.com/mcp")
    assert connection_id_from_url(url) == "abc-123"


def test_search_path_keeps_existing_entries_first_and_adds_the_usual_install_folders_once():
    path = search_path("/usr/bin:/bin")

    entries = path.split(os.pathsep)
    assert entries[:2] == ["/usr/bin", "/bin"]
    assert "/opt/homebrew/bin" in entries and entries.count("/opt/homebrew/bin") == 1
    assert search_path(path) == path


def test_resolve_command_finds_names_on_path_and_checks_absolute_paths(tmp_path):
    tool = tmp_path / "mytool"
    tool.write_text("#!/bin/sh\n")
    tool.chmod(tool.stat().st_mode | stat.S_IXUSR)

    assert resolve_command("mytool", str(tmp_path)) == str(tool)
    assert resolve_command(str(tool), "") == str(tool)
    with pytest.raises(StdioSpecError, match="could not find a program named 'nothing-here'"):
        resolve_command("nothing-here", str(tmp_path))
    with pytest.raises(StdioSpecError, match="not an executable file"):
        resolve_command(str(tmp_path / "missing"), "")
    with pytest.raises(StdioSpecError, match="absolute path"):
        resolve_command("./relative/tool", "")
    with pytest.raises(StdioSpecError, match="empty"):
        resolve_command("   ", "")


def test_build_parameters_passes_arguments_without_a_shell_and_merges_environment(tmp_path):
    spec = _spec(args=["-c", "a b; rm -rf /"], cwd=str(tmp_path), env={"FIXTURE_GREETING": "hi"})

    parameters = build_parameters(spec, base_env={"PATH": "/usr/bin"})

    assert parameters.command == sys.executable
    assert parameters.args == ["-c", "a b; rm -rf /"]
    assert parameters.cwd == str(tmp_path)
    assert parameters.env["FIXTURE_GREETING"] == "hi"
    assert "/opt/homebrew/bin" in parameters.env["PATH"]


def test_build_parameters_rejects_a_missing_folder():
    with pytest.raises(StdioSpecError, match="does not exist"):
        build_parameters(_spec(cwd="/no/such/folder"), base_env={"PATH": "/usr/bin"})


@pytest.mark.parametrize(
    "command, args, env, fragment",
    [
        ("", [], {}, "needs a command"),
        ("python\nrm", [], {}, "line breaks"),
        (sys.executable, ["ok\0bad"], {}, "null characters"),
        (sys.executable, [], {"A=B": "x"}, "equals sign"),
    ],
)
def test_validate_spec_fields_rejects_unusable_input(command, args, env, fragment):
    with pytest.raises(StdioSpecError, match=fragment):
        validate_spec_fields(command, args, None, env)


def test_validate_spec_fields_returns_a_trimmed_spec():
    spec = validate_spec_fields(f"  {sys.executable}  ", [FIXTURE], "  ", {"K": "v"})

    assert spec.command == sys.executable and spec.cwd is None and spec.env == {"K": "v"}


@pytest.mark.asyncio
async def test_a_real_stdio_server_lists_and_calls_tools(client_with_spec):
    client, _holder = client_with_spec

    listed = await client.list_tools("basil-stdio://fixture")
    called = await client.call_tool("basil-stdio://fixture", "echo", {"text": "hello"})

    assert listed["ok"] is True
    assert listed["result"]["server"]["name"] == "basil-stdio-fixture"
    assert {tool["name"] for tool in listed["result"]["tools"]} >= {"echo", "where_am_i", "sleep_forever"}
    assert called["ok"] is True
    assert "echo: hello" in str(called["result"])


@pytest.mark.asyncio
async def test_the_server_runs_in_the_folder_with_the_environment_it_was_given(client_with_spec, tmp_path):
    client, holder = client_with_spec
    holder["spec"] = _spec(cwd=str(tmp_path), env={"FIXTURE_GREETING": "hello-from-spec"})

    called = await client.call_tool("basil-stdio://fixture", "where_am_i", {})

    assert called["ok"] is True
    assert str(tmp_path.resolve()) in str(called["result"]) or str(tmp_path) in str(called["result"])
    assert "hello-from-spec" in str(called["result"])


@pytest.mark.asyncio
async def test_a_missing_command_is_a_plain_error_that_names_the_fix(client_with_spec):
    client, holder = client_with_spec
    holder["spec"] = _spec(command="definitely-not-installed-xyz")

    result = await client.list_tools("basil-stdio://fixture")

    assert result["ok"] is False
    assert "cannot start" in result["error"]["message"]
    assert "could not find a program" in result["error"]["message"]
    assert result["error"]["user_action_required"]


@pytest.mark.asyncio
async def test_a_server_that_exits_at_once_reports_what_it_said(client_with_spec):
    client, holder = client_with_spec
    holder["spec"] = _spec(args=["-c", "import sys; sys.stderr.write('boom: missing config'); sys.exit(3)"])

    result = await client.list_tools("basil-stdio://fixture")

    assert result["ok"] is False
    assert "boom: missing config" in result["error"]["message"]


@pytest.mark.asyncio
async def test_a_stored_connection_that_no_longer_exists_is_a_clear_error(monkeypatch):
    from api.services.mcp_connectors import mcp_client_service

    monkeypatch.setattr(mcp_client_service, "load_stdio_spec", lambda url: None)

    result = await MCPClientService().list_tools("basil-stdio://gone")

    assert result["ok"] is False
    assert "no longer set up" in result["error"]["message"]


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


@pytest.mark.asyncio
async def test_the_deadline_stops_a_stuck_call_and_the_process_is_gone_afterwards(client_with_spec, tmp_path):
    client, holder = client_with_spec
    pid_file = tmp_path / "pid"
    holder["spec"] = _spec(env={"FIXTURE_PID_FILE": str(pid_file)})

    started = time.monotonic()
    result = await client.call_tool("basil-stdio://fixture", "sleep_forever", {}, timeout_seconds=3.0)
    elapsed = time.monotonic() - started

    assert result["ok"] is False and result["error"]["kind"] == "timeout"
    assert elapsed < 15
    pid = int(pid_file.read_text())
    for _ in range(50):
        if not _alive(pid):
            break
        time.sleep(0.1)
    assert not _alive(pid)


@pytest.mark.asyncio
async def test_the_process_is_gone_after_a_normal_call(client_with_spec, tmp_path):
    client, holder = client_with_spec
    pid_file = tmp_path / "pid"
    holder["spec"] = _spec(env={"FIXTURE_PID_FILE": str(pid_file)})

    await client.call_tool("basil-stdio://fixture", "echo", {"text": "x"})

    pid = int(pid_file.read_text())
    for _ in range(50):
        if not _alive(pid):
            break
        time.sleep(0.1)
    assert not _alive(pid)


@pytest.mark.asyncio
async def test_the_token_bridge_answers_a_stdio_connection_with_a_placeholder_and_never_asks_swift(monkeypatch):
    from api.core.models.preferences import MCPConnectionRecord, Preferences
    from api.services.mcp_connectors import swift_token_bridge

    record = MCPConnectionRecord(friendly_name="Local", server_url="basil-stdio://x", stdio=_spec())
    record.server_url = stdio_server_url(record.id)
    prefs = Preferences()
    prefs.connections.mcp_connections = [record]
    monkeypatch.setattr("api.core.preferences.preferences_io.load_preferences", lambda: prefs)

    async def must_not_ask(**kwargs):
        raise AssertionError("Keychain must not be asked for a stdio connection")

    monkeypatch.setattr(swift_token_bridge, "_ask_swift_for_credentials", must_not_ask)

    outcome = await swift_token_bridge._request_access_token_from_swift(record.id)

    assert outcome.kind == "token_available"
    assert outcome.access_token == stdio_transport.STDIO_PLACEHOLDER_TOKEN
