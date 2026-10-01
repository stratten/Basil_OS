"""Close abandoned conversation turns before they enter the memory stream."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from api.services.conversation.conversation_turn_contract import (
    CONVERSATION_TURN_METADATA_KEY,
    CONVERSATION_TURN_STALE_AFTER,
    ConversationTurnLifecycle,
    is_active_conversation_turn_lifecycle,
    parse_conversation_turn_metadata,
)
from api.services.zettel.normalization import to_utc_iso

STALE_CONVERSATION_TURN_OUTCOME = (
    "Conversation turn expired after six hours without a terminal outcome."
)
STALE_AGENT_TASK_OUTCOME = STALE_CONVERSATION_TURN_OUTCOME
_TERMINAL_AGENT_TASK_STATUSES = frozenset({"completed", "failed", "canceled"})


@dataclass(frozen=True)
class ConversationTurnReconciliationResult:
    closed_turns: int = 0
    failed_agent_tasks: int = 0


def reconcile_stale_conversation_turns(
    conn: sqlite3.Connection,
    *,
    now: Optional[datetime] = None,
) -> ConversationTurnReconciliationResult:
    """Durably cancel active placeholders that have exceeded the grace period."""
    current_time = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    cutoff = current_time - CONVERSATION_TURN_STALE_AFTER
    closed_turns = 0
    failed_agent_tasks = 0
    rows = conn.execute(
        """
        SELECT id, metadata, timestamp
        FROM conversation_messages
        WHERE role = 'assistant' AND metadata IS NOT NULL
        ORDER BY timestamp ASC, rowid ASC
        """
    ).fetchall()

    for row in rows:
        metadata = _decode_metadata(row["metadata"])
        parsed = parse_conversation_turn_metadata(metadata)
        if parsed is None or not is_active_conversation_turn_lifecycle(parsed.lifecycle):
            continue
        started_at = _as_utc_datetime(row["timestamp"])
        if started_at is None or started_at > cutoff:
            continue

        if parsed.agent_task_id and _linked_agent_task_is_recent(
            conn,
            parsed.agent_task_id,
            cutoff=cutoff,
        ):
            continue
        if parsed.agent_task_id and _fail_stale_agent_task(conn, parsed.agent_task_id):
            failed_agent_tasks += 1

        raw_turn = metadata.get(CONVERSATION_TURN_METADATA_KEY)
        if not isinstance(raw_turn, dict):
            continue
        updated_metadata = dict(metadata)
        updated_turn = dict(raw_turn)
        updated_turn["lifecycle"] = ConversationTurnLifecycle.CANCELED.value
        updated_turn["terminal_outcome"] = STALE_CONVERSATION_TURN_OUTCOME
        updated_metadata[CONVERSATION_TURN_METADATA_KEY] = updated_turn
        conn.execute(
            "UPDATE conversation_messages SET metadata = ? WHERE id = ?",
            (json.dumps(updated_metadata, ensure_ascii=False), row["id"]),
        )
        closed_turns += 1

    return ConversationTurnReconciliationResult(
        closed_turns=closed_turns,
        failed_agent_tasks=failed_agent_tasks,
    )


def _decode_metadata(raw_metadata: Any) -> dict[str, Any]:
    try:
        decoded = json.loads(raw_metadata)
    except (TypeError, ValueError):
        return {}
    return decoded if isinstance(decoded, dict) else {}


def _as_utc_datetime(value: Any) -> Optional[datetime]:
    normalized = to_utc_iso(value)
    return datetime.fromisoformat(normalized) if normalized else None


def _linked_agent_task_is_recent(
    conn: sqlite3.Connection,
    agent_task_id: str,
    *,
    cutoff: datetime,
) -> bool:
    row = conn.execute(
        "SELECT status, updated_at FROM agent_tasks WHERE id = ?",
        (agent_task_id,),
    ).fetchone()
    if row is None:
        return False
    status = str(row["status"] or "").lower()
    if status in _TERMINAL_AGENT_TASK_STATUSES:
        return False
    updated_at = _as_utc_datetime(row["updated_at"])
    return updated_at is not None and updated_at > cutoff


def _fail_stale_agent_task(conn: sqlite3.Connection, agent_task_id: str) -> bool:
    row = conn.execute(
        "SELECT status, result_data FROM agent_tasks WHERE id = ?",
        (agent_task_id,),
    ).fetchone()
    if row is None or str(row["status"] or "").lower() in _TERMINAL_AGENT_TASK_STATUSES:
        return False
    result_data = _decode_metadata(row["result_data"])
    result_data.update(
        {
            "success": False,
            "error": STALE_AGENT_TASK_OUTCOME,
            "stale_execution": True,
        }
    )
    conn.execute(
        """
        UPDATE agent_tasks
        SET status = 'failed', result_data = ?, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (json.dumps(result_data, ensure_ascii=False), agent_task_id),
    )
    from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.agent_tasks.mutations.create_update import (
        recompute_root_summary,
        root_task_id_for_agent_task,
    )

    root_task_id = root_task_id_for_agent_task(conn, agent_task_id)
    if root_task_id:
        recompute_root_summary(conn, root_task_id)
    return True
