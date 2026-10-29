"""The watchdog must publish heartbeats while healthy and write every thread's stack when the loop is blocked."""

from __future__ import annotations

import asyncio
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
