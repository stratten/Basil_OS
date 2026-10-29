"""Bounded retrieval projection for finalized Zettel entries."""

from __future__ import annotations

import hashlib
import sqlite3
from typing import Iterable, Optional

from api.services.retrieval.contracts import RetrievalDocument

_SEARCH_TEXT_LIMIT = 4000
_TITLE_LIMIT = 200


def _bounded(value: object, limit: int) -> str:
    return str(value or "")[:limit]


def _retrieval_text_parts(row: sqlite3.Row) -> tuple[str, str, str, str]:
    title = _bounded(row["title"], _TITLE_LIMIT)
    summary = _bounded(row["summary"], 3000)
    narrative = _bounded(row["narrative"], 3000)
    outcome = _bounded(row["outcome"], 1000)
    return title, summary, narrative, outcome


def build_zettel_fts_content(row: sqlite3.Row) -> str:
    """Return the bounded text shared by exact and semantic retrieval."""
    title, summary, narrative, outcome = _retrieval_text_parts(row)
    return _bounded(
        "\n".join(part for part in (title, summary, narrative, outcome) if part),
        _SEARCH_TEXT_LIMIT,
    )


def finalized_zettel_digest(row: sqlite3.Row) -> str:
    """Digest contract for FAISS staleness detection."""
    digest_input = "|".join(
        str(row[key] or "")
        for key in (
            "id",
            "content_digest",
            "title",
            "summary",
            "outcome",
            "narrative",
            "narrative_at",
        )
    )
    return hashlib.sha256(digest_input.encode()).hexdigest()


def zettel_card_document(row: sqlite3.Row) -> RetrievalDocument:
    title, summary, narrative, outcome = _retrieval_text_parts(row)
    return RetrievalDocument(
        document_id=f"{row['source_kind']}:{row['source_id']}",
        source_kind=str(row["source_kind"]),
        source_id=str(row["source_id"]),
        occurred_at=str(row["occurred_at"]),
        updated_at=str(row["narrative_at"] or row["materialized_at"]),
        title=title,
        search_text=build_zettel_fts_content(row),
        content_digest=finalized_zettel_digest(row),
        metadata={
            "representation": "zettel",
            "summary": summary,
            "outcome": row["outcome"],
            "narrative_state": row["narrative_state"],
        },
    )


def finalized_zettel_document(row: sqlite3.Row) -> RetrievalDocument:
    """Build a bounded retrieval document for one finalized Zettel row."""
    if row["narrative_state"] != "final":
        raise ValueError("finalized_zettel_document requires narrative_state='final'")
    return zettel_card_document(row)


def iter_finalized_zettel_documents(
    conn: sqlite3.Connection,
    *,
    source_kind: Optional[str] = None,
) -> Iterable[RetrievalDocument]:
    """Yield finalized Zettel documents with non-empty retrieval text."""
    query = "SELECT * FROM zettel_entries WHERE narrative_state = 'final'"
    params: list[object] = []
    if source_kind is not None:
        query += " AND source_kind = ?"
        params.append(source_kind)
    query += " ORDER BY occurred_at, id"
    rows = conn.execute(query, params).fetchall()
    for row in rows:
        if build_zettel_fts_content(row):
            yield finalized_zettel_document(row)
