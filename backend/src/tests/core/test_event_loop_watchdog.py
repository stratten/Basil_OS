"""The watchdog must publish heartbeats while healthy and write every thread's stack when the loop is blocked."""

from __future__ import annotations

import asyncio
import faulthandler
import os
import signal
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from api.core.runtime.event_loop_watchdog import HEARTBEAT_EVENT_TYPE, EventLoopWatchdog

BACKEND_SRC = str(Path(__file__).resolve().parents[2])


@pytest.mark.asyncio
async def test_heartbeats_are_published_while_the_loop_is_healthy(tmp_path):
    published = []

    async def publisher(payload):
        published.append(payload)

    watchdog = EventLoopWatchdog(
        heartbeat_interval=0.05,
        publish_interval=0.05,
        stall_dump_seconds=30.0,
        check_interval=5.0,
        diagnostics_dir=tmp_path,
        publisher=publisher,
        capture_native_sample=False,
    )
    await watchdog.start()
    try:
        await asyncio.sleep(0.4)
    finally:
        await watchdog.stop()

    assert len(published) >= 3
    assert all(item["event_type"] == HEARTBEAT_EVENT_TYPE for item in published)
    assert all(isinstance(item["sent_at"], float) and item["loop_lag_ms"] >= 0 for item in published)


@pytest.mark.asyncio
async def test_a_failing_or_slow_publisher_does_not_stop_the_beat(tmp_path, monkeypatch):
    from api.core.runtime import event_loop_watchdog as module

    monkeypatch.setattr(module, "PUBLISH_TIMEOUT_SECONDS", 0.05)
    attempts = []

    async def hanging_publisher(payload):
        attempts.append(payload)
        await asyncio.sleep(10)

    watchdog = EventLoopWatchdog(
        heartbeat_interval=0.05,
        publish_interval=0.05,
        stall_dump_seconds=30.0,
        diagnostics_dir=tmp_path,
        publisher=hanging_publisher,
        capture_native_sample=False,
    )
    await watchdog.start()
    try:
        await asyncio.sleep(0.4)
        beat_age = time.monotonic() - watchdog._last_beat
    finally:
        await watchdog.stop()

    assert len(attempts) >= 2
    assert beat_age < 0.3


def test_a_blocked_loop_writes_the_blocking_frame_to_the_stall_log(tmp_path):
    script = textwrap.dedent(
        f"""
        import asyncio, sys, time
        sys.path.insert(0, {BACKEND_SRC!r})
        from pathlib import Path
        from api.core.runtime.event_loop_watchdog import EventLoopWatchdog

        def block_the_loop_for_the_stall_test():
            time.sleep(6)

        async def main():
            watchdog = EventLoopWatchdog(
                heartbeat_interval=0.2,
                stall_dump_seconds=2.0,
                check_interval=0.5,
                publish_interval=60.0,
                diagnostics_dir=Path({str(tmp_path)!r}),
                publisher=None,
                capture_native_sample=False,
            )
            await watchdog.start()
            await asyncio.sleep(0.6)
            block_the_loop_for_the_stall_test()
            await asyncio.sleep(0.5)
            await watchdog.stop()

        asyncio.run(main())
        """
    )
    started = time.monotonic()
    completed = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=60)

    assert completed.returncode == 0, completed.stderr[-2000:]
    log_text = (tmp_path / "loop_stalls.log").read_text(encoding="utf-8")
    assert "block_the_loop_for_the_stall_test" in log_text
    assert "Event loop has not advanced" in log_text
    assert time.monotonic() - started < 40


@pytest.mark.asyncio
async def test_a_healthy_loop_writes_nothing_to_the_stall_log(tmp_path):
    watchdog = EventLoopWatchdog(
        heartbeat_interval=0.05,
        stall_dump_seconds=1.0,
        check_interval=0.1,
        publish_interval=60.0,
        diagnostics_dir=tmp_path,
        publisher=None,
        capture_native_sample=False,
    )
    await watchdog.start()
    try:
        await asyncio.sleep(1.5)
    finally:
        await watchdog.stop()

    assert (tmp_path / "loop_stalls.log").read_text(encoding="utf-8") == ""


def _wait_for_text(path: Path, needle: str, timeout: float = 3.0) -> str:
    deadline = time.monotonic() + timeout
    text = ""
    while time.monotonic() < deadline:
        text = path.read_text(encoding="utf-8") if path.exists() else ""
        if needle in text:
            return text
        time.sleep(0.02)
    return text


@pytest.mark.asyncio
@pytest.mark.skipif(not hasattr(signal, "SIGUSR1"), reason="SIGUSR1 is not available on this platform")
async def test_sigusr1_writes_the_function_a_blocked_thread_is_waiting_in(tmp_path):
    import threading

    held = threading.Lock()
    held.acquire()
    started = threading.Event()

    def waits_for_the_model_lock_forever():
        started.set()
        held.acquire()

    worker = threading.Thread(target=waits_for_the_model_lock_forever, name="stuck-worker", daemon=True)
    worker.start()
    assert started.wait(2.0)

    watchdog = EventLoopWatchdog(
        heartbeat_interval=0.05,
        stall_dump_seconds=30.0,
        diagnostics_dir=tmp_path,
        publisher=lambda payload: asyncio.sleep(0),
        capture_native_sample=False,
    )
    await watchdog.start()
    try:
        await asyncio.sleep(0.2)
        assert watchdog.stall_log_path.read_text(encoding="utf-8") == ""

        os.kill(os.getpid(), signal.SIGUSR1)
        dump = _wait_for_text(watchdog.stall_log_path, "waits_for_the_model_lock_forever")
    finally:
        await watchdog.stop()
        held.release()
        worker.join(timeout=2.0)

    assert "most recent call first" in dump
    assert "waits_for_the_model_lock_forever" in dump


@pytest.mark.asyncio
@pytest.mark.skipif(not hasattr(signal, "SIGUSR1"), reason="SIGUSR1 is not available on this platform")
async def test_the_signal_handler_is_removed_when_the_watchdog_stops(tmp_path):
    watchdog = EventLoopWatchdog(
        heartbeat_interval=0.05,
        stall_dump_seconds=30.0,
        diagnostics_dir=tmp_path,
        publisher=lambda payload: asyncio.sleep(0),
        capture_native_sample=False,
    )
    await watchdog.start()
    assert watchdog._stack_dump_signal == int(signal.SIGUSR1)
    await watchdog.stop()

    assert watchdog._stack_dump_signal is None
    assert faulthandler.unregister(signal.SIGUSR1) is False
