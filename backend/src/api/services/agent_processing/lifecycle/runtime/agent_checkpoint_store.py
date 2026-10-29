"""Location, write mode, and retention of the LangGraph agent checkpoint database."""

from __future__ import annotations

import asyncio
import os
import sqlite3
import time
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

AGENT_CHECKPOINT_DATABASE_PATH = "~/.basil/agent_checkpoints.sqlite"
TERMINAL_CHECKPOINT_RETENTION_DAYS = 7
TERMINAL_AGENT_TASK_STATUSES = ("completed", "failed", "canceled")
VACUUM_MIN_FREE_BYTES = 64 * 1024 * 1024
VACUUM_MIN_FREE_FRACTION = 0.25
_THREAD_LOOKUP_BATCH_SIZE = 500


class ExitDurabilityGraph:
    """Compiled graph whose runs persist one checkpoint when they stop instead of one per node.

    Only the final checkpoint of a run is ever read back (pause and resume, delegation resume), so per-node snapshots are pure write cost. Callers may still pass an explicit ``durability``.
    """

    def __init__(self, compiled_graph: Any) -> None:
        self._compiled_graph = compiled_graph

    def astream(self, *args: Any, **kwargs: Any) -> Any:
        kwargs.setdefault("durability", "exit")
        return self._compiled_graph.astream(*args, **kwargs)

    async def ainvoke(self, *args: Any, **kwargs: Any) -> Any:
        kwargs.setdefault("durability", "exit")
        return await self._compiled_graph.ainvoke(*args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._compiled_graph, name)


def agent_checkpoint_database_path() -> Path:
    """Return the checkpoint database path for the current ``HOME``."""
    return Path(os.path.expanduser(AGENT_CHECKPOINT_DATABASE_PATH))


@dataclass(frozen=True)
class CheckpointPruneResult:
    threads_before: int = 0
    deleted_terminal_threads: int = 0
    deleted_orphan_threads: int = 0
    vacuumed: bool = False
    size_bytes_before: int = 0
    size_bytes_after: int = 0
    elapsed_seconds: float = 0.0
    skipped_reason: str | None = None


def _database_size(path: Path) -> int:
    total = 0
    for candidate in (path, Path(f"{path}-wal"), Path(f"{path}-shm")):
        try:
            total += candidate.stat().st_size
        except FileNotFoundError:
            continue
    return total


def _batches(items: list[str], size: int) -> Iterator[list[str]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def _classify_threads(
    knowledge_db_path: Path,
    thread_ids: list[str],
    retention_days: int,
) -> tuple[list[str], list[str]] | None:
    """Return expired terminal thread ids and orphan thread ids, or None when the knowledge database has no agent_tasks table.

    The connection only reads; it is not opened with ``mode=ro`` because a read-only connection cannot create the WAL shared-memory file when no other connection has the database open.
    """
    known_task_ids: set[str] = set()
    expired_thread_ids: list[str] = []
    status_placeholders = ",".join("?" * len(TERMINAL_AGENT_TASK_STATUSES))
    with closing(sqlite3.connect(str(knowledge_db_path))) as knowledge_conn:
        if not _table_exists(knowledge_conn, "agent_tasks"):
            return None
        for batch in _batches(thread_ids, _THREAD_LOOKUP_BATCH_SIZE):
            id_placeholders = ",".join("?" * len(batch))
            rows = knowledge_conn.execute(
                f"""
                SELECT id,
                       status IN ({status_placeholders})
                       AND julianday(updated_at) < julianday('now', ?)
                FROM agent_tasks
                WHERE id IN ({id_placeholders})
                """,
                (*TERMINAL_AGENT_TASK_STATUSES, f"-{retention_days} days", *batch),
            ).fetchall()
            for task_id, is_expired in rows:
                known_task_ids.add(task_id)
                if is_expired:
                    expired_thread_ids.append(task_id)
    orphan_thread_ids = [thread_id for thread_id in thread_ids if thread_id not in known_task_ids]
    return expired_thread_ids, orphan_thread_ids


def _vacuum_if_mostly_free(
    conn: sqlite3.Connection,
    min_free_bytes: int,
    min_free_fraction: float,
) -> bool:
    page_size = conn.execute("PRAGMA page_size").fetchone()[0]
    page_count = conn.execute("PRAGMA page_count").fetchone()[0]
    freelist_count = conn.execute("PRAGMA freelist_count").fetchone()[0]
    if page_count <= 0:
        return False
    if freelist_count * page_size < min_free_bytes:
        return False
    if freelist_count / page_count < min_free_fraction:
        return False
    conn.execute("VACUUM")
    return True


def prune_agent_checkpoints(
    checkpoint_db_path: Path,
    knowledge_db_path: Path,
    *,
    retention_days: int = TERMINAL_CHECKPOINT_RETENTION_DAYS,
    vacuum_min_free_bytes: int = VACUUM_MIN_FREE_BYTES,
    vacuum_min_free_fraction: float = VACUUM_MIN_FREE_FRACTION,
) -> CheckpointPruneResult:
    """Delete checkpoint threads that can never be resumed again.

    A thread is deleted when its agent task is terminal and has not been updated for ``retention_days``, or when no agent task row exists for it. Deleting threads without a task row is only safe before agent-task intake opens, so call this during startup.
    """
    started_at = time.monotonic()
    checkpoint_db_path = Path(checkpoint_db_path)
    knowledge_db_path = Path(knowledge_db_path)
    if not checkpoint_db_path.exists():
        return CheckpointPruneResult(skipped_reason="checkpoint database does not exist")
    if not knowledge_db_path.exists():
        return CheckpointPruneResult(skipped_reason="knowledge database does not exist")

    size_before = _database_size(checkpoint_db_path)
    from langgraph.checkpoint.sqlite import SqliteSaver  # type: ignore

    with closing(sqlite3.connect(str(checkpoint_db_path), check_same_thread=False)) as checkpoint_conn:
        if not (_table_exists(checkpoint_conn, "checkpoints") and _table_exists(checkpoint_conn, "writes")):
            return CheckpointPruneResult(
                size_bytes_before=size_before,
                size_bytes_after=size_before,
                elapsed_seconds=time.monotonic() - started_at,
                skipped_reason="checkpoint tables do not exist",
            )
        thread_ids = [
            row[0]
            for row in checkpoint_conn.execute(
                "SELECT thread_id FROM checkpoints UNION SELECT thread_id FROM writes"
            )
        ]
        classified = _classify_threads(knowledge_db_path, thread_ids, retention_days)
        if classified is None:
            return CheckpointPruneResult(
                threads_before=len(thread_ids),
                size_bytes_before=size_before,
                size_bytes_after=size_before,
                elapsed_seconds=time.monotonic() - started_at,
                skipped_reason="agent_tasks table does not exist",
            )
        expired_thread_ids, orphan_thread_ids = classified
        saver = SqliteSaver(checkpoint_conn)
        for thread_id in (*expired_thread_ids, *orphan_thread_ids):
            saver.delete_thread(thread_id)
        vacuumed = _vacuum_if_mostly_free(
            checkpoint_conn,
            vacuum_min_free_bytes,
            vacuum_min_free_fraction,
        )
        checkpoint_conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    return CheckpointPruneResult(
        threads_before=len(thread_ids),
        deleted_terminal_threads=len(expired_thread_ids),
        deleted_orphan_threads=len(orphan_thread_ids),
        vacuumed=vacuumed,
        size_bytes_before=size_before,
        size_bytes_after=_database_size(checkpoint_db_path),
        elapsed_seconds=time.monotonic() - started_at,
    )


async def prune_agent_checkpoints_at_startup(knowledge_db_path: str | Path) -> CheckpointPruneResult:
    """Run checkpoint pruning off the event loop for backend startup."""
    return await asyncio.to_thread(
        prune_agent_checkpoints,
        agent_checkpoint_database_path(),
        Path(knowledge_db_path),
    )
