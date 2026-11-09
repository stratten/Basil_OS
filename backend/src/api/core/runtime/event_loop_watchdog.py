"""Detect a stalled event loop, record where it is stuck, and tell connected clients the backend is alive.

Three cooperating parts:

* A beat task on the event loop re-arms ``faulthandler.dump_traceback_later``.
  The faulthandler timer runs on its own C thread and needs neither the GIL nor the loop, so if the loop stops beating, every thread's Python stack is written to ``loop_stalls.log`` after ``stall_dump_seconds``.
  There is only one faulthandler timer per process; re-arming replaces the previous one.
* A publish task broadcasts ``backend_heartbeat`` events so clients can tell a frozen backend (open socket, no heartbeats) from a healthy one.
* A daemon thread notices a stalled beat, logs it, and on macOS captures native stacks with ``/usr/bin/sample``.
  ``sample`` is started with ``os.posix_spawn`` because ``subprocess`` can itself hang in a process that is already wedged.
* A sidecar process (``stall_sampler.py``) that watches a heartbeat file the beat task touches and runs ``sample`` from outside when the file goes stale.
  The daemon thread above needs the GIL, so it is blind when a thread holds the GIL for good; the sidecar is not.
  While the sidecar is alive it owns native sampling and the in-process thread only logs.
"""

from __future__ import annotations

import asyncio
import faulthandler
import os
import signal
import sys
import threading
import time
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Optional, TextIO

from api.core.logging.api_logger import api_logger

logger = api_logger.getChild("event_loop_watchdog")

HEARTBEAT_EVENT_TYPE = "backend_heartbeat"
SAMPLE_BINARY = "/usr/bin/sample"
SAMPLE_DURATION_SECONDS = 5
SAMPLE_COOLDOWN_SECONDS = 600.0
LAG_WARNING_SECONDS = 2.0
PUBLISH_TIMEOUT_SECONDS = 1.5
HEARTBEAT_FILE_NAME = "loop_heartbeat"
SAMPLER_SCRIPT = Path(__file__).with_name("stall_sampler.py")
SAMPLER_STALE_SECONDS = 10.0

Publisher = Callable[[Dict[str, Any]], Awaitable[Any]]


async def _broadcast_to_clients(payload: Dict[str, Any]) -> Any:
    from api.services.websocket_connection_manager import broadcast_heartbeat

    return await broadcast_heartbeat(payload, log=logger)


class EventLoopWatchdog:
    """Owns the beat task, the heartbeat publisher, and the stall-watching thread."""

    def __init__(
        self,
        *,
        heartbeat_interval: float = 1.0,
        stall_dump_seconds: float = 15.0,
        publish_interval: float = 2.0,
        check_interval: float = 5.0,
        diagnostics_dir: Optional[Path] = None,
        publisher: Optional[Publisher] = None,
        capture_native_sample: bool = True,
        sample_sidecar: Optional[bool] = None,
        sampler_stale_seconds: float = SAMPLER_STALE_SECONDS,
    ) -> None:
        self.heartbeat_interval = heartbeat_interval
        self.stall_dump_seconds = stall_dump_seconds
        self.publish_interval = publish_interval
        self.check_interval = check_interval
        self.diagnostics_dir = Path(diagnostics_dir) if diagnostics_dir else Path.home() / ".basil" / "diagnostics"
        self._publisher = publisher or _broadcast_to_clients
        self._capture_native_sample = capture_native_sample
        self._use_sample_sidecar = capture_native_sample if sample_sidecar is None else sample_sidecar
        self._sampler_stale_seconds = sampler_stale_seconds
        self._sidecar_pid: Optional[int] = None
        self._stall_log: Optional[TextIO] = None
        self._stack_dump_signal: Optional[int] = None
        self._beat_task: Optional[asyncio.Task] = None
        self._publish_task: Optional[asyncio.Task] = None
        self._thread: Optional[threading.Thread] = None
        self._stop_thread = threading.Event()
        self._last_beat = time.monotonic()
        self._loop_lag_ms = 0
        self._stall_reported = False
        self._last_sample_at: Optional[float] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    @property
    def stall_log_path(self) -> Path:
        return self.diagnostics_dir / "loop_stalls.log"

    @property
    def heartbeat_file_path(self) -> Path:
        return self.diagnostics_dir / HEARTBEAT_FILE_NAME

    async def start(self) -> None:
        if self._beat_task is not None:
            return
        self.diagnostics_dir.mkdir(parents=True, exist_ok=True)
        self._stall_log = open(self.stall_log_path, "a", buffering=1, encoding="utf-8")
        self._register_stack_dump_signal()
        self._loop = asyncio.get_running_loop()
        self._last_beat = time.monotonic()
        self._arm_dump_timer()
        self._touch_heartbeat_file()
        if self._use_sample_sidecar:
            self._start_sidecar()
        self._beat_task = asyncio.create_task(self._beat_loop(), name="event-loop-watchdog-beat")
        self._publish_task = asyncio.create_task(self._publish_loop(), name="event-loop-watchdog-publish")
        self._stop_thread.clear()
        self._thread = threading.Thread(target=self._watch_thread, name="event-loop-watchdog", daemon=True)
        self._thread.start()
        logger.info("Event-loop watchdog started (stall dump after %.0fs, log %s)", self.stall_dump_seconds, self.stall_log_path)

    async def stop(self) -> None:
        for task in (self._beat_task, self._publish_task):
            if task is not None:
                task.cancel()
        for task in (self._beat_task, self._publish_task):
            if task is not None:
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
        self._beat_task = None
        self._publish_task = None
        self._stop_thread.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        faulthandler.cancel_dump_traceback_later()
        self._unregister_stack_dump_signal()
        self._stop_sidecar()
        if self._stall_log is not None:
            self._stall_log.close()
            self._stall_log = None

    def _register_stack_dump_signal(self) -> None:
        """Let ``kill -USR1 <backend pid>`` write every thread's Python stack to the stall log on demand.

        The loop watchdog only fires when the event loop stops. A task that waits forever on a lock while the loop stays healthy leaves no trace, and this dump shows which thread holds the lock. The handler runs in C without the GIL, so it works even when every Python thread is blocked.
        """
        signal_number = getattr(signal, "SIGUSR1", None)
        if signal_number is None or self._stall_log is None:
            return
        try:
            faulthandler.register(signal_number, file=self._stall_log, all_threads=True, chain=False)
            self._stack_dump_signal = int(signal_number)
        except (AttributeError, OSError, RuntimeError, ValueError) as exc:
            logger.debug("On-demand stack dump signal could not be registered: %s", exc)

    def _unregister_stack_dump_signal(self) -> None:
        signal_number, self._stack_dump_signal = self._stack_dump_signal, None
        if signal_number is None:
            return
        try:
            faulthandler.unregister(signal_number)
        except (AttributeError, OSError, RuntimeError, ValueError):
            pass

    def _touch_heartbeat_file(self) -> None:
        try:
            os.utime(self.heartbeat_file_path)
        except FileNotFoundError:
            try:
                self.heartbeat_file_path.touch()
            except OSError:
                pass
        except OSError:
            pass

    def _start_sidecar(self) -> None:
        if sys.platform != "darwin" or not os.path.exists(SAMPLE_BINARY) or not SAMPLER_SCRIPT.exists():
            return
        arguments = [
            sys.executable, "-S", "-E", str(SAMPLER_SCRIPT), str(os.getpid()), str(self.heartbeat_file_path),
            str(self.diagnostics_dir), str(self._sampler_stale_seconds), str(SAMPLE_DURATION_SECONDS), str(SAMPLE_COOLDOWN_SECONDS),
        ]
        try:
            self._sidecar_pid = os.posix_spawn(sys.executable, arguments, dict(os.environ))
            logger.info("Stall sampler sidecar started (pid %s)", self._sidecar_pid)
        except Exception as exc:
            self._sidecar_pid = None
            logger.warning("Stall sampler sidecar could not be started; in-process sampling stays active: %s", exc)

    def _sidecar_running(self) -> bool:
        if self._sidecar_pid is None:
            return False
        try:
            reaped, _status = os.waitpid(self._sidecar_pid, os.WNOHANG)
        except ChildProcessError:
            reaped = self._sidecar_pid
        if reaped:
            logger.warning("Stall sampler sidecar exited; in-process sampling is active again")
            self._sidecar_pid = None
            return False
        return True

    def _stop_sidecar(self) -> None:
        pid, self._sidecar_pid = self._sidecar_pid, None
        if pid is None:
            return
        try:
            os.kill(pid, signal.SIGTERM)
            deadline = time.monotonic() + 2.0
            while time.monotonic() < deadline:
                reaped, _status = os.waitpid(pid, os.WNOHANG)
                if reaped:
                    return
                time.sleep(0.02)
            os.kill(pid, signal.SIGKILL)
            os.waitpid(pid, 0)
        except (ProcessLookupError, ChildProcessError):
            pass
        except Exception as exc:
            logger.debug("Stall sampler sidecar shutdown skipped: %s", exc)

    def _arm_dump_timer(self) -> None:
        if self._stall_log is not None:
            faulthandler.dump_traceback_later(self.stall_dump_seconds, repeat=False, file=self._stall_log)

    async def _beat_loop(self) -> None:
        expected = time.monotonic() + self.heartbeat_interval
        while True:
            await asyncio.sleep(self.heartbeat_interval)
            now = time.monotonic()
            lag = max(0.0, now - expected)
            self._loop_lag_ms = int(lag * 1000)
            if lag > LAG_WARNING_SECONDS:
                logger.warning("Event loop was blocked for %.1fs", lag)
            self._last_beat = now
            self._arm_dump_timer()
            self._touch_heartbeat_file()
            expected = now + self.heartbeat_interval

    async def _publish_loop(self) -> None:
        while True:
            await asyncio.sleep(self.publish_interval)
            payload = {
                "event_type": HEARTBEAT_EVENT_TYPE,
                "sent_at": time.time(),
                "loop_lag_ms": self._loop_lag_ms,
            }
            try:
                await asyncio.wait_for(self._publisher(payload), PUBLISH_TIMEOUT_SECONDS)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.debug("Heartbeat publish skipped: %s", exc)

    def _watch_thread(self) -> None:
        while not self._stop_thread.wait(self.check_interval):
            if self._loop is not None and self._loop.is_closed():
                faulthandler.cancel_dump_traceback_later()
                return
            age = time.monotonic() - self._last_beat
            if age < self.stall_dump_seconds:
                self._stall_reported = False
                continue
            if self._stall_reported:
                continue
            self._stall_reported = True
            self._report_stall(age)

    def _report_stall(self, age: float) -> None:
        message = f"Event loop has not advanced for {age:.0f}s; thread stacks are in {self.stall_log_path}"
        logger.warning(message)
        if self._stall_log is not None:
            try:
                self._stall_log.write(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n")
            except Exception:
                pass
        if self._capture_native_sample:
            self._capture_sample()

    def _capture_sample(self) -> None:
        if self._sidecar_running():
            return
        now = time.monotonic()
        if self._last_sample_at is not None and now - self._last_sample_at < SAMPLE_COOLDOWN_SECONDS:
            return
        if sys.platform != "darwin" or not os.path.exists(SAMPLE_BINARY):
            return
        self._last_sample_at = now
        output_path = self.diagnostics_dir / f"sample-{time.strftime('%Y%m%d-%H%M%S')}.txt"
        try:
            pid = os.posix_spawn(
                SAMPLE_BINARY,
                [SAMPLE_BINARY, str(os.getpid()), str(SAMPLE_DURATION_SECONDS), "-file", str(output_path)],
                dict(os.environ),
            )
            logger.warning("Native stack sample started (pid %s) -> %s", pid, output_path)
            os.waitpid(pid, 0)
        except Exception as exc:
            logger.warning("Native stack sample could not be captured: %s", exc)


_WATCHDOG: Optional[EventLoopWatchdog] = None


async def start_event_loop_watchdog() -> EventLoopWatchdog:
    """Start the process-wide watchdog once."""
    global _WATCHDOG
    if _WATCHDOG is None:
        _WATCHDOG = EventLoopWatchdog()
    await _WATCHDOG.start()
    return _WATCHDOG


async def stop_event_loop_watchdog() -> None:
    global _WATCHDOG
    if _WATCHDOG is not None:
        await _WATCHDOG.stop()
        _WATCHDOG = None
