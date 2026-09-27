"""Canonical retrieval adapter for root agent-task chains."""

from __future__ import annotations

import hashlib
from typing import Any, Dict, Iterable, Optional

from ..contracts import (
    RetrievalCandidate,
    RetrievalDocument,
    RetrievalSourceDescriptor,
)


def _text(value: Any, limit: int = 8000) -> str:
    return str(value or "")[:limit]


class AgentTaskRootSource:
    source_kind = "agent_task"

    def describe(self) -> RetrievalSourceDescriptor:
        return RetrievalSourceDescriptor(
            source_kind=self.source_kind,
            display_name="Basil agent-task chains",
            authority="primary",
            evidence_kind="durable Agent Task request and result history",
            browse_guidance="Use for prior Agent Task chains and completed work.",
            detail_guidance="Use detail to obtain the task-chain turns and durable results.",
            supported_actions=("browse", "search", "aggregate", "detail"),
        )

    def iter_documents(self, conn) -> Iterable[RetrievalDocument]:
        rows = conn.execute(
            """
            SELECT root.id, root.title, root.original_prompt, root.result_preview,
                   root.last_turn_timestamp, root.timestamp, root.latest_status,
                   root.latest_agent_task_id, f.content
            FROM agent_tasks root
            JOIN agent_task_search_fts f ON f.root_task_id = root.id
            WHERE COALESCE(root.root_task_id, root.id) = root.id
            """
        ).fetchall()
        for row in rows:
            yield self._document(row)

    def search_exact(
        self, conn, query: str, start: Optional[str], end: Optional[str], limit: int
    ) -> Iterable[RetrievalCandidate]:
        tokens = [token for token in query.split() if token]
        if not tokens:
            return []
        fts = " AND ".join(f'"{token.replace(chr(34), "")}"*' for token in tokens)
        clauses = ["agent_task_search_fts MATCH ?"]
        params: list[Any] = [fts]
        if start:
            clauses.append("COALESCE(root.last_turn_timestamp, root.timestamp) >= ?")
            params.append(start)
        if end:
            clauses.append("COALESCE(root.last_turn_timestamp, root.timestamp) <= ?")
            params.append(end)
        params.append(limit)
        rows = conn.execute(
            f"""
            SELECT root.id
            FROM agent_task_search_fts
            JOIN agent_tasks root ON root.id = agent_task_search_fts.root_task_id
            WHERE {' AND '.join(clauses)}
            ORDER BY COALESCE(root.last_turn_timestamp, root.timestamp) DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
        return [
            RetrievalCandidate(f"agent_task:{row['id']}", 1.0 / (index + 1), "exact_rank")
            for index, row in enumerate(rows)
        ]

    def hydrate(self, conn, source_id: str) -> Optional[RetrievalDocument]:
        row = conn.execute(
            """
            SELECT root.id, root.title, root.original_prompt, root.result_preview,
                   root.last_turn_timestamp, root.timestamp, root.latest_status,
                   root.latest_agent_task_id, f.content
            FROM agent_tasks root
            JOIN agent_task_search_fts f ON f.root_task_id = root.id
            WHERE root.id = ?
            """,
            (source_id,),
        ).fetchone()
        return self._document(row) if row else None

    def detail(self, conn, source_id: str) -> Optional[Dict[str, Any]]:
        rows = conn.execute(
            """
            SELECT id, timestamp, title, original_prompt, status, result_data,
                   root_task_id, previous_task_id, chain_sequence_number
            FROM agent_tasks
            WHERE id = ? OR root_task_id = ?
            ORDER BY chain_sequence_number ASC, timestamp ASC
            """,
            (source_id, source_id),
        ).fetchall()
        if not rows:
            return None
        return {
            "root_task_id": source_id,
            "turns": [dict(row) for row in rows],
            "detail_available": True,
        }

    def _document(self, row) -> RetrievalDocument:
        occurred = str(row["last_turn_timestamp"] or row["timestamp"])
        search_text = _text(row["content"])
        digest_input = "|".join(
            str(row[key] or "")
            for key in ("id", "last_turn_timestamp", "latest_status", "latest_agent_task_id", "content")
        )
        return RetrievalDocument(
            document_id=f"agent_task:{row['id']}",
            source_kind=self.source_kind,
            source_id=str(row["id"]),
            occurred_at=occurred,
            updated_at=occurred,
            title=_text(row["title"] or row["original_prompt"], 200),
            search_text=search_text,
            content_digest=hashlib.sha256(digest_input.encode()).hexdigest(),
            metadata={
                "status": row["latest_status"],
                "prompt": _text(row["original_prompt"], 800),
                "result_preview": _text(row["result_preview"], 2000),
            },
        )
