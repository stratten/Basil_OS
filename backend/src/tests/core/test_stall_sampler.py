"""The out-of-process stall sampler must sample a frozen backend once per stall and never on a healthy or sleeping one."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from api.core.runtime import stall_sampler
from api.core.runtime.stall_sampler import StallMonitor

BACKEND_SRC = str(Path(__file__).resolve().parents[2])
IS_MAC_WITH_SAMPLE = sys.platform == "darwin" and os.path.exists("/usr/bin/sample")


def _sidecar_pid_from(stdout: str, stderr: str) -> int:
    # The backend's logging setup prints a literal backslash-n without a real newline, so the marker can follow other text on the same line.
    match = re.search(r"SIDECAR (\d+|None)", stdout)
    assert match, f"child printed no SIDECAR marker\nstdout: {stdout[-1500:]}\nstderr: {stderr[-1500:]}"
    assert match.group(1) != "None", f"the sidecar did not start\nstdout: {stdout[-1500:]}"
    return int(match.group(1))


def test_no_sample_while_the_heartbeat_keeps_changing():
    monitor = StallMonitor(stale_after=10.0, cooldown=600.0)

    assert [monitor.observe(index, float(index * 3)) for index in range(20)] == [False] * 20


def test_one_sample_when_the_heartbeat_goes_stale_and_none_for_the_rest_of_that_stall():
    monitor = StallMonitor(stale_after=10.0, cooldown=600.0)
    monitor.observe(1, 0.0)

    results = [monitor.observe(1, float(second)) for second in range(1, 40)]

    assert results.index(True) == 9
    assert results.count(True) == 1
    assert monitor.stale_for(39.0) == 39.0


def test_a_missing_heartbeat_file_counts_as_unchanged_not_as_a_new_beat():
    monitor = StallMonitor(stale_after=5.0, cooldown=600.0)
    monitor.observe(7, 0.0)

    assert [monitor.observe(None, float(second)) for second in range(1, 8)].count(True) == 1


def test_a_second_stall_inside_the_cooldown_is_not_sampled_but_one_after_it_is():
    monitor = StallMonitor(stale_after=5.0, cooldown=100.0)
    monitor.observe(1, 0.0)
    assert monitor.observe(1, 5.0) is True

    monitor.observe(2, 6.0)
    assert monitor.observe(2, 50.0) is False

    monitor.observe(3, 60.0)
    assert monitor.observe(3, 106.0) is True


def test_recovery_resets_the_stall_so_a_slow_but_alive_loop_is_never_sampled():
    monitor = StallMonitor(stale_after=10.0, cooldown=0.0)
    monitor.observe(1, 0.0)

    assert monitor.observe(1, 9.0) is False
    assert monitor.observe(2, 9.5) is False
    assert monitor.observe(2, 19.0) is False


def test_run_samples_a_real_stale_file_once_and_exits_when_the_parent_is_gone(tmp_path):
    heartbeat = tmp_path / "loop_heartbeat"
    heartbeat.touch()
    sampled = []
    clock_value = [0.0]
    parent_checks = [0]

    def clock():
        return clock_value[0]

    def sleep(seconds):
        clock_value[0] += 1.0

    def parent_alive():
        parent_checks[0] += 1
        return parent_checks[0] <= 30

    stall_sampler.run(
        parent_pid=123,
        heartbeat_path=str(heartbeat),
        output_dir=str(tmp_path),
        stale_after=10.0,
        duration=5,
        cooldown=600.0,
        clock=clock,
        sleep=sleep,
        sampler=lambda pid, output_dir, duration, stale: sampled.append((pid, output_dir, duration, round(stale))),
        parent_alive=parent_alive,
    )

    assert sampled == [(123, str(tmp_path), 5, 10)]
    assert parent_checks[0] == 31


def test_main_rejects_wrong_arguments():
    assert stall_sampler.main(["stall_sampler.py"]) == 2


@pytest.mark.skipif(not IS_MAC_WITH_SAMPLE, reason="needs macOS /usr/bin/sample")
def test_a_backend_that_holds_the_gil_forever_is_sampled_from_outside_and_the_sidecar_is_cleaned_up(tmp_path):
    script = textwrap.dedent(
        f"""
        import asyncio, ctypes, os, sys
        sys.path.insert(0, {BACKEND_SRC!r})
        from pathlib import Path
        from api.core.runtime import event_loop_watchdog as module

        module.SAMPLE_DURATION_SECONDS = 1

        async def main():
            watchdog = module.EventLoopWatchdog(
                heartbeat_interval=0.2, stall_dump_seconds=120.0, check_interval=0.5, publish_interval=60.0,
                diagnostics_dir=Path({str(tmp_path)!r}), publisher=None, sampler_stale_seconds=3.0,
            )
            await watchdog.start()
            print("SIDECAR", watchdog._sidecar_pid, flush=True)
            await asyncio.sleep(0.8)
            ctypes.PyDLL(None).sleep(9)
            await asyncio.sleep(0.5)
            await watchdog.stop()
            print("STOPPED", flush=True)

        asyncio.run(main())
        """
    )

    completed = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=90)

    assert completed.returncode == 0, completed.stderr[-2000:]
    sidecar_pid = _sidecar_pid_from(completed.stdout, completed.stderr)
    samples = list(tmp_path.glob("sample-*.txt"))
    assert len(samples) == 1
    sample_text = samples[0].read_text(encoding="utf-8", errors="replace")
    assert "nanosleep" in sample_text
    assert "stall sampler: backend heartbeat stale" in (tmp_path / "loop_stalls.log").read_text(encoding="utf-8")
    with pytest.raises(ProcessLookupError):
        os.kill(sidecar_pid, 0)


@pytest.mark.skipif(not IS_MAC_WITH_SAMPLE, reason="needs macOS /usr/bin/sample")
def test_a_healthy_backend_is_never_sampled_and_stopping_it_stops_the_sidecar(tmp_path):
    script = textwrap.dedent(
        f"""
        import asyncio, sys
        sys.path.insert(0, {BACKEND_SRC!r})
        from pathlib import Path
        from api.core.runtime import event_loop_watchdog as module

        async def main():
            watchdog = module.EventLoopWatchdog(
                heartbeat_interval=0.1, stall_dump_seconds=120.0, check_interval=0.5, publish_interval=60.0,
                diagnostics_dir=Path({str(tmp_path)!r}), publisher=None, sampler_stale_seconds=2.0,
            )
            await watchdog.start()
            print("SIDECAR", watchdog._sidecar_pid, flush=True)
            await asyncio.sleep(4.5)
            await watchdog.stop()

        asyncio.run(main())
        """
    )

    completed = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=60)

    assert completed.returncode == 0, completed.stderr[-2000:]
    sidecar_pid = _sidecar_pid_from(completed.stdout, completed.stderr)
    assert list(tmp_path.glob("sample-*.txt")) == []
    assert (tmp_path / "loop_stalls.log").read_text(encoding="utf-8") == ""
    with pytest.raises(ProcessLookupError):
        os.kill(sidecar_pid, 0)


@pytest.mark.skipif(not IS_MAC_WITH_SAMPLE, reason="needs macOS /usr/bin/sample")
def test_the_sidecar_exits_by_itself_when_the_backend_is_killed(tmp_path):
    script = textwrap.dedent(
        f"""
        import asyncio, os, signal, sys
        sys.path.insert(0, {BACKEND_SRC!r})
        from pathlib import Path
        from api.core.runtime import event_loop_watchdog as module

        async def main():
            watchdog = module.EventLoopWatchdog(
                heartbeat_interval=0.1, stall_dump_seconds=120.0, check_interval=0.5, publish_interval=60.0,
                diagnostics_dir=Path({str(tmp_path)!r}), publisher=None,
            )
            await watchdog.start()
            print("SIDECAR", watchdog._sidecar_pid, flush=True)
            await asyncio.sleep(0.5)
            os.kill(os.getpid(), signal.SIGKILL)

        asyncio.run(main())
        """
    )

    output = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=60).stdout
    sidecar_pid = _sidecar_pid_from(output, "")

    deadline = time.monotonic() + 8.0
    alive = True
    while alive and time.monotonic() < deadline:
        try:
            os.kill(sidecar_pid, 0)
            time.sleep(0.2)
        except ProcessLookupError:
            alive = False

    assert alive is False
