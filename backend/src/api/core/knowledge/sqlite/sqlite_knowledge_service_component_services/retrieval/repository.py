"""SQLite metadata repository for rebuildable retrieval-vector generations."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

from api.services.retrieval.contracts import RetrievalDocument


class RetrievalRepository:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path

    def state(self, conn, model: str):
        return conn.execute(
            "SELECT * FROM retrieval_index_state WHERE embedding_model = ?", (model,)
        ).fetchone()

    def matches_generation(
        self, conn, model: str, documents: list[RetrievalDocument]
    ) -> bool:
        """Return True when active metadata matches the proposed document set."""
        state = self.state(conn, model)
        if not state or not state["generation_id"]:
            return False
        if int(state["document_count"] or 0) != len(documents):
            return False
        proposed = {document.document_id: document.content_digest for document in documents}
        rows = conn.execute(
            """
            SELECT document_id, content_digest, is_active
            FROM retrieval_documents
            WHERE embedding_model = ?
            """,
            (model,),
        ).fetchall()
        active = {
            row["document_id"]: row["content_digest"]
            for row in rows
            if row["is_active"]
        }
        if active != proposed:
            return False
        inactive_ids = {
            row["document_id"]
            for row in rows
            if not row["is_active"]
        }
        return not (inactive_ids & set(proposed))

    def replace_generation(
        self, conn, model: str, dimension: int, generation_id: str,
        documents: Iterable[RetrievalDocument],
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        docs = list(documents)
        conn.execute(
            "UPDATE retrieval_documents SET is_active = 0 WHERE embedding_model = ?",
            (model,),
        )
        for vector_id, document in enumerate(docs):
            conn.execute(
                """
                INSERT INTO retrieval_documents (
                    document_id, source_kind, source_id, content_digest, occurred_at,
                    updated_at, embedding_model, embedding_dimension, vector_id,
                    generation_id, indexed_at, is_active
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                ON CONFLICT(document_id) DO UPDATE SET
                    source_kind=excluded.source_kind, source_id=excluded.source_id,
                    content_digest=excluded.content_digest, occurred_at=excluded.occurred_at,
                    updated_at=excluded.updated_at, embedding_model=excluded.embedding_model,
                    embedding_dimension=excluded.embedding_dimension, vector_id=excluded.vector_id,
                    generation_id=excluded.generation_id, indexed_at=excluded.indexed_at,
                    is_active=1
                """,
                (
                    document.document_id, document.source_kind, document.source_id,
                    document.content_digest, document.occurred_at, document.updated_at,
                    model, dimension, vector_id, generation_id, now,
                ),
            )
        conn.execute(
            """
            INSERT INTO retrieval_index_state (
                embedding_model, embedding_dimension, generation_id, document_count,
                completed_at, last_error
            ) VALUES (?, ?, ?, ?, ?, NULL)
            ON CONFLICT(embedding_model) DO UPDATE SET
                embedding_dimension=excluded.embedding_dimension,
                generation_id=excluded.generation_id,
                document_count=excluded.document_count,
                completed_at=excluded.completed_at,
                last_error=NULL
            """,
            (model, dimension, generation_id, len(docs), now),
        )
        conn.execute(
            "DELETE FROM retrieval_documents WHERE embedding_model = ? AND is_active = 0",
            (model,),
        )

    def mark_failed(self, conn, model: str, error: str) -> None:
        conn.execute(
            """
            INSERT INTO retrieval_index_state (
                embedding_model, embedding_dimension, document_count, last_error
            ) VALUES (?, 0, 0, ?)
            ON CONFLICT(embedding_model) DO UPDATE SET last_error=excluded.last_error
            """,
            (model, error[:2000]),
        )
