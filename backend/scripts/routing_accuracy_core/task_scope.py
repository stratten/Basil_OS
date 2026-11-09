"""Find every database table that holds rows for a given set of task ids, so what is captured and what is deleted come from one definition.

Tables are discovered from the live schema, not listed by hand, so a table added later is picked up and a table that holds rows for these tasks is never silently skipped.
A table is matched on ``agent_task_id`` when it has that column, otherwise on ``root_task_id``; ``agent_tasks`` is matched on ``id``.
Tables keyed by a work-session id are matched through the sessions that belong to the tasks.
Any other ``*task_id`` column that points at these tasks is reported as an "other reference" and blocks cleanup, because deleting around it would leave a dangling pointer.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Iterator, Sequence


@dataclass(frozen=True)
class ScopedTable:
    table: str
    column: str
    derived: bool  # a search index rebuilt from other rows: counted and cleaned, but not captured row by row


@dataclass(frozen=True)
class TaskScope:
    task_ids: tuple[str, ...]
    tables: tuple[ScopedTable, ...]
    session_ids: tuple[str, ...]
    session_tables: tuple[str, ...]
    # The row ids of every row in scope, read while the rows were still attached to their tasks. The app's delete route sets agent_task_id to NULL on receipts, events, and sessions, so after it runs those rows can no longer be found by task id; deleting and verifying go by these row ids instead.
    row_ids: dict[str, tuple[int, ...]] = field(default_factory=dict)


def open_read_only(database_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"file:{database_path}?mode=ro", uri=True, timeout=30)
    connection.row_factory = sqlite3.Row
    return connection


def quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _marks(values: Sequence[str]) -> str:
    return ",".join("?" * len(values))


def _columns(connection: sqlite3.Connection, table: str) -> list[str]:
    return [row[1] for row in connection.execute(f"PRAGMA table_info({quote(table)})")]


def _tables(connection: sqlite3.Connection) -> list[tuple[str, str]]:
    rows = connection.execute("SELECT name, sql FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name")
    return [(row[0], row[1] or "") for row in rows]


def discover(connection: sqlite3.Connection, task_ids: Iterable[str]) -> TaskScope:
    ids = tuple(sorted(set(task_ids)))
    if not ids:
        raise ValueError("no task ids were given")
    scoped: list[ScopedTable] = []
    session_tables: list[str] = []
    all_tables = _tables(connection)
    for table, sql in all_tables:
        columns = _columns(connection, table)
        if table == "agent_tasks":
            scoped.append(ScopedTable(table, "id", False))
        elif "agent_task_id" in columns:
            scoped.append(ScopedTable(table, "agent_task_id", "VIRTUAL TABLE" in sql.upper()))
        elif "root_task_id" in columns:
            scoped.append(ScopedTable(table, "root_task_id", "VIRTUAL TABLE" in sql.upper()))
        elif "session_id" in columns and table != "agent_work_sessions" and "VIRTUAL TABLE" not in sql.upper():
            session_tables.append(table)
    session_ids: tuple[str, ...] = ()
    if any(table == "agent_work_sessions" for table, _ in all_tables):
        rows = connection.execute(f"SELECT id FROM agent_work_sessions WHERE agent_task_id IN ({_marks(ids)})", ids)
        session_ids = tuple(sorted(row[0] for row in rows))
    row_ids: dict[str, tuple[int, ...]] = {}
    for item in scoped:
        found = tuple(row[0] for row in connection.execute(f"SELECT rowid FROM {quote(item.table)} WHERE {quote(item.column)} IN ({_marks(ids)})", ids))
        if found:
            row_ids[item.table] = found
    if session_ids:
        for table in session_tables:
            found = tuple(row[0] for row in connection.execute(f"SELECT rowid FROM {quote(table)} WHERE session_id IN ({_marks(session_ids)})", session_ids))
            if found:
                row_ids[f"session:{table}"] = found
    return TaskScope(ids, tuple(scoped), session_ids, tuple(session_tables), row_ids)


def chunks(values: Sequence[int], size: int = 500) -> Iterator[Sequence[int]]:
    """Row id lists are used in ``IN (...)`` clauses, so they are split to stay under SQLite's limit on bound variables."""
    for start in range(0, len(values), size):
        yield values[start:start + size]


def count_by_row_id(connection: sqlite3.Connection, scope: TaskScope) -> dict[str, int]:
    """How many of the rows captured in ``scope.row_ids`` still exist. This is the proof cleanup worked, and it does not depend on the task id columns the delete route clears."""
    remaining: dict[str, int] = {}
    for key, ids in scope.row_ids.items():
        table = key.removeprefix("session:")
        total = sum(connection.execute(f"SELECT COUNT(*) FROM {quote(table)} WHERE rowid IN ({_marks(chunk)})", tuple(chunk)).fetchone()[0] for chunk in chunks(ids))
        if total:
            remaining[key] = total
    return remaining


def count_rows(connection: sqlite3.Connection, scope: TaskScope) -> dict[str, int]:
    """Rows per table that belong to the scope. Session-keyed tables appear as ``session:<table>``. Only tables with rows are listed."""
    counts: dict[str, int] = {}
    for item in scope.tables:
        sql = f"SELECT COUNT(*) FROM {quote(item.table)} WHERE {quote(item.column)} IN ({_marks(scope.task_ids)})"
        number = connection.execute(sql, scope.task_ids).fetchone()[0]
        if number:
            counts[item.table] = number
    if scope.session_ids:
        for table in scope.session_tables:
            sql = f"SELECT COUNT(*) FROM {quote(table)} WHERE session_id IN ({_marks(scope.session_ids)})"
            number = connection.execute(sql, scope.session_ids).fetchone()[0]
            if number:
                counts[f"session:{table}"] = number
    return counts


def other_references(connection: sqlite3.Connection, scope: TaskScope) -> dict[str, int]:
    """Rows that point at these tasks through a ``*task_id`` column the scope does not match on. Only entries with rows are listed."""
    matched_by = {item.table: item.column for item in scope.tables}
    found: dict[str, int] = {}
    for table, sql in _tables(connection):
        if "VIRTUAL TABLE" in sql.upper():
            continue
        for column in _columns(connection, table):
            if not column.endswith("task_id") or matched_by.get(table) == column:
                continue
            query = f"SELECT COUNT(*) FROM {quote(table)} WHERE {quote(column)} IN ({_marks(scope.task_ids)})"
            parameters: tuple[str, ...] = scope.task_ids
            if table in matched_by:
                query += f" AND {quote(matched_by[table])} NOT IN ({_marks(scope.task_ids)})"
                parameters = scope.task_ids + scope.task_ids
            elif table in scope.session_tables and scope.session_ids:
                # Rows in a session-keyed table are already in scope, so a pointer to these tasks from one of them is not an outside reference.
                query += f" AND session_id NOT IN ({_marks(scope.session_ids)})"
                parameters = scope.task_ids + scope.session_ids
            number = connection.execute(query, parameters).fetchone()[0]
            if number:
                found[f"{table}.{column}"] = number
    return found


def task_statuses(connection: sqlite3.Connection, scope: TaskScope) -> dict[str, str]:
    rows = connection.execute(f"SELECT id, status FROM agent_tasks WHERE id IN ({_marks(scope.task_ids)})", scope.task_ids)
    return {row[0]: str(row[1] or "") for row in rows}
