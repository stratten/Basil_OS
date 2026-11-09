"""Out-of-process stall sampler for the backend, run as ``python -S -E stall_sampler.py``.

The in-process watchdog thread cannot report a freeze in which a thread holds the GIL, because it needs the GIL to run.
Backend logs from 2026-10-30 and 2026-11-04 show exactly that: the only evidence was the C-level faulthandler dump, with no native stacks and no log line.
This script runs in its own tiny interpreter, watches the modification time of a heartbeat file that the backend's event loop touches every beat, and when that file stops changing it runs ``/usr/bin/sample`` against the backend from outside.
It uses only the standard library and imports nothing from ``api`` so it cannot be blocked by anything the backend is blocked on.
The stale time is measured with the monotonic clock, which does not advance while the Mac sleeps, so waking from sleep does not look like a stall.
It exits on its own when the backend process that launched it is gone.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from typing import Callable, Optional

SAMPLE_BINARY = "/usr/bin/sample"
POLL_SECONDS = 1.0


class StallMonitor:
    """Decides when a stalled heartbeat file deserves one native sample."""

    def __init__(self, stale_after: float, cooldown: float) -> None:
        self.stale_after = stale_after
        self.cooldown = cooldown
        self._last_mtime: Optional[int] = None
        self._changed_at: Optional[float] = None
        self._sampled_this_stall = False
        self._last_sample_at: Optional[float] = None

    def stale_for(self, now: float) -> float:
        return 0.0 if self._changed_at is None else now - self._changed_at

    def observe(self, mtime_ns: Optional[int], now: float) -> bool:
        """Record one look at the heartbeat file and return True when a sample should be taken now."""
        if self._changed_at is None or (mtime_ns is not None and mtime_ns != self._last_mtime):
            self._last_mtime = mtime_ns
            self._changed_at = now
            self._sampled_this_stall = False
            return False
        if self._sampled_this_stall or now - self._changed_at < self.stale_after:
            return False
        if self._last_sample_at is not None and now - self._last_sample_at < self.cooldown:
            return False
        self._sampled_this_stall = True
        self._last_sample_at = now
        return True


def _heartbeat_mtime_ns(path: str) -> Optional[int]:
    try:
        return os.stat(path).st_mtime_ns
    except OSError:
        return None


def _append_log(log_path: str, message: str) -> None:
    try:
        with open(log_path, "a", encoding="utf-8") as handle:
            handle.write(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n")
    except OSError:
        pass


def take_sample(parent_pid: int, output_dir: str, duration: int, stale_seconds: float) -> None:
    output_path = os.path.join(output_dir, f"sample-{time.strftime('%Y%m%d-%H%M%S')}.txt")
    log_path = os.path.join(output_dir, "loop_stalls.log")
    _append_log(log_path, f"stall sampler: backend heartbeat stale for {stale_seconds:.0f}s; native sample of pid {parent_pid} -> {output_path}")
    try:
        subprocess.run(
            [SAMPLE_BINARY, str(parent_pid), str(duration), "-file", output_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=duration + 60,
        )
    except Exception as exc:
        _append_log(log_path, f"stall sampler: native sample failed: {exc}")


def run(
    parent_pid: int,
    heartbeat_path: str,
    output_dir: str,
    stale_after: float,
    duration: int,
    cooldown: float,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    sampler: Callable[[int, str, int, float], None] = take_sample,
    parent_alive: Optional[Callable[[], bool]] = None,
) -> None:
    monitor = StallMonitor(stale_after, cooldown)
    is_parent_alive = parent_alive or (lambda: os.getppid() == parent_pid)
    while is_parent_alive():
        now = clock()
        if monitor.observe(_heartbeat_mtime_ns(heartbeat_path), now):
            sampler(parent_pid, output_dir, duration, monitor.stale_for(now))
        sleep(POLL_SECONDS)


def main(argv: list[str]) -> int:
    if len(argv) != 7 or not os.path.exists(SAMPLE_BINARY):
        return 2
    parent_pid, heartbeat_path, output_dir = int(argv[1]), argv[2], argv[3]
    run(parent_pid, heartbeat_path, output_dir, float(argv[4]), int(argv[5]), float(argv[6]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
