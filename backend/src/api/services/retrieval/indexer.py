"""Full, atomic rebuild of the local exact-NumPy retrieval sidecar."""

from __future__ import annotations

import uuid
from typing import Any

import numpy as np

from api.core.models.embeddings.embedding_model_manager import get_global_embedding_manager
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.infrastructure.connection import (
    get_sync_connection,
)
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.retrieval.repository import (
    RetrievalRepository,
)
from api.services.retrieval.contracts import RetrievalDocument
from api.services.retrieval.zettel_projection import iter_finalized_zettel_documents

from .numpy_vector_sidecar import NumpyVectorSidecar

DEFAULT_EMBEDDING_MODEL = "all-MiniLM-L6-v2"


class RetrievalIndexer:
    def __init__(self, db_path: str, registry, model: str = DEFAULT_EMBEDDING_MODEL) -> None:
        self.db_path = db_path
        self.registry = registry
        self.model = model
        self._repository = RetrievalRepository(db_path)

    def rebuild(self) -> dict[str, Any]:
        return self._rebuild_documents(self._collect_documents())

    def rebuild_if_stale(self) -> dict[str, Any]:
        documents = self._collect_documents()
        with get_sync_connection(self.db_path) as conn:
            state = self._repository.state(conn, self.model)
            if self._repository.matches_generation(conn, self.model, documents):
                if not documents or (
                    state is not None
                    and NumpyVectorSidecar(self.db_path, self.model).load(
                        state["generation_id"],
                        int(state["embedding_dimension"]),
                        int(state["document_count"]),
                    )
                    is not None
                ):
                    return {
                        "rebuilt": False,
                        "reason": "current",
                        "document_count": len(documents),
                    }
        return self._rebuild_documents(documents)

    def _collect_documents(self) -> list[RetrievalDocument]:
        with get_sync_connection(self.db_path) as conn:
            documents = list(iter_finalized_zettel_documents(conn))
        documents.sort(key=lambda item: (item.source_kind, item.occurred_at, item.document_id))
        return documents

    def _rebuild_documents(self, documents: list[RetrievalDocument]) -> dict[str, Any]:
        manager = get_global_embedding_manager()
        manager.begin_use(self.model)
        sidecar = NumpyVectorSidecar(self.db_path, self.model)
        try:
            if not documents:
                generation_id = str(uuid.uuid4())
                with get_sync_connection(self.db_path) as conn:
                    self._repository.replace_generation(
                        conn, self.model, 0, generation_id, []
                    )
                    conn.commit()
                sidecar.remove_current_generation()
                sidecar.remove_legacy_faiss_generations()
                return {
                    "rebuilt": True,
                    "generation_id": generation_id,
                    "document_count": 0,
                    "dimension": 0,
                }

            model = manager.get(self.model)
            vectors = np.asarray(
                model.encode(
                    [document.search_text for document in documents],
                    convert_to_numpy=True,
                    normalize_embeddings=True,
                ),
                dtype=np.float32,
            )
            dimension = int(vectors.shape[1])
            generation_id = str(uuid.uuid4())
            previous_manifest = sidecar.snapshot_current_manifest()
            sidecar.publish(generation_id, vectors, dimension, len(documents))
            try:
                with get_sync_connection(self.db_path) as conn:
                    self._repository.replace_generation(
                        conn, self.model, dimension, generation_id, documents
                    )
                    conn.commit()
            except Exception:
                sidecar.restore_current_manifest(previous_manifest)
                raise
            sidecar.remove_legacy_faiss_generations()
            return {
                "rebuilt": True,
                "generation_id": generation_id,
                "document_count": len(documents),
                "dimension": dimension,
            }
        except Exception as exc:
            with get_sync_connection(self.db_path) as conn:
                self._repository.mark_failed(conn, self.model, str(exc))
                conn.commit()
            raise
        finally:
            manager.end_use(self.model)
