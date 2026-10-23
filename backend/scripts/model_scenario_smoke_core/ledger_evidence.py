"""Read-only work-ledger evidence lookups for the model-scenario smoke matrix.

Every agent-visible tool call is captured into ``agent_work_receipts`` by
``ToolLedgerCaptureCoordinator`` (see tool_ledger_capture.py /
tool_call_repetition_guard.py) regardless of tool family. This module reads
that table back out, read-only, to prove which tool a real agent task
actually invoked.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable


def _connect_read_only(database_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"file:{database_path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    return connection


def invoked_service_methods(database_path: Path, agent_task_id: str) -> set[tuple[str, str]]:
    """Return the distinct (service, method) pairs captured for one agent task."""
    with _connect_read_only(database_path) as connection:
        rows = connection.execute(
            "SELECT DISTINCT service, method FROM agent_work_receipts WHERE agent_task_id = ?",
            (agent_task_id,),
        ).fetchall()
    return {(row["service"], row["method"]) for row in rows}


def any_expected_invoked(
    database_path: Path,
    agent_task_id: str,
    expected: Iterable[tuple[str, str]],
) -> bool:
    """True if at least one of the expected (service, method) pairs was invoked."""
    invoked = invoked_service_methods(database_path, agent_task_id)
    return bool(invoked.intersection(set(expected)))


def all_required_groups_satisfied(
    database_path: Path,
    agent_task_id: str,
    groups: Iterable[Iterable[tuple[str, str]]],
) -> bool:
    """True when each group has at least one invoked (service, method) pair."""
    invoked = invoked_service_methods(database_path, agent_task_id)
    for group in groups:
        if not invoked.intersection(set(group)):
            return False
    return True


def all_required_services_invoked(
    database_path: Path,
    agent_task_id: str,
    services: Iterable[str],
) -> bool:
    """True when at least one receipt exists for every required service name."""
    invoked_services = {service for service, _method in invoked_service_methods(database_path, agent_task_id)}
    return all(service in invoked_services for service in services)
