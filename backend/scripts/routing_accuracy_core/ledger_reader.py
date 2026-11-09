"""Read one task's tool calls back out of the work ledger, in call order, read-only."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .route_tokens import Receipt

DEFAULT_DATABASE_PATH = Path.home() / ".basil" / "knowledge_base.db"


def read_receipts(database_path: Path, agent_task_id: str) -> list[Receipt]:
    """Every receipt captured for one agent task, oldest first. An unreadable ledger raises, so a harness fault is never scored as a routing failure."""
    connection = sqlite3.connect(f"file:{database_path}?mode=ro", uri=True, timeout=10)
    try:
        connection.execute("PRAGMA query_only = ON")
        rows = connection.execute(
            "SELECT service, method, requested_effect_json FROM agent_work_receipts "
            "WHERE agent_task_id = ? ORDER BY created_at, rowid",
            (agent_task_id,),
        ).fetchall()
    finally:
        connection.close()
    return [Receipt(service, method, _parameters(raw)) for service, method, raw in rows]


def _parameters(raw: str | None) -> dict:
    try:
        effect = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {}
    parameters = effect.get("parameters") if isinstance(effect, dict) else None
    return parameters if isinstance(parameters, dict) else {}
