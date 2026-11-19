"""Keeps a local server's background program running, and says whether it is.

Some local servers cannot work without a program running beside them (for example a bridge that holds a paired session). Basil starts that program, waits until it is ready, restarts it after a crash, and stops it when Basil quits. The backend owns the process, so there is no separate supervisor in the app.

The program is never run through a shell. Secret values are read from the Keychain only while the launch environment is built, and they are never logged or written down.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import signal
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from secrets import token_urlsafe
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence, Tuple

from api.core.models.preferences import MCPCompanionSpec, MCPConnectionRecord, MCPStdioSpec
from api.core.runtime.safe_spawn import create_subprocess_exec

from .companion_probe import GetJson, ProbeMonitor, ProbeReading, read_probe
from .local_server_paths import ConnectionFolders, ensure_connection_folders, remove_connection_folders
from .local_server_placeholders import contains_path_placeholder, contains_port_placeholder
from .local_server_prepare import NOT_PREPARED_MESSAGE, artifacts_ready
from .local_server_redaction import redact_secrets
from .local_server_secrets import SecretResolution, resolve_secret_env
from .port_allocation import allocate_loopback_port, wait_until_port_accepts
from .stdio_transport import StdioSpecError, build_parameters

logger = logging.getLogger(__name__)

READY_TIMEOUT_SECONDS = 90.0
NO_PORT_GRACE_SECONDS = 1.0
STOP_GRACE_SECONDS = 5.0
RESTART_BACKOFF_SECONDS: Tuple[float, ...] = (1.0, 2.0, 4.0, 8.0, 16.0)
STABLE_RUN_SECONDS = 30.0
MAX_LOG_BYTES = 1_000_000
LOG_TAIL_CHARS = 1500
_SAFE_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")

STATUS_STOPPED = "stopped"
STATUS_STARTING = "starting"
STATUS_RUNNING = "running"
STATUS_FAILED = "failed"
STATUS_NEEDS_SECRETS = "needs_secrets"
STATUS_STOPPING = "stopping"

_RESULT_RUNNING = "running"
_RESULT_RETRY = "retry"
_RESULT_FINAL = "final"


class CompanionError(Exception):
    """The background program cannot be started because of how the connection is set up. The message says why in plain words."""


@dataclass(frozen=True)
class CompanionSnapshot:
    """What the rest of Basil may know about a background program right now."""

    status: str
    port: Optional[int] = None
    last_error: Optional[str] = None
    restart_count: int = 0
    missing_secrets: Tuple[str, ...] = ()
    health: Optional[ProbeReading] = None
    """What the program's own status page said last, when the connection has a probe and the program is running."""

    @property
    def running(self) -> bool:
        return self.status == STATUS_RUNNING


@dataclass
class _Runtime:
    connection_id: str
    status: str = STATUS_STOPPED
    pid: Optional[int] = None
    port: Optional[int] = None
    started_at: Optional[float] = None
    last_error: Optional[str] = None
    restart_count: int = 0
    consecutive_failures: int = 0
    missing_secrets: List[str] = field(default_factory=list)
    wanted: bool = False
    process: Any = None
    watcher: Optional["asyncio.Task[None]"] = None
    restart_task: Optional["asyncio.Task[None]"] = None
    log_offset: int = 0
    run_secret: Optional[str] = None
    secret_values: Dict[str, str] = field(default_factory=dict)
    known_secrets: set = field(default_factory=set)
    monitor: Optional[ProbeMonitor] = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


def _stored_connections() -> List[MCPConnectionRecord]:
    from api.core.preferences import preferences_io

    return list(preferences_io.load_preferences().connections.mcp_connections)


class CompanionSupervisor:
    """Starts, watches, restarts and stops the background programs of local servers. One instance serves the whole backend."""

    def __init__(
        self,
        state_dir: Path,
        *,
        load_connections: Callable[[], List[MCPConnectionRecord]] = _stored_connections,
        resolve_secrets: Optional[Callable[..., Awaitable[SecretResolution]]] = None,
        allocate_port: Callable[[], int] = allocate_loopback_port,
        wait_for_port: Callable[..., Awaitable[bool]] = wait_until_port_accepts,
        spawn: Optional[Callable[..., Awaitable[Any]]] = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        ready_timeout_seconds: float = READY_TIMEOUT_SECONDS,
        no_port_grace_seconds: float = NO_PORT_GRACE_SECONDS,
        stop_grace_seconds: float = STOP_GRACE_SECONDS,
        backoff_seconds: Sequence[float] = RESTART_BACKOFF_SECONDS,
        stable_run_seconds: float = STABLE_RUN_SECONDS,
        probe_read: Callable[..., Awaitable[ProbeReading]] = read_probe,
        probe_sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        probe_get_json: Optional[GetJson] = None,
    ) -> None:
        self._state_dir = Path(state_dir)
        self._probe_read = probe_read
        self._probe_sleep = probe_sleep
        self._probe_get_json = probe_get_json
        self._load_connections = load_connections
        self._resolve_secrets = resolve_secrets or resolve_secret_env
        self._allocate_port = allocate_port
        self._wait_for_port = wait_for_port
        self._spawn = spawn or create_subprocess_exec
        self._sleep = sleep
        self._ready_timeout = ready_timeout_seconds
        self._no_port_grace = no_port_grace_seconds
        self._stop_grace = stop_grace_seconds
        self._backoff = tuple(backoff_seconds)
        self._stable_run = stable_run_seconds
        self._runtimes: Dict[str, _Runtime] = {}

    # ------------------------------------------------------------------ public

    @property
    def state_dir(self) -> Path:
        return self._state_dir

    def folders(self, connection_id: str) -> ConnectionFolders:
        """The install and data folders for a connection, created when missing."""
        return ensure_connection_folders(self._state_dir, connection_id)

    def run_secret_for(self, connection_id: str) -> Optional[str]:
        """The token generated for the program's current run, or None when it is not running. Held in memory only."""
        runtime = self._runtimes.get(connection_id)
        return runtime.run_secret if runtime is not None else None

    def snapshot(self, connection_id: str) -> CompanionSnapshot:
        runtime = self._runtimes.get(connection_id)
        if runtime is None:
            return CompanionSnapshot(status=STATUS_STOPPED)
        status = runtime.status
        if status == STATUS_RUNNING and not self._is_alive(runtime):
            status = STATUS_FAILED
        return CompanionSnapshot(
            status=status,
            port=runtime.port,
            last_error=runtime.last_error,
            restart_count=runtime.restart_count,
            missing_secrets=tuple(runtime.missing_secrets),
            health=runtime.monitor.reading if runtime.monitor is not None and status == STATUS_RUNNING else None,
        )

    async def wait_until_ready(self, connection_id: str, timeout_seconds: float, poll_seconds: float = 0.5) -> CompanionSnapshot:
        """The snapshot once the program's own status page says ready or needs the person, or after the timeout. A connection with no probe is ready as soon as it is running."""
        deadline = time.monotonic() + timeout_seconds
        while True:
            snapshot = self.snapshot(connection_id)
            if not snapshot.running or snapshot.health is None and not self._has_probe(connection_id):
                return snapshot
            if snapshot.health is not None and snapshot.health.phase != "starting":
                return snapshot
            if time.monotonic() >= deadline:
                return snapshot
            await asyncio.sleep(poll_seconds)

    def _has_probe(self, connection_id: str) -> bool:
        runtime = self._runtimes.get(connection_id)
        return runtime is not None and runtime.monitor is not None

    def log_tail(self, connection_id: str) -> str:
        """The end of the program's own output, for the Settings row and for error messages, with secret values hidden."""
        if not _SAFE_ID.fullmatch(connection_id):
            return ""
        return self._redacted(connection_id, self._read_log(self._log_path(connection_id), 0))

    def _redacted(self, connection_id: str, text: str) -> str:
        runtime = self._runtimes.get(connection_id)
        return redact_secrets(text, runtime.known_secrets) if runtime is not None else text

    async def start(self, connection_id: str, *, wait_for_host: bool = False) -> CompanionSnapshot:
        """Start the program now unless it is already running. Returns the state after one attempt; a failure is reported, not retried."""
        record, companion = self._configured(connection_id)
        runtime = self._runtime(connection_id)
        runtime.wanted = True
        async with runtime.lock:
            if self._is_alive(runtime) and runtime.status in (STATUS_STARTING, STATUS_RUNNING):
                return self.snapshot(connection_id)
            if not artifacts_ready(record.stdio.install, self.folders(connection_id)):
                runtime.status = STATUS_FAILED
                runtime.last_error = NOT_PREPARED_MESSAGE
                return self.snapshot(connection_id)
            runtime.consecutive_failures = 0
            await self._launch_locked(runtime, companion, wait_for_host=wait_for_host)
        return self.snapshot(connection_id)

    async def ensure_running(self, connection_id: str) -> CompanionSnapshot:
        """The program's state, starting it first when it is not running. Used the first time a server that is not set to start with Basil is used."""
        current = self.snapshot(connection_id)
        if current.running:
            return current
        return await self.start(connection_id)

    async def stop(self, connection_id: str) -> CompanionSnapshot:
        """Stop the program and keep it stopped until it is started again."""
        runtime = self._runtimes.get(connection_id)
        if runtime is None:
            return CompanionSnapshot(status=STATUS_STOPPED)
        runtime.wanted = False
        task = runtime.restart_task
        runtime.restart_task = None
        if task is not None and task is not asyncio.current_task():
            task.cancel()
        async with runtime.lock:
            await self._stop_locked(runtime, STATUS_STOPPED)
            runtime.last_error = None
            runtime.missing_secrets = []
        return self.snapshot(connection_id)

    async def stop_all(self) -> None:
        for connection_id in list(self._runtimes):
            try:
                await self.stop(connection_id)
            except Exception:
                logger.exception("Stopping the background program of local server %s failed", connection_id)

    async def forget(self, connection_id: str) -> None:
        """Stop the program and delete everything Basil kept about it: its log, its pid entry and its state."""
        await self.stop(connection_id)
        self._runtimes.pop(connection_id, None)
        if _SAFE_ID.fullmatch(connection_id):
            try:
                self._log_path(connection_id).unlink()
            except OSError:
                pass
            remove_connection_folders(self._state_dir, connection_id)
        self._forget_pid(connection_id)

    async def start_enabled_at_launch(self) -> None:
        """At backend start: stop leftovers from a crashed run, then start every enabled program that is set to start with Basil."""
        try:
            await self.reap_leftovers()
        except Exception:
            logger.exception("Reaping leftover local server programs failed")

        async def _start_one(connection_id: str) -> None:
            try:
                await self.start(connection_id, wait_for_host=True)
            except CompanionError as exc:
                logger.info("Local server %s was not started with Basil: %s", connection_id, exc)
            except Exception:
                logger.exception("Starting the background program of local server %s failed", connection_id)

        wanted = [
            record.id
            for record in self._load_connections()
            if record.enabled and record.stdio is not None and record.stdio.companion is not None and record.stdio.companion.start_with_basil
        ]
        await asyncio.gather(*[_start_one(connection_id) for connection_id in wanted])

    async def reap_leftovers(self) -> int:
        """Stop every program recorded in the pid file whose process is still running. Returns how many were stopped."""
        reaped = 0
        for connection_id, entry in self._read_pids().items():
            pid = entry.get("pid")
            executable = entry.get("executable")
            if isinstance(pid, int) and isinstance(executable, str) and _pid_runs(pid, executable):
                logger.warning("Stopping a leftover background program of local server %s (pid %s)", connection_id, pid)
                await self._terminate_group(pid, None)
                reaped += 1
        self._write_pids({})
        return reaped

    # ---------------------------------------------------------------- internals

    def _runtime(self, connection_id: str) -> _Runtime:
        runtime = self._runtimes.get(connection_id)
        if runtime is None:
            runtime = _Runtime(connection_id=connection_id)
            self._runtimes[connection_id] = runtime
        return runtime

    @staticmethod
    def _is_alive(runtime: _Runtime) -> bool:
        return runtime.process is not None and runtime.process.returncode is None

    def _configured(self, connection_id: str) -> Tuple[MCPConnectionRecord, MCPCompanionSpec]:
        if not _SAFE_ID.fullmatch(connection_id):
            raise CompanionError("That local server is not set up.")
        for record in self._load_connections():
            if record.id != connection_id:
                continue
            if record.stdio is None or record.stdio.companion is None:
                raise CompanionError("This server does not use a background program.")
            if not record.enabled:
                raise CompanionError("This server is turned off in Settings.")
            return record, record.stdio.companion
        raise CompanionError("That local server is not set up.")

    def _log_path(self, connection_id: str) -> Path:
        return self._state_dir / f"{connection_id}.log"

    def _pids_path(self) -> Path:
        return self._state_dir / "pids.json"

    def _read_pids(self) -> Dict[str, Dict[str, Any]]:
        try:
            data = json.loads(self._pids_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _write_pids(self, data: Dict[str, Dict[str, Any]]) -> None:
        self._state_dir.mkdir(parents=True, exist_ok=True)
        temporary = self._pids_path().with_suffix(".tmp")
        temporary.write_text(json.dumps(data), encoding="utf-8")
        os.replace(temporary, self._pids_path())

    def _remember_pid(self, connection_id: str, pid: int, executable: str) -> None:
        data = self._read_pids()
        data[connection_id] = {"pid": pid, "executable": executable}
        self._write_pids(data)

    def _forget_pid(self, connection_id: str) -> None:
        data = self._read_pids()
        if connection_id in data:
            del data[connection_id]
            self._write_pids(data)

    def _prepare_log(self, path: Path) -> int:
        self._state_dir.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.stat().st_size > MAX_LOG_BYTES:
            path.write_bytes(b"")
        with open(path, "ab") as handle:
            handle.write(f"--- started {datetime.now().isoformat(timespec='seconds')} ---\n".encode("utf-8"))
        path.chmod(0o600)
        return path.stat().st_size

    @staticmethod
    def _read_log(path: Path, offset: int) -> str:
        try:
            with open(path, "rb") as handle:
                handle.seek(offset)
                data = handle.read()
        except OSError:
            return ""
        return data.decode("utf-8", errors="replace")[-LOG_TAIL_CHARS:].strip()

    def _said(self, runtime: _Runtime) -> str:
        tail = self._redacted(runtime.connection_id, self._read_log(self._log_path(runtime.connection_id), runtime.log_offset))
        return f" It said: {tail}" if tail else ""

    async def _launch_locked(self, runtime: _Runtime, companion: MCPCompanionSpec, *, wait_for_host: bool) -> str:
        """One start attempt, with the runtime lock held. Returns running, retry (a crash-like failure) or final (nothing a retry would fix)."""
        connection_id = runtime.connection_id
        runtime.status = STATUS_STARTING
        runtime.last_error = None
        runtime.missing_secrets = []
        runtime.port = None

        secrets = SecretResolution()
        if companion.secret_env:
            secrets = await self._resolve_secrets(connection_id, companion.secret_env, wait_for_host=wait_for_host)
            if not runtime.wanted:
                runtime.status = STATUS_STOPPED
                return _RESULT_FINAL
            if secrets.missing:
                runtime.status = STATUS_NEEDS_SECRETS
                runtime.missing_secrets = list(secrets.missing)
                runtime.last_error = f"Enter the values for {', '.join(secrets.missing)} in Settings, then start it again."
                return _RESULT_FINAL
            if secrets.blocked_message:
                runtime.status = STATUS_FAILED
                runtime.last_error = secrets.blocked_message
                return _RESULT_FINAL

        allocated_port = self._allocate_port() if contains_port_placeholder([*companion.args, *companion.env.values()]) else None
        run_secret = token_urlsafe(32)
        runtime.run_secret = run_secret
        runtime.secret_values = dict(secrets.values)
        runtime.known_secrets.update({run_secret, *secrets.values.values()})
        launch_spec = MCPStdioSpec(command=companion.command, args=list(companion.args), cwd=companion.cwd, env=dict(companion.env))
        folders: Optional[ConnectionFolders] = None
        try:
            if contains_path_placeholder([launch_spec.command, launch_spec.cwd or "", *launch_spec.args, *launch_spec.env.values()]):
                folders = self.folders(connection_id)
            parameters = build_parameters(
                launch_spec,
                port=allocated_port,
                extra_env=secrets.values,
                run_secret=run_secret,
                data_dir=str(folders.data) if folders else None,
                install_dir=str(folders.install) if folders else None,
            )
        except (StdioSpecError, OSError, ValueError) as exc:
            runtime.run_secret = None
            runtime.secret_values = {}
            runtime.status = STATUS_FAILED
            runtime.last_error = f"The background program cannot start: {exc}"
            return _RESULT_FINAL

        log_path = self._log_path(connection_id)
        runtime.log_offset = self._prepare_log(log_path)
        try:
            with open(log_path, "ab") as log_handle:
                process = await self._spawn(
                    parameters.command,
                    *parameters.args,
                    cwd=parameters.cwd,
                    env=parameters.env,
                    stdin=asyncio.subprocess.DEVNULL,
                    stdout=log_handle,
                    stderr=asyncio.subprocess.STDOUT,
                    start_new_session=True,
                )
        except OSError as exc:
            runtime.status = STATUS_FAILED
            runtime.last_error = f"The background program could not be started: {exc}"
            return _RESULT_FINAL

        runtime.process = process
        runtime.pid = process.pid
        runtime.started_at = time.monotonic()
        runtime.port = allocated_port if allocated_port is not None else companion.fixed_port
        self._remember_pid(connection_id, process.pid, parameters.command)
        runtime.watcher = asyncio.create_task(self._watch(runtime, process))

        if runtime.port is not None:
            ready = await self._wait_for_port(
                runtime.port,
                timeout_seconds=self._ready_timeout,
                is_alive=lambda: process.returncode is None and runtime.wanted,
            )
        else:
            ready = await self._survives_grace(process)

        if not runtime.wanted:
            await self._stop_locked(runtime, STATUS_STOPPED)
            return _RESULT_FINAL
        if not ready:
            if process.returncode is not None:
                runtime.last_error = f"The background program stopped before it was ready (exit code {process.returncode}).{self._said(runtime)}"
            else:
                runtime.last_error = (
                    f"The background program did not start listening on port {runtime.port} within {self._ready_timeout:.0f} seconds.{self._said(runtime)}"
                )
            await self._stop_locked(runtime, STATUS_FAILED)
            return _RESULT_RETRY
        runtime.status = STATUS_RUNNING
        if companion.probe is not None and runtime.port is not None:
            runtime.monitor = ProbeMonitor(
                companion.probe,
                port=runtime.port,
                run_secret=run_secret,
                secrets=secrets.values,
                read=self._probe_read,
                sleep=self._probe_sleep,
                get_json=self._probe_get_json,
            )
            runtime.monitor.start()
        return _RESULT_RUNNING

    async def _survives_grace(self, process: Any) -> bool:
        """For a program with no port to wait on: True when it is still alive after the grace period."""
        try:
            await asyncio.wait_for(process.wait(), timeout=self._no_port_grace)
        except asyncio.TimeoutError:
            return True
        return False

    async def _watch(self, runtime: _Runtime, process: Any) -> None:
        returncode = await process.wait()
        if runtime.process is not process or not runtime.wanted or runtime.status != STATUS_RUNNING:
            return
        ran_seconds = time.monotonic() - (runtime.started_at or time.monotonic())
        runtime.status = STATUS_STARTING
        runtime.last_error = f"The background program stopped unexpectedly (exit code {returncode}).{self._said(runtime)}"
        runtime.process = None
        runtime.pid = None
        runtime.watcher = None
        await self._stop_monitor(runtime)
        await self._terminate_group(process.pid, process)
        self._forget_pid(runtime.connection_id)
        runtime.restart_task = asyncio.create_task(self._restart_loop(runtime, ran_seconds))

    @staticmethod
    async def _stop_monitor(runtime: _Runtime) -> None:
        """Stop reading the status page and forget the credentials of the run that ended. The values stay known for hiding them in what its log said."""
        monitor, runtime.monitor = runtime.monitor, None
        runtime.run_secret = None
        runtime.secret_values = {}
        if monitor is not None:
            await monitor.stop()

    async def _restart_loop(self, runtime: _Runtime, ran_seconds: float) -> None:
        if ran_seconds >= self._stable_run:
            runtime.consecutive_failures = 0
        while runtime.wanted:
            runtime.consecutive_failures += 1
            if runtime.consecutive_failures > len(self._backoff):
                runtime.status = STATUS_FAILED
                runtime.last_error = (
                    f"{runtime.last_error or 'The background program stopped.'} It stopped {len(self._backoff) + 1} times in a row, so Basil gave up. Start it again from Settings."
                )
                return
            await self._sleep(self._backoff[runtime.consecutive_failures - 1])
            async with runtime.lock:
                if not runtime.wanted or self._is_alive(runtime):
                    return
                try:
                    _record, companion = self._configured(runtime.connection_id)
                except CompanionError:
                    runtime.status = STATUS_STOPPED
                    return
                runtime.restart_count += 1
                outcome = await self._launch_locked(runtime, companion, wait_for_host=True)
            if outcome != _RESULT_RETRY:
                return

    async def _stop_locked(self, runtime: _Runtime, final_status: str) -> None:
        runtime.status = STATUS_STOPPING
        process = runtime.process
        runtime.process = None
        watcher = runtime.watcher
        runtime.watcher = None
        if watcher is not None and watcher is not asyncio.current_task():
            watcher.cancel()
        await self._stop_monitor(runtime)
        if process is not None:
            await self._terminate_group(process.pid, process)
        runtime.pid = None
        runtime.started_at = None
        if final_status == STATUS_STOPPED:
            runtime.port = None
        runtime.status = final_status
        self._forget_pid(runtime.connection_id)

    async def _terminate_group(self, pid: int, process: Any) -> None:
        """SIGTERM the whole process group, wait for it to empty, then SIGKILL what is left."""
        _signal_group(pid, signal.SIGTERM)
        deadline = time.monotonic() + self._stop_grace
        while _group_alive(pid) and time.monotonic() < deadline:
            await self._sleep(0.05)
        if _group_alive(pid):
            _signal_group(pid, signal.SIGKILL)
            for _ in range(60):
                if not _group_alive(pid):
                    break
                await self._sleep(0.05)
        if process is not None:
            try:
                await asyncio.wait_for(process.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                logger.warning("Background program %s did not report its exit", pid)


def _signal_group(pid: int, sig: int) -> None:
    try:
        os.killpg(pid, sig)
    except (ProcessLookupError, PermissionError):
        pass


def _group_alive(pid: int) -> bool:
    try:
        os.killpg(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _pid_runs(pid: int, executable: str) -> bool:
    """True when the process still exists and its command line contains the recorded executable, which rules out a reused process id."""
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    try:
        output = subprocess.run(["ps", "-p", str(pid), "-o", "command="], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    return executable in output


_supervisor: Optional[CompanionSupervisor] = None


def get_companion_supervisor() -> CompanionSupervisor:
    """The one supervisor for this backend. Its files live under the data directory, in ``local_servers``."""
    global _supervisor
    if _supervisor is None:
        from api.settings import get_settings

        _supervisor = CompanionSupervisor(Path(get_settings().data_dir).expanduser() / "local_servers")
    return _supervisor


def set_companion_supervisor(supervisor: Optional[CompanionSupervisor]) -> None:
    """Replace the shared supervisor. For tests; pass None to reset."""
    global _supervisor
    _supervisor = supervisor
