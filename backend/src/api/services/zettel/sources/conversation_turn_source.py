"""Project finalized user and assistant pairs into immutable zettel entries."""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Dict, List, Optional, Sequence

from api.services.conversation.conversation_turn_contract import (
    is_terminal_conversation_turn_lifecycle,
    parse_conversation_turn_metadata,
)
from api.services.zettel.normalization import to_utc_iso, truncate
from api.services.zettel.sources.base import ZettelDraft


class ConversationTurnSource:
    """Projects terminal conversation pairs rather than mutable whole threads."""

    source_kind = "conversation_turn"

    def find_uncarded(
        self,
        conn: sqlite3.Connection,
        *,
        since_iso: Optional[str],
        limit: int,
    ) -> List[ZettelDraft]:
        records = self._terminal_records(conn, since_iso=since_iso, only_uncarded=True)
        return [self._draft(record) for record in records[:limit]]

    def count_uncarded(
        self,
        conn: sqlite3.Connection,
        *,
        since_iso: Optional[str],
    ) -> int:
        return len(self._terminal_records(conn, since_iso=since_iso, only_uncarded=True))

    def stamp(
        self,
        conn: sqlite3.Connection,
        draft: ZettelDraft,
        zettel_id: str,
    ) -> None:
        """Entries are idempotent by assistant placeholder ID, not a source stamp."""

    def gather_context(
        self,
        conn: sqlite3.Connection,
        source_ids: Sequence[str],
    ) -> Dict[str, Dict[str, Any]]:
        requested = {str(source_id) for source_id in source_ids}
        return {
            record["assistant_id"]: self._context(record)
            for record in self._terminal_records(conn, since_iso=None, only_uncarded=False)
            if record["assistant_id"] in requested
        }

    def _terminal_records(
        self,
        conn: sqlite3.Connection,
        *,
        since_iso: Optional[str],
        only_uncarded: bool,
    ) -> List[Dict[str, Any]]:
        clauses = [
            "assistant.role = 'assistant'",
            "assistant.metadata IS NOT NULL",
        ]
        if only_uncarded:
            clauses.append(
                "NOT EXISTS ("
                "SELECT 1 FROM zettel_entries entry "
                "WHERE entry.source_kind = 'conversation_turn' "
                "AND entry.source_id = assistant.id"
                ")"
            )
        params: List[Any] = []
        if since_iso:
            clauses.append("assistant.timestamp >= ?")
            params.append(since_iso)
        rows = conn.execute(
            f"""
            SELECT assistant.id AS assistant_id, assistant.conversation_id,
                   assistant.content AS assistant_content, assistant.metadata,
                   assistant.timestamp AS assistant_timestamp, assistant.rowid AS assistant_rowid
            FROM conversation_messages assistant
            WHERE {' AND '.join(clauses)}
            ORDER BY assistant.timestamp ASC, assistant.rowid ASC
            """,
            params,
        ).fetchall()
        records: List[Dict[str, Any]] = []
        for row in rows:
            metadata = _decode_metadata(row["metadata"])
            turn = parse_conversation_turn_metadata(metadata)
            if turn is None or not is_terminal_conversation_turn_lifecycle(turn.lifecycle):
                continue
            user = self._user_message_for_turn(
                conn,
                conversation_id=str(row["conversation_id"]),
                assistant_rowid=int(row["assistant_rowid"]),
                user_message_id=turn.user_message_id,
            )
            if user is None:
                continue
            occurred_at = to_utc_iso(user["timestamp"])
            ended_at = to_utc_iso(row["assistant_timestamp"])
            if occurred_at is None or ended_at is None:
                continue
            records.append(
                {
                    "assistant_id": str(row["assistant_id"]),
                    "conversation_id": str(row["conversation_id"]),
                    "assistant_content": str(row["assistant_content"] or ""),
                    "assistant_timestamp": ended_at,
                    "user_id": str(user["id"]),
                    "user_content": str(user["content"] or ""),
                    "user_timestamp": occurred_at,
                    "route": turn.route.value,
                    "lifecycle": turn.lifecycle.value,
                    "terminal_outcome": turn.terminal_outcome,
                    "agent_task_id": turn.agent_task_id,
                    "agent_task": self._agent_task_context(conn, turn.agent_task_id),
                }
            )
        return records

    def _user_message_for_turn(
        self,
        conn: sqlite3.Connection,
        *,
        conversation_id: str,
        assistant_rowid: int,
        user_message_id: Optional[str],
    ) -> Optional[sqlite3.Row]:
        if user_message_id:
            return conn.execute(
                """
                SELECT id, content, timestamp
                FROM conversation_messages
                WHERE id = ? AND conversation_id = ? AND role = 'user'
                """,
                (user_message_id, conversation_id),
            ).fetchone()
        return conn.execute(
            """
            SELECT id, content, timestamp
            FROM conversation_messages
            WHERE conversation_id = ? AND role = 'user' AND rowid < ?
            ORDER BY rowid DESC
            LIMIT 1
            """,
            (conversation_id, assistant_rowid),
        ).fetchone()

    def _agent_task_context(
        self,
        conn: sqlite3.Connection,
        agent_task_id: Optional[str],
    ) -> Optional[Dict[str, Any]]:
        if not agent_task_id:
            return None
        row = conn.execute(
            "SELECT status, result_data FROM agent_tasks WHERE id = ?",
            (agent_task_id,),
        ).fetchone()
        if row is None:
            return {"id": agent_task_id, "status": "missing", "result_data": None}
        return {
            "id": agent_task_id,
            "status": row["status"],
            "result_data": _decode_metadata(row["result_data"]),
        }

    def _draft(self, record: Dict[str, Any]) -> ZettelDraft:
        title_text = truncate(record["user_content"], 120)
        return ZettelDraft(
            source_kind=self.source_kind,
            source_id=record["assistant_id"],
            event_type="conversation_turn",
            occurred_at=record["user_timestamp"],
            ended_at=record["assistant_timestamp"],
            title=f"Conversation: {title_text}" if title_text else "Conversation turn",
            summary=record["assistant_content"] or record["terminal_outcome"],
            outcome=record["lifecycle"],
            source_status=record["lifecycle"],
            payload={
                "conversation_id": record["conversation_id"],
                "user_message_id": record["user_id"],
                "assistant_message_id": record["assistant_id"],
                "route": record["route"],
                "lifecycle": record["lifecycle"],
                "agent_task_id": record["agent_task_id"],
                "terminal_outcome": record["terminal_outcome"],
            },
        )

    @staticmethod
    def _context(record: Dict[str, Any]) -> Dict[str, Any]:
        context = {
            "user_message": record["user_content"],
            "assistant_message": record["assistant_content"],
            "route": record["route"],
            "lifecycle": record["lifecycle"],
            "terminal_outcome": record["terminal_outcome"],
        }
        if record["agent_task"] is not None:
            context["agent_task"] = record["agent_task"]
        return context


def _decode_metadata(raw_metadata: Any) -> Dict[str, Any]:
    try:
        decoded = json.loads(raw_metadata) if raw_metadata else {}
    except (TypeError, ValueError):
        return {}
    return decoded if isinstance(decoded, dict) else {}
