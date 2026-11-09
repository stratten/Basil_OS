"""Continuous sampling of Basil's own CPU use so a benchmark run can be flagged when Basil was busy during it.

Basil's backend runs periodic work (automatic activity capture, meeting and audio probes) even when the owner is not using it, so "Basil idle" cannot be assumed. This monitor samples the total CPU percent (one core is 100) of the backend and the client once per second.
A run window whose maximum exceeds BUSY_THRESHOLD_PERCENT is flagged busy and excluded from reported medians; the number of excluded runs is reported.
Depends only on psutil.
"""
from __future__ import annotations

import os
import threading
import time
from typing import Dict, List, Tuple

import psutil

BUSY_THRESHOLD_PERCENT = 100.0


class BasilCpuMonitor:
    def __init__(self, interval: float = 1.0) -> None:
        self._interval = interval
        self._stop = threading.Event()
        self._samples: List[Tuple[float, float]] = []
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._run, daemon=True)

    @staticmethod
    def _find() -> List[psutil.Process]:
        me = os.getpid()
        found = []
        for proc in psutil.process_iter(["pid", "cmdline"]):
            try:
                cmd = " ".join(proc.info["cmdline"] or [])
            except psutil.Error:
                continue
            if proc.info["pid"] != me and ("uvicorn api.main" in cmd or "BasilClient" in cmd or "Basil Validation" in cmd):
                found.append(proc)
        return found

    def _run(self) -> None:
        procs = self._find()
        for proc in procs:
            try:
                proc.cpu_percent(None)
            except psutil.Error:
                pass
        ticks = 0
        while not self._stop.wait(self._interval):
            ticks += 1
            if ticks % 15 == 0:
                procs = self._find()
                for proc in procs:
                    try:
                        proc.cpu_percent(None)
                    except psutil.Error:
                        pass
                continue
            total = 0.0
            for proc in procs:
                try:
                    total += proc.cpu_percent(None)
                except psutil.Error:
                    pass
            with self._lock:
                self._samples.append((time.perf_counter(), total))

    def start(self) -> "BasilCpuMonitor":
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2)

    def window(self, start: float, end: float) -> Dict[str, float]:
        """Mean and maximum Basil CPU percent over a perf_counter interval. Returns zeros with samples=0 when the window is shorter than one sample."""
        with self._lock:
            values = [v for t, v in self._samples if start <= t <= end + self._interval]
        if not values:
            return {"mean": 0.0, "max": 0.0, "samples": 0, "busy": False}
        return {"mean": sum(values) / len(values), "max": max(values), "samples": len(values), "busy": max(values) > BUSY_THRESHOLD_PERCENT}
