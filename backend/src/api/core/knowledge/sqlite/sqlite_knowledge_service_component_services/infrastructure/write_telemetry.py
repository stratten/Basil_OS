"""Timing for the SQLite write slot, so a slow write can be traced to the writer that held the slot instead of guessed at.

Every writer against one database file takes turns through the write coordinator in ``connection.py``. A write that feels slow has three possible causes, and the lines written here tell them apart:

- It waited behind another writer (``sqlite-write-waited``, which names the writer that was holding the slot when it queued).
- A writer held the slot for a long time (``sqlite-write-slot-held``). The hold is split into statement time (including SQLite's own busy waits), commit time (where SQLite syncs the disk and may checkpoint the write-ahead log), and idle time (the transaction stayed open while its caller did something else, such as awaiting a model, a network call, or a tool).
- Neither happened, so the delay is somewhere other than the write slot.

A ``sqlite-write-summary`` line, at most one per minute while writes occur, gives the baseline between the slow events. Statements are summarized by their first words only, never their values.

Everything here is failure-isolated: telemetry must never change how a write behaves, so every public function swallows its own errors.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# The backend's log handlers sit on the "api.main" logger and it does not propagate, so only its children reach the log file. A logger named after this module's path would drop these lines without a trace.
telemetry_logger = logging.getLogger("api.main.sqlite_write_telemetry")

SLOW_WAIT_SECONDS = 0.25
SLOW_HOLD_SECONDS = 0.25
WARNING_SECONDS = 2.0
SUMMARY_INTERVAL_SECONDS = 60.0


@dataclass(frozen=True)
class AdmissionInfo:
    """What a writer learned while it waited for the write slot."""

    wait_seconds: float
    queued_ahead: int
    blocked_by_operation: Optional[str]
    blocked_by_statement: Optional[str]
    blocked_by_held_seconds: Optional[float]


@dataclass
class HoldStats:
    """Timing for one admission, from the first mutating statement to the commit, rollback, or close that ends it. One connection is used by one thread at a time, so no lock is needed."""

    acquired_at: float
    wait_seconds: float
    first_statement: str = ""
    statements: int = 0
    statement_seconds: float = 0.0
    commit_seconds: float = 0.0


def wal_megabytes(db_path: str) -> Optional[float]:
    """Size of the write-ahead log beside the database, or None when there is none."""
    try:
        return round(os.path.getsize(f"{db_path}-wal") / 1048576, 1)
    except OSError:
        return None


def _level(seconds: float) -> int:
    return logging.WARNING if seconds >= WARNING_SECONDS else logging.INFO


class WriteTelemetry:
    """Rolling one-minute totals for one database file."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._lock = threading.Lock()
        self._window_started = time.monotonic()
        self._reset()

    def _reset(self) -> None:
        self._writes = 0
        self._wait_total = 0.0
        self._wait_max = 0.0
        self._hold_total = 0.0
        self._hold_max = 0.0
        self._slow_waits = 0
        self._slow_holds = 0

    def record(self, wait_seconds: float, hold_seconds: float) -> Optional[str]:
        """Add one finished admission; return the summary line when the window has run its course."""
        with self._lock:
            self._writes += 1
            self._wait_total += wait_seconds
            self._wait_max = max(self._wait_max, wait_seconds)
            self._hold_total += hold_seconds
            self._hold_max = max(self._hold_max, hold_seconds)
            self._slow_waits += 1 if wait_seconds >= SLOW_WAIT_SECONDS else 0
            self._slow_holds += 1 if hold_seconds >= SLOW_HOLD_SECONDS else 0
            now = time.monotonic()
            window = now - self._window_started
            if window < SUMMARY_INTERVAL_SECONDS:
                return None
            summary = (
                "[AgentTelemetry] sqlite-write-summary window_seconds=%.0f writes=%d wait_total=%.2f wait_max=%.2f "
                "hold_total=%.2f hold_max=%.2f slow_waits=%d slow_holds=%d wal_mb=%s db=%s"
                % (
                    window,
                    self._writes,
                    self._wait_total,
                    self._wait_max,
                    self._hold_total,
                    self._hold_max,
                    self._slow_waits,
                    self._slow_holds,
                    wal_megabytes(self.db_path),
                    Path(self.db_path).name,
                )
            )
            self._window_started = now
            self._reset()
            return summary


def report_wait(
    db_path: str,
    info: AdmissionInfo,
    *,
    operation_name: str,
    statement: str,
    on_event_loop: bool,
    thread_name: str,
    task_name: Optional[str],
) -> None:
    """Log a writer that had to queue for longer than the slow-wait threshold."""
    try:
        if info.wait_seconds < SLOW_WAIT_SECONDS:
            return
        held = info.blocked_by_held_seconds
        telemetry_logger.log(
            _level(info.wait_seconds),
            "[AgentTelemetry] sqlite-write-waited seconds=%.2f queued_ahead=%d blocked_by_operation=%s "
            "blocked_by_statement=%r blocked_by_held_seconds=%s operation=%s statement=%r on_event_loop=%s "
            "thread=%s task=%s db=%s wal_mb=%s",
            info.wait_seconds,
            info.queued_ahead,
            info.blocked_by_operation,
            info.blocked_by_statement,
            "n/a" if held is None else "%.2f" % held,
            operation_name,
            statement,
            on_event_loop,
            thread_name,
            task_name,
            Path(db_path).name,
            wal_megabytes(db_path),
        )
    except Exception:
        pass


def report_release(
    telemetry: WriteTelemetry,
    stats: HoldStats,
    *,
    hold_seconds: float,
    queued_behind: int,
    operation_name: str,
    statement: str,
    thread_name: str,
    task_name: Optional[str],
) -> None:
    """Log a slot that was held for longer than the slow-hold threshold, and the one-minute summary when it is due."""
    try:
        if hold_seconds >= SLOW_HOLD_SECONDS:
            idle_seconds = max(0.0, hold_seconds - stats.statement_seconds - stats.commit_seconds)
            telemetry_logger.log(
                _level(hold_seconds),
                "[AgentTelemetry] sqlite-write-slot-held seconds=%.2f statements=%d statement_seconds=%.2f "
                "commit_seconds=%.2f idle_seconds=%.2f operation=%s statement=%r queued_behind=%d thread=%s task=%s "
                "db=%s wal_mb=%s",
                hold_seconds,
                stats.statements,
                stats.statement_seconds,
                stats.commit_seconds,
                idle_seconds,
                operation_name,
                statement,
                queued_behind,
                thread_name,
                task_name,
                Path(telemetry.db_path).name,
                wal_megabytes(telemetry.db_path),
            )
        summary = telemetry.record(stats.wait_seconds, hold_seconds)
        if summary is not None:
            telemetry_logger.info(summary)
    except Exception:
        pass
