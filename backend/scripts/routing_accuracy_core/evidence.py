"""Snapshot every database row a run produced, so the rows can be deleted afterward without losing anything worth keeping.

The snapshot holds each task's receipts, approval cards, events, sessions, and final result, which include the owner's real data for live cases.
It is written under ``local/`` (gitignored), separate from the results file, which holds only route tokens and verdicts.
Rows are captured from the same tables cleanup deletes from (see task_scope), and the per-table row counts are recorded so cleanup can refuse if the database changed after the snapshot.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .task_scope import TaskScope, count_rows, discover, open_read_only, quote

SCHEMA_VERSION = 1
KIND = "routing_run_evidence"
MAX_VALUE_CHARS = 50_000


def evidence_path_for(results_path: Path) -> Path:
    """``run.json`` is paired with ``run.evidence.json`` in the same folder."""
    return results_path.with_name(results_path.stem + ".evidence.json")


def plain_value(value: Any, truncated: list[int]) -> Any:
    """A column value as it is stored in a snapshot: blobs become a size note and very long text is cut, with the cut length appended to ``truncated``."""
    if isinstance(value, bytes):
        return f"<{len(value)} bytes>"
    if isinstance(value, str) and len(value) > MAX_VALUE_CHARS:
        truncated.append(len(value) - MAX_VALUE_CHARS)
        return value[:MAX_VALUE_CHARS] + f"[truncated {len(value) - MAX_VALUE_CHARS} characters]"
    return value


def _rows(connection: Any, table: str, column: str, values: tuple[str, ...], truncated: list[int]) -> list[dict[str, Any]]:
    marks = ",".join("?" * len(values))
    rows = connection.execute(f"SELECT * FROM {quote(table)} WHERE {quote(column)} IN ({marks})", values).fetchall()
    return [{key: plain_value(row[key], truncated) for key in row.keys()} for row in rows]


def collect_evidence(database_path: Path, task_ids: Iterable[str]) -> dict[str, Any]:
    connection = open_read_only(database_path)
    try:
        scope: TaskScope = discover(connection, task_ids)
        counts = count_rows(connection, scope)
        truncated: list[int] = []
        tables: dict[str, list[dict[str, Any]]] = {}
        for item in scope.tables:
            if item.derived or item.table not in counts:
                continue
            tables[item.table] = _rows(connection, item.table, item.column, scope.task_ids, truncated)
        session_tables: dict[str, list[dict[str, Any]]] = {}
        for table in scope.session_tables:
            if f"session:{table}" in counts:
                session_tables[table] = _rows(connection, table, "session_id", scope.session_ids, truncated)
        derived = sorted(item.table for item in scope.tables if item.derived and item.table in counts)
        return {
            "schema_version": SCHEMA_VERSION,
            "kind": KIND,
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "task_ids": list(scope.task_ids),
            "session_ids": list(scope.session_ids),
            "row_counts": counts,
            "tables": tables,
            "session_tables": session_tables,
            "derived_tables_not_captured": derived,
            "truncated_values": len(truncated),
        }
    finally:
        connection.close()


def validate_evidence(document: dict[str, Any], task_ids: Iterable[str]) -> None:
    """Raise ValueError unless ``document`` is a run snapshot that covers exactly ``task_ids`` and holds every non-derived row it counted."""
    if document.get("kind") != KIND or document.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("the evidence file is not a routing run snapshot of the expected version")
    if sorted(document.get("task_ids", [])) != sorted(set(task_ids)):
        raise ValueError("the evidence file does not cover exactly the task ids in the results file")
    derived = set(document.get("derived_tables_not_captured", []))
    for name, counted in document.get("row_counts", {}).items():
        if name in derived:
            continue
        group = document["session_tables"] if name.startswith("session:") else document["tables"]
        captured = len(group.get(name.removeprefix("session:"), []))
        if captured != counted:
            raise ValueError(f"the evidence file holds {captured} rows for {name} but counted {counted}")
