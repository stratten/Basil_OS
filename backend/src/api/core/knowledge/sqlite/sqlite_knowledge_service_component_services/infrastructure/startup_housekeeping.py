"""Startup housekeeping for the knowledge database.

Each step checks the state of the database and does a bounded amount of work, so it is safe to run at every launch, resumes where the last launch stopped, and costs almost nothing once there is nothing left to do. No step can raise into startup: a failure is logged and the step is tried again at the next launch.

1. The write-ahead log is truncated when a burst of writes left it large.
2. Search entries written by an older builder, or never recorded, are rebuilt a few at a time, biggest chains first, each in its own short write transaction so the write slot is never held for long.
3. Free space inside the file is returned to the disk. The database starts in ``auto_vacuum=NONE`` mode, which can only be changed by one full ``VACUUM``. That one-time conversion waits until the search re-index has finished, so the space freed by the smaller entries is reclaimed in the same pass, and it is skipped unless enough space is reclaimable and the disk has room. Afterwards the file is in incremental mode and later launches return free pages in small slices.
"""

from __future__ import annotations

import logging
import os
import shutil
import sqlite3
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional

from .connection import get_sync_connection, run_write_transaction

logger = logging.getLogger("api.main.db_housekeeping")

WAL_TRUNCATE_THRESHOLD_BYTES = 64 * 1024 * 1024
REINDEX_BUDGET_SECONDS = 30.0
REINDEX_BACKGROUND_PAUSE_RATIO = 1.0
REINDEX_MAX_PAUSE_SECONDS = 1.0
INCREMENTAL_VACUUM_PAGES_PER_STEP = 2000
INCREMENTAL_VACUUM_BUDGET_SECONDS = 10.0
MIN_RECLAIMABLE_BYTES = 256 * 1024 * 1024
MIN_RECLAIMABLE_FRACTION = 0.10
DISK_MARGIN_BYTES = 1024 * 1024 * 1024
HOUSEKEEPING_BUSY_TIMEOUT_MS = 120_000

AUTO_VACUUM_NONE = 0
AUTO_VACUUM_INCREMENTAL = 2


@dataclass
class HousekeepingReport:
    wal_truncated: bool = False
    search_entries_rebuilt: int = 0
    search_entries_remaining: int = 0
    space_reclaim: str = "not needed"
    pages_returned: int = 0


def _raw_connection(db_path: str) -> sqlite3.Connection:
    connection = sqlite3.connect(db_path, timeout=HOUSEKEEPING_BUSY_TIMEOUT_MS / 1000, isolation_level=None)
    connection.execute(f"PRAGMA busy_timeout = {HOUSEKEEPING_BUSY_TIMEOUT_MS}")
    return connection


def _wal_bytes(db_path: str) -> int:
    try:
        return os.path.getsize(f"{db_path}-wal")
    except OSError:
        return 0


def truncate_wal_if_large(db_path: str, threshold_bytes: int = WAL_TRUNCATE_THRESHOLD_BYTES) -> bool:
    """Checkpoint and truncate the write-ahead log when it is larger than the threshold. Returns whether it was truncated."""
    if _wal_bytes(db_path) < threshold_bytes:
        return False
    connection = _raw_connection(db_path)
    try:
        busy = connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()[0]
        return busy == 0
    finally:
        connection.close()


def stale_search_roots(connection: sqlite3.Connection) -> list[str]:
    """Chains whose search entry was written by an older builder or never recorded, biggest chains first. Chains whose newest turn is still in flight are left alone, because they are indexed when that turn ends."""
    from ..agent_tasks.mutations.root_summary import IN_FLIGHT_TURN_STATUSES, SEARCH_BUILDER_VERSION

    in_flight = sorted(IN_FLIGHT_TURN_STATUSES)
    placeholders = ",".join("?" for _ in in_flight)
    rows = connection.execute(
        f"""
        SELECT a.id
        FROM agent_tasks a
        LEFT JOIN agent_task_search_index_state s ON s.root_task_id = a.id
        WHERE COALESCE(a.root_task_id, a.id) = a.id
          AND (s.builder_version IS NULL OR s.builder_version < ?)
          AND COALESCE(a.latest_status, '') NOT IN ({placeholders})
        ORDER BY COALESCE(a.turn_count, 0) DESC, a.id ASC
        """,
        (SEARCH_BUILDER_VERSION, *in_flight),
    ).fetchall()
    return [row[0] for row in rows]


def count_stale_search_entries(db_path: str) -> int:
    """How many search entries are stale right now, without rebuilding any."""
    reader = get_sync_connection(db_path, ensure_schema=False)
    try:
        return len(stale_search_roots(reader))
    finally:
        reader.close()


def reindex_stale_search_entries(
    db_path: str,
    budget_seconds: Optional[float] = REINDEX_BUDGET_SECONDS,
    *,
    stop_event: Optional[threading.Event] = None,
    pause_ratio: float = 0.0,
) -> tuple[int, int]:
    """Rebuild stale search entries until the time budget is spent, or until all are done when ``budget_seconds`` is None. Returns how many were rebuilt and how many are still stale.

    ``stop_event`` ends the loop between two entries. ``pause_ratio`` rests after each rebuild for that multiple of the time the rebuild took (at most ``REINDEX_MAX_PAUSE_SECONDS``), so a background run leaves the database free for the app's own writes.
    """
    from ..agent_tasks.mutations.root_summary import recompute_root_summary

    reader = get_sync_connection(db_path, ensure_schema=False)
    try:
        stale = stale_search_roots(reader)
    finally:
        reader.close()

    deadline = None if budget_seconds is None else time.monotonic() + budget_seconds
    rebuilt = 0
    for root_id in stale:
        if stop_event is not None and stop_event.is_set():
            break
        if deadline is not None and time.monotonic() >= deadline:
            break
        started = time.monotonic()
        try:
            run_write_transaction(
                db_path,
                "reindex_agent_task_search",
                lambda connection, root=root_id: recompute_root_summary(connection, root),
            )
            rebuilt += 1
        except Exception:
            logger.warning("Search re-index failed for chain %s; it is tried again at the next launch", root_id, exc_info=True)
        if pause_ratio > 0:
            rest = min(REINDEX_MAX_PAUSE_SECONDS, (time.monotonic() - started) * pause_ratio)
            if stop_event is not None:
                stop_event.wait(rest)
            else:
                time.sleep(rest)

    reader = get_sync_connection(db_path, ensure_schema=False)
    try:
        remaining = len(stale_search_roots(reader))
    finally:
        reader.close()
    return rebuilt, remaining


def _pragma(connection: sqlite3.Connection, name: str) -> int:
    return int(connection.execute(f"PRAGMA {name}").fetchone()[0])


def reclaim_free_space(
    db_path: str,
    *,
    search_entries_remaining: int,
    status: Optional[Callable[[str], None]] = None,
    incremental_budget_seconds: float = INCREMENTAL_VACUUM_BUDGET_SECONDS,
    min_reclaimable_bytes: int = MIN_RECLAIMABLE_BYTES,
    min_reclaimable_fraction: float = MIN_RECLAIMABLE_FRACTION,
    disk_margin_bytes: int = DISK_MARGIN_BYTES,
) -> tuple[str, int]:
    """Return free pages to the disk. Returns a short description of what happened and the number of pages returned."""
    connection = _raw_connection(db_path)
    try:
        page_size = _pragma(connection, "page_size")
        page_count = _pragma(connection, "page_count")
        free_pages = _pragma(connection, "freelist_count")
        mode = _pragma(connection, "auto_vacuum")

        if mode == AUTO_VACUUM_INCREMENTAL:
            if free_pages == 0:
                return "not needed", 0
            returned = 0
            deadline = time.monotonic() + incremental_budget_seconds
            while free_pages > 0 and time.monotonic() < deadline:
                connection.execute(f"PRAGMA incremental_vacuum({INCREMENTAL_VACUUM_PAGES_PER_STEP})").fetchall()
                remaining_pages = _pragma(connection, "freelist_count")
                returned += free_pages - remaining_pages
                free_pages = remaining_pages
            return ("returned free pages in slices" if free_pages == 0 else "returned some free pages, more next launch"), returned

        if mode != AUTO_VACUUM_NONE:
            return "left alone: the file uses full auto-vacuum", 0

        free_bytes = free_pages * page_size
        if free_bytes < min_reclaimable_bytes or free_pages < page_count * min_reclaimable_fraction:
            return "not needed", 0
        if search_entries_remaining:
            return "waiting for the search re-index to finish", 0

        file_bytes = page_count * page_size
        available = shutil.disk_usage(os.path.dirname(os.path.abspath(db_path)) or ".").free
        if available < file_bytes + _wal_bytes(db_path) + disk_margin_bytes:
            return "skipped: not enough free disk for the one-time rewrite", 0

        logger.info(
            "[Housekeeping] Converting the database to incremental auto-vacuum with a one-time VACUUM: file_mb=%d reclaimable_mb=%d",
            file_bytes // 1048576,
            free_bytes // 1048576,
        )
        if status is not None:
            status("Optimizing the database (one time, this can take a few minutes)...")
        started = time.monotonic()
        connection.execute(f"PRAGMA auto_vacuum = {AUTO_VACUUM_INCREMENTAL}")
        connection.execute("VACUUM")
        after_pages = _pragma(connection, "page_count")
        logger.info(
            "[Housekeeping] VACUUM finished in %.0fs: file_mb %d -> %d, auto_vacuum=%d",
            time.monotonic() - started,
            file_bytes // 1048576,
            after_pages * page_size // 1048576,
            _pragma(connection, "auto_vacuum"),
        )
        return "converted to incremental auto-vacuum", max(0, page_count - after_pages)
    finally:
        connection.close()


def run_startup_housekeeping(
    db_path: str,
    *,
    status: Optional[Callable[[str], None]] = None,
    reindex_budget_seconds: float = REINDEX_BUDGET_SECONDS,
    defer_reindex: bool = False,
) -> HousekeepingReport:
    """Run every housekeeping step once. Never raises.

    With ``defer_reindex`` the search re-index is not run here: the stale entries are only counted, so startup is not held up, and the caller runs ``run_background_reindex`` after startup. The one-time rewrite in the next step waits while any entry is stale, so it happens at the first launch after the re-index has finished.
    """
    report = HousekeepingReport()

    try:
        report.wal_truncated = truncate_wal_if_large(db_path)
    except Exception:
        logger.warning("[Housekeeping] Truncating the write-ahead log failed", exc_info=True)

    try:
        if defer_reindex:
            report.search_entries_remaining = count_stale_search_entries(db_path)
        else:
            if status is not None:
                status("Tidying the database...")
            report.search_entries_rebuilt, report.search_entries_remaining = reindex_stale_search_entries(
                db_path, reindex_budget_seconds
            )
    except Exception:
        logger.warning("[Housekeeping] The search re-index failed", exc_info=True)
        report.search_entries_remaining = -1

    try:
        # A failed re-index (-1) counts as unfinished work, so the one-time rewrite waits for it.
        unfinished_search_entries = report.search_entries_remaining if report.search_entries_remaining >= 0 else 1
        report.space_reclaim, report.pages_returned = reclaim_free_space(
            db_path,
            search_entries_remaining=unfinished_search_entries,
            status=status,
        )
    except Exception:
        logger.warning("[Housekeeping] Reclaiming free space failed; it is tried again at the next launch", exc_info=True)
        report.space_reclaim = "failed"

    logger.info(
        "[Housekeeping] wal_truncated=%s search_entries_rebuilt=%d search_entries_remaining=%d space_reclaim=%s pages_returned=%d",
        report.wal_truncated,
        report.search_entries_rebuilt,
        report.search_entries_remaining,
        report.space_reclaim,
        report.pages_returned,
    )
    return report


def run_background_reindex(db_path: str, stop_event: Optional[threading.Event] = None) -> tuple[int, int]:
    """Rebuild every stale search entry, resting between entries, until none is left or ``stop_event`` is set. Meant to run on a worker thread after startup. Never raises. Returns how many were rebuilt and how many are still stale (-1 when that could not be read)."""
    started = time.monotonic()
    try:
        rebuilt, remaining = reindex_stale_search_entries(
            db_path,
            None,
            stop_event=stop_event,
            pause_ratio=REINDEX_BACKGROUND_PAUSE_RATIO,
        )
    except Exception:
        logger.warning("[Housekeeping] The background search re-index failed; it is tried again at the next launch", exc_info=True)
        return 0, -1
    logger.info(
        "[Housekeeping] Background search re-index %s: rebuilt=%d remaining=%d seconds=%.0f",
        "finished" if remaining == 0 else "stopped early",
        rebuilt,
        remaining,
        time.monotonic() - started,
    )
    return rebuilt, remaining
