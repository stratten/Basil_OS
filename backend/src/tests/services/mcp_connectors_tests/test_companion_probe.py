"""The health probe: reading a program's own status page, the per-run token, redaction, restarts, and the gate in front of the server."""

from __future__ import annotations

import asyncio
import contextlib
import http.server
import json
import os
import signal
import sys
import threading
from pathlib import Path
from typing import Any, AsyncIterator, Callable, Dict, Iterator, Optional

import pytest

from api.core.models.preferences import MCPProbeSpec, Preferences
from api.core.preferences import preferences_io
from api.services.mcp_connectors import local_server_launch
from api.services.mcp_connectors.companion_probe import (
    ProbeMonitor,
    ProbeReading,
    ProbeUnavailable,
    interpret,
    read_probe,
    value_at,
)
from api.services.mcp_connectors.companion_supervisor import CompanionSupervisor, set_companion_supervisor
from api.services.mcp_connectors.local_server_launch import prepare_stdio_launch
from api.services.mcp_connectors.local_server_redaction import redact_secrets
from api.services.mcp_connectors.local_server_registration import register_local_server_record

FIXTURE = str(Path(__file__).with_name("stdio_fixture_server.py"))

FAKE_BRIDGE = """
import http.server, json, os, socketserver, sys
port, state_file, token = int(sys.argv[1]), sys.argv[2], os.environ["BRIDGE_TOKEN"]
class Server(http.server.ThreadingHTTPServer):
    def server_bind(self):
        socketserver.TCPServer.server_bind(self)
        self.server_port = self.server_address[1]
class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args): pass
    def do_GET(self):
        if self.headers.get("Authorization") != "Bearer " + token:
            self.send_response(401); self.end_headers(); return
        body = open(state_file, "rb").read()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(body)
print("the token is " + token, flush=True)
Server(("127.0.0.1", port), Handler).serve_forever()
"""

PROBE: Dict[str, Any] = {
    "url": "http://127.0.0.1:{port}/api/connection",
    "auth": "bearer_run_secret",
    "state_path": "state",
    "states": {"connected": "ready", "pairing": "needs_action", "connecting": "starting", "error": "failed"},
    "message_path": "message",
    "action_kind": "qr",
    "action_path": "qrCode",
    "expires_path": "qrExpiresAt",
}


async def _fast_sleep(_seconds: float) -> None:
    await asyncio.sleep(0.05)


async def _eventually(predicate: Callable[[], bool], timeout: float = 15.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.05)
    raise AssertionError("the condition never became true")


def _spec(**overrides: Any) -> MCPProbeSpec:
    return MCPProbeSpec(**{**PROBE, **overrides})


def test_value_at_walks_dotted_paths_and_list_indexes_and_returns_none_for_anything_missing():
    data = {"a": {"b": [{"c": 5}]}, "flag": False}

    assert value_at(data, "a.b.0.c") == 5
    assert value_at(data, "flag") is False
    for missing in ("a.x", "a.b.1", "a.b.zero", "nope", "a.b.0.c.d"):
        assert value_at(data, missing) is None


def test_interpret_maps_states_and_only_reports_an_action_while_the_person_is_needed():
    spec = _spec()

    waiting = interpret(spec, {"state": "pairing", "message": "Scan the code.", "qrCode": "ABC", "qrExpiresAt": "2026-01-01T00:00:00Z"})
    assert (waiting.phase, waiting.message, waiting.action_kind, waiting.action_value) == ("needs_action", "Scan the code.", "qr", "ABC")
    assert waiting.action_expires_at == "2026-01-01T00:00:00Z"

    ready = interpret(spec, {"state": "connected", "qrCode": "STALE"})
    assert ready.phase == "ready" and ready.action_value is None and ready.action_kind is None

    assert interpret(spec, {"state": "something-new"}).phase == "starting"
    assert interpret(spec, {}).phase == "starting"
    assert interpret(spec, {"state": "pairing"}).action_value is None
    assert interpret(spec, {"state": "error", "message": "x" * 1000}).message == "x" * 300


@contextlib.contextmanager
def _serve(handler_factory: Callable[[], Callable[[http.server.BaseHTTPRequestHandler], None]]) -> Iterator[int]:
    handle = handler_factory()

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args: Any) -> None:
            pass

        def do_GET(self) -> None:
            handle(self)

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()


def _json_reply(request: http.server.BaseHTTPRequestHandler, status: int, body: bytes) -> None:
    request.send_response(status)
    request.send_header("Content-Type", "application/json")
    request.end_headers()
    request.wfile.write(body)


@pytest.mark.asyncio
async def test_read_probe_sends_the_bearer_token_and_accepts_a_json_body_on_an_error_status():
    seen: Dict[str, str] = {}

    def factory():
        def handle(request):
            seen["authorization"] = request.headers.get("Authorization", "")
            _json_reply(request, 503, json.dumps({"state": "connecting", "message": "Connecting"}).encode())

        return handle

    with _serve(factory) as port:
        reading = await read_probe(_spec(), port=port, run_secret="run-token", secrets={})

    assert seen["authorization"] == "Bearer run-token"
    assert (reading.phase, reading.message) == ("starting", "Connecting")


@pytest.mark.asyncio
async def test_read_probe_can_authenticate_with_a_declared_secret():
    seen: Dict[str, str] = {}

    def factory():
        def handle(request):
            seen["authorization"] = request.headers.get("Authorization", "")
            _json_reply(request, 200, b'{"state": "connected"}')

        return handle

    with _serve(factory) as port:
        reading = await read_probe(_spec(auth="bearer_secret", secret_name="BRIDGE_TOKEN"), port=port, run_secret=None, secrets={"BRIDGE_TOKEN": "typed-value"})

    assert seen["authorization"] == "Bearer typed-value" and reading.phase == "ready"


@pytest.mark.asyncio
async def test_read_probe_sends_no_authorization_when_none_is_configured():
    seen: Dict[str, Optional[str]] = {}

    def factory():
        def handle(request):
            seen["authorization"] = request.headers.get("Authorization")
            _json_reply(request, 200, b'{"state": "connected"}')

        return handle

    with _serve(factory) as port:
        await read_probe(_spec(auth="none"), port=port, run_secret="ignored", secrets={})

    assert seen["authorization"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,body,headers,message",
    [
        (401, b"no", {}, "refused"),
        (403, b"no", {}, "refused"),
        (302, b"", {"Location": "http://127.0.0.1:1/elsewhere"}, "redirected"),
        (200, b"<html>not json</html>", {}, "JSON"),
        (200, b"x" * 300_000, {}, "too much"),
    ],
)
async def test_read_probe_reports_why_a_page_cannot_be_read(status, body, headers, message):
    def factory():
        def handle(request):
            request.send_response(status)
            for key, value in headers.items():
                request.send_header(key, value)
            request.end_headers()
            request.wfile.write(body)

        return handle

    with _serve(factory) as port:
        with pytest.raises(ProbeUnavailable, match=message):
            await read_probe(_spec(), port=port, run_secret="t", secrets={})


@pytest.mark.asyncio
async def test_read_probe_without_the_credential_does_not_ask_at_all():
    with pytest.raises(ProbeUnavailable, match="credential"):
        await read_probe(_spec(), port=1, run_secret=None, secrets={})
    with pytest.raises(ProbeUnavailable, match="credential"):
        await read_probe(_spec(auth="bearer_secret", secret_name="X"), port=1, run_secret="t", secrets={})


@pytest.mark.asyncio
async def test_read_probe_reports_an_address_nobody_is_listening_on():
    with pytest.raises(ProbeUnavailable, match="could not reach"):
        await read_probe(_spec(), port=1, run_secret="t", secrets={})


@pytest.mark.asyncio
async def test_the_monitor_reports_starting_through_a_brief_hiccup_then_failed_then_recovers():
    answers = [ProbeUnavailable("down")] * 5 + [ProbeReading(phase="ready")]

    async def read(spec, **kwargs):
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    monitor = ProbeMonitor(_spec(), port=1, run_secret="t", secrets={}, read=read, sleep=_fast_sleep)
    phases = [(await monitor.read_once()).phase for _ in range(6)]

    assert phases == ["starting", "starting", "starting", "failed", "failed", "ready"]


@pytest.mark.asyncio
async def test_the_monitor_keeps_going_after_an_unexpected_error_and_stops_when_told():
    calls = {"count": 0}

    async def read(spec, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("boom")
        return ProbeReading(phase="ready")

    monitor = ProbeMonitor(_spec(), port=1, run_secret="t", secrets={}, read=read, sleep=_fast_sleep)
    monitor.start()
    await _eventually(lambda: monitor.reading.phase == "ready")
    await monitor.stop()
    settled = calls["count"]
    await asyncio.sleep(0.2)

    assert calls["count"] == settled


def test_redaction_hides_longer_values_first_and_ignores_values_too_short_to_be_secrets():
    assert redact_secrets("token=abcd1234 and abcd", ["abcd", "abcd1234"]) == "token=[hidden] and [hidden]"
    assert redact_secrets("a b c", ["a", "", "bc"]) == "a b c"
    assert redact_secrets("", ["secret"]) == ""


@pytest.fixture
def stored_preferences(monkeypatch) -> Dict[str, Preferences]:
    holder = {"value": Preferences()}
    monkeypatch.setattr(preferences_io, "load_preferences", lambda: holder["value"].model_copy(deep=True))
    monkeypatch.setattr(preferences_io, "save_preferences", lambda prefs: holder.__setitem__("value", prefs.model_copy(deep=True)))
    return holder


@contextlib.asynccontextmanager
async def _running_bridge(tmp_path: Path, **adapter: Any) -> AsyncIterator[Any]:
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps({"state": "connecting", "message": "Connecting"}))
    supervisor = CompanionSupervisor(
        tmp_path / "local_servers",
        ready_timeout_seconds=15.0,
        stop_grace_seconds=3.0,
        backoff_seconds=(0.05, 0.05),
        probe_sleep=_fast_sleep,
    )
    set_companion_supervisor(supervisor)
    record = register_local_server_record(
        friendly_name="Fake bridge",
        command=sys.executable,
        args=[FIXTURE],
        env={"ADAPTER_TOKEN": "{run_secret}"},
        companion={
            "command": sys.executable,
            "args": ["-c", FAKE_BRIDGE, "{port}", str(state_file)],
            "env": {"BRIDGE_TOKEN": "{run_secret}"},
            "probe": PROBE,
        },
        **adapter,
    )
    try:
        yield supervisor, record, state_file
    finally:
        await supervisor.stop_all()
        set_companion_supervisor(None)


def _set_state(state_file: Path, **fields: Any) -> None:
    state_file.write_text(json.dumps(fields))


@pytest.mark.asyncio
async def test_a_running_program_is_read_through_its_states_and_the_scan_code_is_shown_only_while_needed(tmp_path, stored_preferences):
    async with _running_bridge(tmp_path) as (supervisor, record, state_file):
        started = await supervisor.start(record.id)
        assert started.status == "running"

        _set_state(state_file, state="pairing", message="Scan the code.", qrCode="QR-ONE", qrExpiresAt="2026-01-01T00:00:00Z")
        await _eventually(lambda: (supervisor.snapshot(record.id).health or ProbeReading(phase="starting")).phase == "needs_action")
        health = supervisor.snapshot(record.id).health
        assert health is not None and health.action_value == "QR-ONE" and health.message == "Scan the code."

        _set_state(state_file, state="pairing", message="Scan the code.", qrCode="QR-TWO")
        await _eventually(lambda: (supervisor.snapshot(record.id).health or ProbeReading(phase="starting")).action_value == "QR-TWO")

        _set_state(state_file, state="connected", message="Connected.", qrCode="STALE")
        await _eventually(lambda: (supervisor.snapshot(record.id).health or ProbeReading(phase="starting")).phase == "ready")
        assert supervisor.snapshot(record.id).health.action_value is None

        await supervisor.stop(record.id)
        assert supervisor.snapshot(record.id).health is None


@pytest.mark.asyncio
async def test_the_token_is_new_for_every_run_never_stored_and_hidden_in_what_the_log_says(tmp_path, stored_preferences):
    async with _running_bridge(tmp_path) as (supervisor, record, state_file):
        _set_state(state_file, state="connected")
        await supervisor.start(record.id)
        first = supervisor.run_secret_for(record.id)
        assert first and len(first) >= 32
        await _eventually(lambda: "the token is" in (tmp_path / "local_servers" / f"{record.id}.log").read_text())

        assert first in (tmp_path / "local_servers" / f"{record.id}.log").read_text()
        assert first not in supervisor.log_tail(record.id)
        assert "[hidden]" in supervisor.log_tail(record.id)
        stored = json.dumps(stored_preferences["value"].model_dump(mode="json"))
        assert first not in stored
        assert oct((tmp_path / "local_servers" / f"{record.id}.log").stat().st_mode & 0o777) == "0o600"

        await supervisor.stop(record.id)
        assert supervisor.run_secret_for(record.id) is None
        await supervisor.start(record.id)

        assert supervisor.run_secret_for(record.id) not in (None, first)
        assert first not in supervisor.log_tail(record.id)


@pytest.mark.asyncio
async def test_after_a_crash_the_restarted_program_gets_a_new_token_and_is_read_again(tmp_path, stored_preferences):
    async with _running_bridge(tmp_path) as (supervisor, record, state_file):
        _set_state(state_file, state="connected")
        await supervisor.start(record.id)
        await _eventually(lambda: (supervisor.snapshot(record.id).health or ProbeReading(phase="starting")).phase == "ready")
        first = supervisor.run_secret_for(record.id)
        pid = json.loads((tmp_path / "local_servers" / "pids.json").read_text())[record.id]["pid"]

        os.killpg(pid, signal.SIGKILL)
        await _eventually(lambda: supervisor.snapshot(record.id).restart_count >= 1 and supervisor.snapshot(record.id).status == "running")
        await _eventually(lambda: (supervisor.snapshot(record.id).health or ProbeReading(phase="starting")).phase == "ready")

        assert supervisor.run_secret_for(record.id) not in (None, first)


@pytest.mark.asyncio
async def test_a_program_that_reports_logged_out_is_left_running_and_not_restarted(tmp_path, stored_preferences):
    async with _running_bridge(tmp_path) as (supervisor, record, state_file):
        _set_state(state_file, state="error", message="Logged out.")
        await supervisor.start(record.id)
        await _eventually(lambda: (supervisor.snapshot(record.id).health or ProbeReading(phase="starting")).phase == "failed")
        await asyncio.sleep(0.3)

        snapshot = supervisor.snapshot(record.id)
        assert snapshot.status == "running" and snapshot.restart_count == 0


@pytest.mark.asyncio
async def test_the_server_launches_once_the_program_is_ready_with_the_same_token_in_its_environment(tmp_path, stored_preferences):
    async with _running_bridge(tmp_path) as (supervisor, record, state_file):
        _set_state(state_file, state="connected", message="Connected.")

        prepared = await prepare_stdio_launch(record.stdio, record.id)

        assert prepared.error is None and prepared.parameters is not None
        assert prepared.parameters.env["ADAPTER_TOKEN"] == supervisor.run_secret_for(record.id)


@pytest.mark.asyncio
async def test_the_server_does_not_launch_while_the_person_is_needed_and_the_error_says_so(tmp_path, stored_preferences):
    async with _running_bridge(tmp_path) as (supervisor, record, state_file):
        _set_state(state_file, state="pairing", message="Scan the code with your phone.", qrCode="QR")

        prepared = await prepare_stdio_launch(record.stdio, record.id)

        assert prepared.parameters is None and prepared.error is not None
        error = prepared.error["error"]
        assert "waiting for you" in error["message"] and "Scan the code with your phone." in error["message"]
        assert "finish the step" in error["user_action_required"]
        assert "QR" not in json.dumps(prepared.error)


@pytest.mark.asyncio
async def test_a_failed_program_and_a_slow_one_are_reported_differently(tmp_path, stored_preferences, monkeypatch):
    monkeypatch.setattr(local_server_launch, "HEALTH_WAIT_SECONDS", 0.6)
    async with _running_bridge(tmp_path) as (supervisor, record, state_file):
        _set_state(state_file, state="error", message="Logged out.")
        failed = await prepare_stdio_launch(record.stdio, record.id)
        assert failed.error is not None and "reports a problem" in failed.error["error"]["message"]

        _set_state(state_file, state="connecting", message="Connecting")
        await _eventually(lambda: (supervisor.snapshot(record.id).health or ProbeReading(phase="failed")).phase == "starting")
        slow = await prepare_stdio_launch(record.stdio, record.id)
        assert slow.error is not None and "still starting" in slow.error["error"]["message"]
        assert slow.error["error"]["user_action_required"] == "Try again in a moment."


@pytest.mark.asyncio
async def test_a_server_with_no_probe_is_ready_as_soon_as_its_program_runs(tmp_path, stored_preferences):
    supervisor = CompanionSupervisor(tmp_path / "local_servers", ready_timeout_seconds=15.0, stop_grace_seconds=3.0)
    set_companion_supervisor(supervisor)
    record = register_local_server_record(
        friendly_name="Plain",
        command=sys.executable,
        args=[FIXTURE],
        companion={"command": sys.executable, "args": ["-c", "import time\nwhile True: time.sleep(1)"]},
    )
    try:
        await supervisor.start(record.id)
        snapshot = await asyncio.wait_for(supervisor.wait_until_ready(record.id, 5.0), timeout=3.0)

        assert snapshot.running and snapshot.health is None
    finally:
        await supervisor.stop_all()
        set_companion_supervisor(None)


@pytest.mark.asyncio
async def test_forgetting_a_connection_deletes_its_install_and_data_folders(tmp_path, stored_preferences):
    async with _running_bridge(tmp_path) as (supervisor, record, state_file):
        _set_state(state_file, state="connected")
        await supervisor.start(record.id)
        folders = supervisor.folders(record.id)
        assert folders.install.is_dir() and folders.data.is_dir()
        (folders.data / "session.db").write_text("x")

        await supervisor.forget(record.id)

        assert not folders.install.parent.exists()


@pytest.mark.asyncio
async def test_the_connection_response_carries_the_health_and_the_scan_code_only_while_it_is_needed(tmp_path, stored_preferences):
    from api.routes.connections.local_server_dto import build_local_server_dto

    async with _running_bridge(tmp_path) as (supervisor, record, state_file):
        _set_state(state_file, state="pairing", message="Scan the code.", qrCode="QR-DTO", qrExpiresAt="2026-01-01T00:00:00Z")
        await supervisor.start(record.id)
        await _eventually(lambda: (supervisor.snapshot(record.id).health or ProbeReading(phase="starting")).phase == "needs_action")

        waiting = build_local_server_dto(record).companion
        assert waiting is not None and waiting.has_probe
        assert (waiting.health_phase, waiting.health_message, waiting.action_kind, waiting.action_value) == ("needs_action", "Scan the code.", "qr", "QR-DTO")
        assert waiting.action_expires_at == "2026-01-01T00:00:00Z"

        _set_state(state_file, state="connected", message="Connected.")
        await _eventually(lambda: (supervisor.snapshot(record.id).health or ProbeReading(phase="starting")).phase == "ready")
        ready = build_local_server_dto(record).companion
        assert ready is not None and ready.health_phase == "ready" and ready.action_value is None and ready.action_kind is None

        await supervisor.stop(record.id)
        stopped = build_local_server_dto(record).companion
        assert stopped is not None and stopped.health_phase is None and stopped.has_probe
