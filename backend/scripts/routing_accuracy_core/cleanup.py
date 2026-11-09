"""Remove the database rows a routing run created, after the evidence has been captured and locked.

Order matters: the app's own delete route runs first (it cancels the task and clears the task, threads, call log, and checklists), then the rows it deliberately leaves behind (work receipts, events, sessions, approvals, and similar) are removed by id in one transaction.
Nothing is deleted unless every precondition holds: the rows still match the snapshot exactly, no task is still active, no approval is still pending, and nothing else points at these tasks.
After deleting, every table is counted again and cleanup fails loudly if any row remains.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Optional, Sequence

from .evidence import plain_value
from .runner import ACTIVE_STATUSES, BackendClient
from .task_scope import TaskScope, chunks, count_by_row_id, count_rows, discover, open_read_only, other_references, quote, task_statuses


class CleanupRefused(RuntimeError):
    """A precondition failed, or rows remained after cleanup. Nothing further was deleted."""


@dataclass(frozen=True)
class CleanupPlan:
    scope: TaskScope
    counts: dict[str, int]
    other_references: dict[str, int]
    active_tasks: dict[str, str]
    pending_approvals: int
    changed_since_snapshot: dict[str, tuple[int, int]]  # table -> (rows in the snapshot, rows now)

    @property
    def blockers(self) -> list[str]:
        problems: list[str] = []
        if self.active_tasks:
            problems.append(f"{len(self.active_tasks)} task(s) are still active: {', '.join(f'{i} ({s})' for i, s in sorted(self.active_tasks.items()))}")
        if self.pending_approvals:
            problems.append(f"{self.pending_approvals} approval card(s) are still pending")
        if self.other_references:
            problems.append(f"other rows point at these tasks: {self.other_references}")
        if self.changed_since_snapshot:
            problems.append(f"rows changed since the snapshot (table: snapshot, now): {self.changed_since_snapshot}")
        return problems


def _looks_like_task_id(value: str) -> bool:
    return len(value) == 36 and value.count("-") == 4


def plan_cleanup(database_path: Path, task_ids: Iterable[str], captured_counts: Optional[Mapping[str, int]]) -> CleanupPlan:
    """Read-only. ``captured_counts`` is the snapshot's per-table row counts; pass None to plan without comparing."""
    ids = sorted(set(task_ids))
    bad = [value for value in ids if not _looks_like_task_id(value)]
    if bad:
        raise CleanupRefused(f"not task ids: {bad}")
    connection = open_read_only(database_path)
    try:
        scope = discover(connection, ids)
        counts = count_rows(connection, scope)
        statuses = task_statuses(connection, scope)
        marks = ",".join("?" * len(scope.task_ids))
        try:
            pending = connection.execute(
                f"SELECT COUNT(*) FROM execution_approvals WHERE agent_task_id IN ({marks}) AND status = 'pending'", scope.task_ids
            ).fetchone()[0]
        except sqlite3.OperationalError:
            pending = 0
        changed: dict[str, tuple[int, int]] = {}
        if captured_counts is not None:
            for name in sorted(set(captured_counts) | set(counts)):
                if captured_counts.get(name, 0) != counts.get(name, 0):
                    changed[name] = (captured_counts.get(name, 0), counts.get(name, 0))
        return CleanupPlan(
            scope, counts, other_references(connection, scope),
            {task_id: status for task_id, status in statuses.items() if status in ACTIVE_STATUSES}, pending, changed,
        )
    finally:
        connection.close()


def _delete_by_row_id(connection: sqlite3.Connection, table: str, row_ids: Sequence[int]) -> int:
    deleted = 0
    for chunk in chunks(row_ids):
        cursor = connection.execute(f"DELETE FROM {quote(table)} WHERE rowid IN ({','.join('?' * len(chunk))})", tuple(chunk))
        deleted += max(cursor.rowcount, 0)
    return deleted


def _delete_residue(database_path: Path, scope: TaskScope) -> dict[str, int]:
    """Delete the rows the app's delete route leaves behind, in one transaction, by the row ids captured before that route ran.

    The route detaches receipts, events, and sessions (their task id becomes NULL) instead of deleting them, so they can no longer be found by task id.
    Session-keyed tables go first, then the rest.
    """
    deleted: dict[str, int] = {}
    connection = sqlite3.connect(str(database_path), timeout=30, isolation_level=None)
    try:
        connection.execute("PRAGMA busy_timeout = 30000")
        connection.execute("BEGIN IMMEDIATE")
        try:
            ordered = sorted(scope.row_ids, key=lambda key: (not key.startswith("session:"), key))
            for key in ordered:
                count = _delete_by_row_id(connection, key.removeprefix("session:"), scope.row_ids[key])
                if count:
                    deleted[key] = count
            connection.execute("COMMIT")
        except BaseException:
            connection.execute("ROLLBACK")
            raise
    finally:
        connection.close()
    return deleted


def _is_the_captured_row(live: sqlite3.Row, captured: Mapping[str, object]) -> bool:
    """Every column except the detached task id equals what the snapshot recorded, compared the way the snapshot recorded it (blobs and very long text are abbreviated there)."""
    columns = set(live.keys())
    return all(
        key not in columns or plain_value(live[key], []) == value
        for key, value in captured.items()
        if key != "agent_task_id"
    )


def repair_orphans(database_path: Path, evidence: Mapping[str, object], dry_run: bool = False) -> dict[str, int]:
    """Remove rows an earlier cleanup left detached, using a verified evidence snapshot to say exactly which rows they were.

    Earlier cleanups deleted by task id, and the app's delete route had already set that id to NULL on receipts, events, and sessions, so those rows were left behind.
    A row is deleted only if it has a primary key ``id`` in the snapshot, still exists, has a NULL ``agent_task_id``, and every other column equals the captured value.
    """
    removed: dict[str, int] = {}
    tables = evidence.get("tables", {})
    if not isinstance(tables, dict):
        raise CleanupRefused("the evidence file has no tables")
    connection = sqlite3.connect(str(database_path), timeout=30, isolation_level=None)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA busy_timeout = 30000")
        connection.execute("BEGIN IMMEDIATE")
        try:
            for table, rows in tables.items():
                columns = [row[1] for row in connection.execute(f"PRAGMA table_info({quote(table)})")]
                if "id" not in columns or "agent_task_id" not in columns:
                    continue
                for captured in rows:
                    live = connection.execute(f"SELECT * FROM {quote(table)} WHERE id = ?", (captured["id"],)).fetchone()
                    if live is not None and live["agent_task_id"] is None and _is_the_captured_row(live, captured):
                        connection.execute(f"DELETE FROM {quote(table)} WHERE id = ?", (captured["id"],))
                        removed[table] = removed.get(table, 0) + 1
            connection.execute("ROLLBACK" if dry_run else "COMMIT")
        except BaseException:
            connection.execute("ROLLBACK")
            raise
    finally:
        connection.close()
    return removed


def run_cleanup(client: BackendClient, database_path: Path, task_ids: Iterable[str], captured_counts: Mapping[str, int]) -> dict[str, dict[str, int]]:
    """Delete the run's rows and prove they are gone. Raises CleanupRefused before deleting anything if a precondition fails."""
    plan = plan_cleanup(database_path, task_ids, captured_counts)
    if plan.blockers:
        raise CleanupRefused("; ".join(plan.blockers))
    for task_id in plan.scope.task_ids:
        client.delete_task(task_id)
    deleted = _delete_residue(database_path, plan.scope)
    connection = open_read_only(database_path)
    try:
        # Counted by the row ids captured before the delete route ran: that route clears the task id on receipts, events, and sessions, so a count by task id would report zero whether or not they were deleted.
        remaining = count_by_row_id(connection, plan.scope)
    finally:
        connection.close()
    if remaining:
        raise CleanupRefused(f"rows remain after cleanup: {remaining}")
    return {"before": plan.counts, "deleted_by_sql": deleted, "remaining": remaining}
