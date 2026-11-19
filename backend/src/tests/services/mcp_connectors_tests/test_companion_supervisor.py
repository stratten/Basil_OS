"""The companion supervisor, against real background programs."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, AsyncIterator, Callable, Dict, List, Optional, Tuple

import pytest

from api.core.models.preferences import MCPCompanionSpec, MCPConnectionRecord, MCPStdioSpec
from api.core.runtime.safe_spawn import create_subprocess_exec
from api.services.mcp_connectors.companion_supervisor import CompanionError, CompanionSupervisor
from api.services.mcp_connectors.local_server_secrets import SecretResolution
from api.services.mcp_connectors.port_allocation import allocate_loopback_port, port_accepts_connections

LISTEN_FOREVER = (
    "import socket, sys, time\n"
    "s = socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)\n"
    "s.bind(('127.0.0.1', int(sys.argv[1]))); s.listen()\n"
    "while True: time.sleep(1)\n"
)
LISTEN_THEN_EXIT = (
    "import socket, sys, time\n"
    "s = socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)\n"
    "s.bind(('127.0.0.1', int(sys.argv[1]))); s.listen()\n"
    "time.sleep(0.4)\n"
    "raise SystemExit(1)\n"
)
LISTEN_ONCE_THEN_STAY = (
    "import os, socket, sys, time\n"
    "s = socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)\n"
    "s.bind(('127.0.0.1', int(sys.argv[1]))); s.listen()\n"
    "marker = sys.argv[2]\n"
    "if not os.path.exists(marker):\n"
    "    open(marker, 'w').write('crashed once')\n"
    "    time.sleep(0.4)\n"
    "    raise SystemExit(1)\n"
    "while True: time.sleep(1)\n"
)
SLEEP_FOREVER = "import time\nwhile True: time.sleep(1)\n"
EXIT_AT_ONCE = "raise SystemExit(3)\n"
PRINT_TOKEN_THEN_SLEEP = "import os, time\nprint('token=' + os.environ['BRIDGE_TOKEN'], flush=True)\nwhile True: time.sleep(1)\n"
SPAWN_GRANDCHILD = (
    "import subprocess, sys, time\n"
    "child = subprocess.Popen([sys.executable, '-c', 'import time\\nwhile True: time.sleep(1)'])\n"
    "open(sys.argv[1], 'w').write(str(child.pid))\n"
    "while True: time.sleep(1)\n"
)


class _CountingSpawn:
    def __init__(self) -> None:
        self.calls = 0

    async def __call__(self, *args: Any, **kwargs: Any) -> Any:
        self.calls += 1
        return await create_subprocess_exec(*args, **kwargs)


def _companion(script: str, *script_args: str, **fields: Any) -> MCPCompanionSpec:
    return MCPCompanionSpec(command=sys.executable, args=["-c", script, *script_args], **fields)


def _record(companion: Optional[MCPCompanionSpec], *, enabled: bool = True) -> MCPConnectionRecord:
    spec = MCPStdioSpec(command=sys.executable, args=["-c", "pass"], companion=companion)
    return MCPConnectionRecord(friendly_name="Bridge", server_url="basil-stdio://pending", stdio=spec, enabled=enabled)


@contextlib.asynccontextmanager
async def _supervised(tmp_path: Path, records: List[MCPConnectionRecord], **overrides: Any) -> AsyncIterator[CompanionSupervisor]:
    options: Dict[str, Any] = {
        "load_connections": lambda: records,
        "ready_timeout_seconds": 15.0,
        "no_port_grace_seconds": 0.3,
        "stop_grace_seconds": 3.0,
        "backoff_seconds": (0.05, 0.05),
        "stable_run_seconds": 30.0,
    }
    options.update(overrides)
    supervisor = CompanionSupervisor(tmp_path / "local_servers", **options)
    try:
        yield supervisor
    finally:
        await supervisor.stop_all()


async def _eventually(predicate: Callable[[], bool], timeout: float = 15.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.05)
    raise AssertionError("the condition never became true")


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


@pytest.mark.asyncio
async def test_a_program_that_uses_the_port_placeholder_is_started_on_a_free_port_and_stopped_cleanly(tmp_path):
    record = _record(_companion(LISTEN_FOREVER, "{port}"))
    async with _supervised(tmp_path, [record]) as supervisor:
        started = await supervisor.start(record.id)

        assert started.status == "running"
        assert started.port is not None and await port_accepts_connections(started.port)
        pids = json.loads((tmp_path / "local_servers" / "pids.json").read_text())
        assert record.id in pids

        stopped = await supervisor.stop(record.id)

        assert stopped.status == "stopped" and stopped.port is None
        assert await port_accepts_connections(started.port) is False
        assert json.loads((tmp_path / "local_servers" / "pids.json").read_text()) == {}


@pytest.mark.asyncio
async def test_a_program_without_a_port_counts_as_started_when_it_stays_alive(tmp_path):
    record = _record(_companion(SLEEP_FOREVER))
    async with _supervised(tmp_path, [record]) as supervisor:
        started = await supervisor.start(record.id)

        assert started.status == "running" and started.port is None
        pid = json.loads((tmp_path / "local_servers" / "pids.json").read_text())[record.id]["pid"]
        assert _pid_alive(pid)

        await supervisor.stop(record.id)

        assert not _pid_alive(pid)


@pytest.mark.asyncio
async def test_a_program_that_exits_at_once_is_reported_failed_with_its_exit_code(tmp_path):
    record = _record(_companion(EXIT_AT_ONCE))
    async with _supervised(tmp_path, [record]) as supervisor:
        result = await supervisor.start(record.id)

        assert result.status == "failed"
        assert result.last_error and "exit code 3" in result.last_error


@pytest.mark.asyncio
async def test_a_program_that_never_listens_is_stopped_and_reported_failed(tmp_path):
    free_port = allocate_loopback_port()
    record = _record(_companion(SLEEP_FOREVER, fixed_port=free_port))
    async with _supervised(tmp_path, [record], ready_timeout_seconds=1.0) as supervisor:
        result = await supervisor.start(record.id)

        assert result.status == "failed"
        assert result.last_error and f"port {free_port}" in result.last_error
        assert json.loads((tmp_path / "local_servers" / "pids.json").read_text()) == {}


@pytest.mark.asyncio
async def test_missing_secrets_stop_the_start_before_anything_is_spawned(tmp_path):
    record = _record(_companion(SLEEP_FOREVER, secret_env=["BRIDGE_TOKEN"]))
    spawn = _CountingSpawn()

    async def _resolve(connection_id: str, names: Any, *, wait_for_host: bool = False) -> SecretResolution:
        return SecretResolution(missing=list(names))

    async with _supervised(tmp_path, [record], spawn=spawn, resolve_secrets=_resolve) as supervisor:
        result = await supervisor.start(record.id)

        assert result.status == "needs_secrets"
        assert result.missing_secrets == ("BRIDGE_TOKEN",)
        assert result.last_error and "BRIDGE_TOKEN" in result.last_error
        assert spawn.calls == 0


@pytest.mark.asyncio
async def test_no_connected_app_fails_the_start_with_the_bridge_message(tmp_path):
    record = _record(_companion(SLEEP_FOREVER, secret_env=["BRIDGE_TOKEN"]))

    async def _resolve(connection_id: str, names: Any, *, wait_for_host: bool = False) -> SecretResolution:
        return SecretResolution(blocked_message="No Basil client is connected to provide the external service token.")

    async with _supervised(tmp_path, [record], resolve_secrets=_resolve) as supervisor:
        result = await supervisor.start(record.id)

        assert result.status == "failed"
        assert result.last_error and "No Basil client" in result.last_error


@pytest.mark.asyncio
async def test_secret_values_reach_the_program_environment_and_nothing_else(tmp_path):
    record = _record(_companion(PRINT_TOKEN_THEN_SLEEP, secret_env=["BRIDGE_TOKEN"]))
    asked: List[Tuple[str, List[str], bool]] = []

    async def _resolve(connection_id: str, names: Any, *, wait_for_host: bool = False) -> SecretResolution:
        asked.append((connection_id, list(names), wait_for_host))
        return SecretResolution(values={"BRIDGE_TOKEN": "s3cret-value"})

    async with _supervised(tmp_path, [record], resolve_secrets=_resolve) as supervisor:
        result = await supervisor.start(record.id)
        assert result.status == "running"
        await _eventually(lambda: "token=[hidden]" in supervisor.log_tail(record.id))

        assert "s3cret-value" not in supervisor.log_tail(record.id)
        assert asked == [(record.id, ["BRIDGE_TOKEN"], False)]
        assert "s3cret-value" not in (tmp_path / "local_servers" / "pids.json").read_text()


@pytest.mark.asyncio
async def test_a_crash_while_running_restarts_the_program_on_a_new_port(tmp_path):
    marker = tmp_path / "crashed.marker"
    record = _record(_companion(LISTEN_ONCE_THEN_STAY, "{port}", str(marker)))
    async with _supervised(tmp_path, [record]) as supervisor:
        first = await supervisor.start(record.id)
        assert first.status == "running"

        await _eventually(lambda: supervisor.snapshot(record.id).restart_count == 1 and supervisor.snapshot(record.id).status == "running")

        after = supervisor.snapshot(record.id)
        assert after.port is not None and await port_accepts_connections(after.port)
        assert marker.exists()


@pytest.mark.asyncio
async def test_repeated_crashes_end_in_failed_with_a_clear_message(tmp_path):
    record = _record(_companion(LISTEN_THEN_EXIT, "{port}"))
    async with _supervised(tmp_path, [record]) as supervisor:
        first = await supervisor.start(record.id)
        assert first.status == "running"

        await _eventually(lambda: supervisor.snapshot(record.id).status == "failed")

        final = supervisor.snapshot(record.id)
        assert final.restart_count == 2
        assert final.last_error and "gave up" in final.last_error
        assert json.loads((tmp_path / "local_servers" / "pids.json").read_text()) == {}


@pytest.mark.asyncio
async def test_stopping_during_the_wait_before_a_restart_prevents_the_restart(tmp_path):
    record = _record(_companion(LISTEN_THEN_EXIT, "{port}"))
    spawn = _CountingSpawn()
    async with _supervised(tmp_path, [record], spawn=spawn, backoff_seconds=(30.0,)) as supervisor:
        await supervisor.start(record.id)
        await _eventually(lambda: supervisor.snapshot(record.id).status == "starting")

        stopped = await supervisor.stop(record.id)

        assert stopped.status == "stopped"
        await asyncio.sleep(0.3)
        assert spawn.calls == 1
        assert supervisor.snapshot(record.id).status == "stopped"


@pytest.mark.asyncio
async def test_stopping_while_waiting_for_readiness_returns_promptly(tmp_path):
    record = _record(_companion(SLEEP_FOREVER, fixed_port=allocate_loopback_port()))
    async with _supervised(tmp_path, [record], ready_timeout_seconds=60.0) as supervisor:
        starting = asyncio.create_task(supervisor.start(record.id))
        await _eventually(lambda: supervisor.snapshot(record.id).status == "starting" and (tmp_path / "local_servers" / "pids.json").exists())

        stopped = await asyncio.wait_for(supervisor.stop(record.id), timeout=10.0)
        await asyncio.wait_for(starting, timeout=10.0)

        assert stopped.status == "stopped"
        assert supervisor.snapshot(record.id).status == "stopped"


@pytest.mark.asyncio
async def test_stopping_ends_the_whole_process_group_including_grandchildren(tmp_path):
    child_pid_file = tmp_path / "grandchild.pid"
    record = _record(_companion(SPAWN_GRANDCHILD, str(child_pid_file)))
    async with _supervised(tmp_path, [record]) as supervisor:
        await supervisor.start(record.id)
        await _eventually(child_pid_file.exists)
        await _eventually(lambda: child_pid_file.read_text().strip().isdigit())
        grandchild = int(child_pid_file.read_text())
        assert _pid_alive(grandchild)

        await supervisor.stop(record.id)

        await _eventually(lambda: not _pid_alive(grandchild), timeout=5.0)


@pytest.mark.asyncio
async def test_leftovers_from_a_crashed_run_are_stopped_but_a_reused_pid_is_left_alone(tmp_path):
    state_dir = tmp_path / "local_servers"
    state_dir.mkdir()
    # The recorded program is a marker in the command line, not sys.executable: a macOS framework Python re-launches itself, so `ps` shows Python.app instead of the path it was started with.
    marker = "basil-leftover-test-marker"
    leftover = subprocess.Popen([sys.executable, "-c", f"{SLEEP_FOREVER}# {marker}\n"], start_new_session=True)
    bystander = subprocess.Popen([sys.executable, "-c", SLEEP_FOREVER], start_new_session=True)
    try:
        (state_dir / "pids.json").write_text(
            json.dumps(
                {
                    "leftover": {"pid": leftover.pid, "executable": marker},
                    "reused": {"pid": bystander.pid, "executable": "/not/the/recorded/program"},
                }
            )
        )
        async with _supervised(tmp_path, []) as supervisor:
            reaped = await supervisor.reap_leftovers()

        assert reaped == 1
        leftover.wait(timeout=5)
        assert bystander.poll() is None
        assert json.loads((state_dir / "pids.json").read_text()) == {}
    finally:
        for process in (leftover, bystander):
            if process.poll() is None:
                process.kill()
                process.wait()


@pytest.mark.asyncio
async def test_only_enabled_programs_set_to_start_with_basil_are_started_at_launch(tmp_path):
    with_basil = _record(_companion(SLEEP_FOREVER, start_with_basil=True))
    lazy = _record(_companion(SLEEP_FOREVER, start_with_basil=False))
    disabled = _record(_companion(SLEEP_FOREVER, start_with_basil=True), enabled=False)
    plain = _record(None)
    async with _supervised(tmp_path, [with_basil, lazy, disabled, plain]) as supervisor:
        await supervisor.start_enabled_at_launch()

        assert supervisor.snapshot(with_basil.id).status == "running"
        assert supervisor.snapshot(lazy.id).status == "stopped"
        assert supervisor.snapshot(disabled.id).status == "stopped"
        assert supervisor.snapshot(plain.id).status == "stopped"


@pytest.mark.asyncio
async def test_a_program_that_is_not_started_with_basil_starts_on_first_use_and_only_once(tmp_path):
    record = _record(_companion(SLEEP_FOREVER, start_with_basil=False))
    spawn = _CountingSpawn()
    async with _supervised(tmp_path, [record], spawn=spawn) as supervisor:
        first = await supervisor.ensure_running(record.id)
        second = await supervisor.ensure_running(record.id)

        assert first.status == "running" and second.status == "running"
        assert spawn.calls == 1


@pytest.mark.asyncio
async def test_two_starts_at_the_same_time_spawn_one_program(tmp_path):
    record = _record(_companion(SLEEP_FOREVER))
    spawn = _CountingSpawn()
    async with _supervised(tmp_path, [record], spawn=spawn) as supervisor:
        results = await asyncio.gather(supervisor.start(record.id), supervisor.start(record.id))

        assert [result.status for result in results] == ["running", "running"]
        assert spawn.calls == 1


@pytest.mark.asyncio
async def test_start_refuses_unknown_plain_and_disabled_connections_in_plain_words(tmp_path):
    plain = _record(None)
    disabled = _record(_companion(SLEEP_FOREVER), enabled=False)
    async with _supervised(tmp_path, [plain, disabled]) as supervisor:
        with pytest.raises(CompanionError, match="not set up"):
            await supervisor.start("no-such-connection")
        with pytest.raises(CompanionError, match="does not use a background program"):
            await supervisor.start(plain.id)
        with pytest.raises(CompanionError, match="turned off"):
            await supervisor.start(disabled.id)
        with pytest.raises(CompanionError, match="not set up"):
            await supervisor.start("../escape")


@pytest.mark.asyncio
async def test_forgetting_a_connection_stops_it_and_deletes_its_log(tmp_path):
    record = _record(_companion(PRINT_TOKEN_THEN_SLEEP, secret_env=["BRIDGE_TOKEN"]))

    async def _resolve(connection_id: str, names: Any, *, wait_for_host: bool = False) -> SecretResolution:
        return SecretResolution(values={"BRIDGE_TOKEN": "abc"})

    async with _supervised(tmp_path, [record], resolve_secrets=_resolve) as supervisor:
        await supervisor.start(record.id)
        await _eventually(lambda: "token=abc" in supervisor.log_tail(record.id))
        assert (tmp_path / "local_servers" / f"{record.id}.log").exists()

        await supervisor.forget(record.id)

        assert not (tmp_path / "local_servers" / f"{record.id}.log").exists()
        assert supervisor.snapshot(record.id).status == "stopped"
        assert json.loads((tmp_path / "local_servers" / "pids.json").read_text()) == {}


@pytest.mark.asyncio
async def test_a_connection_that_never_started_is_reported_stopped(tmp_path):
    async with _supervised(tmp_path, []) as supervisor:
        assert supervisor.snapshot("anything").status == "stopped"
        assert supervisor.log_tail("../escape") == ""


def test_the_startup_and_shutdown_hooks_are_wired_into_the_application():
    source = (Path(__file__).resolve().parents[3] / "api" / "main.py").read_text(encoding="utf-8")

    assert "get_companion_supervisor().start_enabled_at_launch()" in source
    assert "get_companion_supervisor().stop_all()" in source
