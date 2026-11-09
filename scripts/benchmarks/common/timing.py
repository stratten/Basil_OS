"""Timing, repetition, and peak-memory helpers shared by every benchmark."""

from __future__ import annotations

import os
import statistics
import threading
import time
from contextlib import contextmanager
from typing import Any, Callable, Dict, Iterator, List, Optional, Sequence

import psutil


def summarize(values: Sequence[float]) -> Dict[str, Any]:
    """Return count, median, min, max, and sample standard deviation for a list of numbers."""
    cleaned = [float(value) for value in values]
    if not cleaned:
        return {"n": 0, "median": None, "min": None, "max": None, "stdev": None}
    return {
        "n": len(cleaned),
        "median": statistics.median(cleaned),
        "min": min(cleaned),
        "max": max(cleaned),
        "stdev": statistics.stdev(cleaned) if len(cleaned) > 1 else 0.0,
    }


class Stopwatch:
    """Monotonic stopwatch with named laps."""

    def __init__(self) -> None:
        self._start = time.perf_counter()
        self._last = self._start
        self.laps: Dict[str, float] = {}

    def lap(self, name: str) -> float:
        now = time.perf_counter()
        elapsed = now - self._last
        self.laps[name] = elapsed
        self._last = now
        return elapsed

    def total(self) -> float:
        return time.perf_counter() - self._start


class PeakMemorySampler:
    """Sample the resident set size of this process (and its children) and keep the peak in megabytes."""

    def __init__(self, interval_seconds: float = 0.05, pid: Optional[int] = None) -> None:
        self._process = psutil.Process(pid or os.getpid())
        self._interval = interval_seconds
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.peak_mb = 0.0
        self.start_mb = 0.0

    def _rss_mb(self) -> float:
        try:
            total = self._process.memory_info().rss
            for child in self._process.children(recursive=True):
                try:
                    total += child.memory_info().rss
                except psutil.Error:
                    continue
            return total / (1024 * 1024)
        except psutil.Error:
            return 0.0

    def _run(self) -> None:
        while not self._stop.is_set():
            self.peak_mb = max(self.peak_mb, self._rss_mb())
            self._stop.wait(self._interval)

    def __enter__(self) -> "PeakMemorySampler":
        self.start_mb = self._rss_mb()
        self.peak_mb = self.start_mb
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
        self.peak_mb = max(self.peak_mb, self._rss_mb())

    def current_mb(self) -> float:
        return self._rss_mb()


@contextmanager
def cool_down(seconds: float, label: str = "") -> Iterator[None]:
    """Sleep after a block so a long run does not heat the next one."""
    try:
        yield
    finally:
        if seconds > 0:
            if label:
                print(f"[cool-down] {label}: waiting {seconds:.0f}s", flush=True)
            time.sleep(seconds)


def repeat(
    function: Callable[[], Dict[str, float]],
    runs: int,
    cool_seconds: float = 0.0,
    label: str = "",
) -> List[Dict[str, float]]:
    """Run ``function`` ``runs`` times, cooling between runs, and return every run's metric dict."""
    results: List[Dict[str, float]] = []
    for index in range(runs):
        results.append(function())
        if index < runs - 1 and cool_seconds > 0:
            print(f"[cool-down] {label or 'run'} {index + 1}/{runs}: waiting {cool_seconds:.0f}s", flush=True)
            time.sleep(cool_seconds)
    return results


def aggregate_runs(runs: Sequence[Dict[str, float]]) -> Dict[str, Dict[str, Any]]:
    """Summarize each metric across runs."""
    keys: List[str] = []
    for run in runs:
        for key in run:
            if key not in keys:
                keys.append(key)
    return {key: summarize([run[key] for run in runs if key in run and run[key] is not None]) for key in keys}
