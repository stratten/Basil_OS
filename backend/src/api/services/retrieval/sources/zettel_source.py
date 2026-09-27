"""Retrieval adapters backed by canonical zettel projections."""

from __future__ import annotations

from typing import Any, Dict, Iterable, Optional

from api.services.zettel.sources.base import sources_by_kind

from ..contracts import (
    RetrievalCandidate,
    RetrievalDocument,
    RetrievalSourceDescriptor,
)
from ..zettel_projection import (
    iter_finalized_zettel_documents,
    zettel_card_document,
)


class ZettelBackedRetrievalSource:
    """One searchable, non-agent zettel source family."""

    _DESCRIPTORS = {
        "transcription": RetrievalSourceDescriptor(
            source_kind="transcription",
            display_name="Recorded transcriptions",
            authority="primary",
            evidence_kind="observed spoken text captured by Basil",
            browse_guidance="Use for recorded transcriptions within a time range.",
            detail_guidance="Use detail to obtain the source-specific context.",
            supported_actions=("browse", "search", "aggregate", "detail"),
        ),
        "assistant_output": RetrievalSourceDescriptor(
            source_kind="assistant_output",
            display_name="Basil assistant outputs",
            authority="derived",
            evidence_kind="generated Basil output",
            browse_guidance="Use for prior generated output and its timeline.",
            detail_guidance="Use detail to obtain the source-specific context.",
            supported_actions=("browse", "search", "aggregate", "detail"),
        ),
        "scheduled_run": RetrievalSourceDescriptor(
            source_kind="scheduled_run",
            display_name="Scheduled Basil runs",
            authority="primary",
            evidence_kind="Basil task-run record",
            browse_guidance="Use for scheduled-task execution history.",
            detail_guidance="Use detail to obtain the source-specific context.",
            supported_actions=("browse", "search", "aggregate", "detail"),
        ),
        "conversation": RetrievalSourceDescriptor(
            source_kind="conversation",
            display_name="Basil conversations",
            authority="primary",
            evidence_kind="user and assistant conversation record",
            browse_guidance="Use for historical conversations outside the active thread.",
            detail_guidance="Use detail to obtain the source-specific context.",
            supported_actions=("browse", "search", "aggregate", "detail"),
        ),
        "screen_block": RetrievalSourceDescriptor(
            source_kind="screen_block",
            display_name="Screen activity blocks",
            authority="primary",
            evidence_kind="bounded screen and OCR observation",
            browse_guidance="Use for historical screen activity, not full application records.",
            detail_guidance="Use detail to obtain the source-specific context.",
            supported_actions=("browse", "search", "aggregate", "detail"),
        ),
        "meeting": RetrievalSourceDescriptor(
            source_kind="meeting",
            display_name="Recorded Basil meetings",
            authority="primary",
            evidence_kind="observed Basil meeting recording and transcript",
            browse_guidance="Use for recorded meetings in a requested time range; cards are grouped logical meetings.",
            detail_guidance="Use detail for current merged transcript, metadata, and meeting analyses.",
            supported_actions=("browse", "search", "aggregate", "detail"),
        ),
    }

    def __init__(self, source_kind: str) -> None:
        if source_kind == "agent_task":
            raise ValueError("agent_task is owned by AgentTaskRootSource")
        self.source_kind = source_kind

    def describe(self) -> RetrievalSourceDescriptor:
        return self._DESCRIPTORS[self.source_kind]

    def iter_documents(self, conn) -> Iterable[RetrievalDocument]:
        yield from iter_finalized_zettel_documents(conn, source_kind=self.source_kind)

    def search_exact(
        self, conn, query: str, start: Optional[str], end: Optional[str], limit: int
    ) -> Iterable[RetrievalCandidate]:
        tokens = [token for token in query.split() if token]
        if not tokens:
            return []
        fts = " AND ".join(f'"{token.replace(chr(34), "")}"*' for token in tokens)
        clauses = [
            "zettel_search_fts MATCH ?",
            "fts.source_kind = ?",
        ]
        params: list[Any] = [fts, self.source_kind]
        if start:
            clauses.append("fts.occurred_at >= ?")
            params.append(start)
        if end:
            clauses.append("fts.occurred_at <= ?")
            params.append(end)
        candidate_limit = max(1, limit * 3)
        params.append(candidate_limit)
        rows = conn.execute(
            f"""
            SELECT zettel_entries.id, zettel_entries.source_kind, zettel_entries.source_id,
                   bm25(zettel_search_fts) AS rank
            FROM zettel_search_fts AS fts
            JOIN zettel_entries
              ON fts.entry_id = zettel_entries.id
            WHERE {' AND '.join(clauses)}
            ORDER BY rank ASC, fts.occurred_at DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
        raw_clauses = ["zettel_raw_search_fts MATCH ?", "source_kind = ?"]
        raw_params: list[Any] = [fts, self.source_kind]
        if start:
            raw_clauses.append("occurred_at >= ?")
            raw_params.append(start)
        if end:
            raw_clauses.append("occurred_at <= ?")
            raw_params.append(end)
        raw_params.append(candidate_limit)
        raw_rows = conn.execute(
            f"SELECT document_id, bm25(zettel_raw_search_fts) AS rank "
            f"FROM zettel_raw_search_fts WHERE {' AND '.join(raw_clauses)} "
            "ORDER BY rank ASC, occurred_at DESC LIMIT ?",
            raw_params,
        ).fetchall()
        return [
            RetrievalCandidate(
                f"{row['source_kind']}:{row['source_id']}",
                float(-row["rank"]),
                "exact_fts:zettel",
            )
            for row in rows
        ] + [
            RetrievalCandidate(str(row["document_id"]), float(-row["rank"]), "exact_fts:raw")
            for row in raw_rows
        ]

    def hydrate(self, conn, source_id: str) -> Optional[RetrievalDocument]:
        row = conn.execute(
            "SELECT * FROM zettel_entries WHERE source_kind = ? AND source_id = ?",
            (self.source_kind, source_id),
        ).fetchone()
        if row is not None:
            return zettel_card_document(row)
        raw = conn.execute(
            """
            SELECT * FROM zettel_raw_search_fts
            WHERE document_id = ? AND source_kind = ?
            """,
            (f"{self.source_kind}:{source_id}", self.source_kind),
        ).fetchone()
        if raw is None:
            return None
        return RetrievalDocument(
            document_id=str(raw["document_id"]),
            source_kind=str(raw["source_kind"]),
            source_id=str(raw["source_id"]),
            occurred_at=str(raw["occurred_at"]),
            updated_at=str(raw["occurred_at"]),
            title=str(raw["title"]),
            search_text=str(raw["content"]),
            content_digest="raw:" + str(raw["document_id"]),
            metadata={
                "representation": "raw",
                "summary": raw["summary"],
                "outcome": raw["outcome"],
                "narrative_state": None,
            },
        )

    def detail(self, conn, source_id: str) -> Optional[Dict[str, Any]]:
        document = self.hydrate(conn, source_id)
        if document is None:
            return None
        source = sources_by_kind().get(self.source_kind)
        context = source.gather_context(conn, [source_id]) if source else {}
        return {
            "source_kind": self.source_kind,
            "source_id": source_id,
            "document": document.metadata,
            "context": context.get(source_id, {}),
            "detail_available": bool(context.get(source_id, {})),
        }
