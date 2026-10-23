"""Tests for unified retrieval ranking and semantic filtering."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

import numpy as np
import pytest

from api.services.retrieval.contracts import (
    RetrievalAggregateRequest,
    RetrievalBrowseRequest,
    RetrievalCandidate,
    RetrievalDetailRequest,
    RetrievalDocument,
    RetrievalSearchRequest,
)
from api.services.retrieval.service import UnifiedRetrievalService, _fuse_ranked_candidates
from api.services.zettel.sources.base import ZettelDraft
from api.services.retrieval.sources.zettel_source import ZettelBackedRetrievalSource
from api.services.zettel import store


class _ConnectionContext:
    def __init__(self, conn) -> None:
        self._conn = conn

    def __enter__(self):
        return self._conn

    def __exit__(self, *exc_info):
        return False


@dataclass(frozen=True)
class FakeSource:
    source_kind: str
    exact_ids: list[str] = field(default_factory=list)

    def iter_documents(self, conn) -> Iterable[RetrievalDocument]:
        return []

    def search_exact(
        self, conn, query: str, start: Optional[str], end: Optional[str], limit: int
    ) -> Iterable[RetrievalCandidate]:
        return [
            RetrievalCandidate(document_id, float(len(self.exact_ids) - index), "exact_fts")
            for index, document_id in enumerate(self.exact_ids[:limit])
        ]

    def hydrate(self, conn, source_id: str) -> Optional[RetrievalDocument]:
        return RetrievalDocument(
            document_id=f"{self.source_kind}:{source_id}",
            source_kind=self.source_kind,
            source_id=source_id,
            occurred_at="2026-07-24T10:00:00+00:00",
            updated_at="2026-07-24T10:00:00+00:00",
            title=f"Title {source_id}",
            search_text=f"Body {source_id}",
            content_digest="digest",
            metadata={},
        )

    def detail(self, conn, source_id: str) -> Optional[dict[str, Any]]:
        return {"source_id": source_id}


class FakeRegistry:
    def __init__(self, sources: list[FakeSource]) -> None:
        self._sources = {source.source_kind: source for source in sources}

    def sources(self, selected: list[str] | None = None) -> list[FakeSource]:
        if selected is None:
            return list(self._sources.values())
        return [self._sources[kind] for kind in selected]

    def require(self, source_kind: str) -> FakeSource:
        return self._sources[source_kind]


def test_rrf_prefers_semantic_only_candidate_when_exact_is_weaker():
    fused = _fuse_ranked_candidates(
        exact_ids=["transcription:weak"],
        semantic_ids=["transcription:strong"],
        limit=2,
    )
    assert fused[0][0] == "transcription:strong"
    assert fused[0][2] == "hybrid_rrf:semantic"


def test_rrf_boosts_overlap_candidate():
    fused = _fuse_ranked_candidates(
        exact_ids=["transcription:shared", "transcription:exact-only"],
        semantic_ids=["transcription:shared", "transcription:semantic-only"],
        limit=3,
    )
    assert fused[0][0] == "transcription:shared"
    assert fused[0][2] == "hybrid_rrf:exact+semantic"


def test_hybrid_falls_back_to_exact_when_semantic_not_built(conn, monkeypatch):
    service = UnifiedRetrievalService(
        ":memory:",
        FakeRegistry([FakeSource("transcription", exact_ids=["transcription:one"])]),
    )
    monkeypatch.setattr(
        "api.services.retrieval.service.get_sync_connection",
        lambda *args, **kwargs: _ConnectionContext(conn),
    )
    monkeypatch.setattr(
        service,
        "_semantic_candidate_ids",
        lambda *args, **kwargs: ([], "not_built", {}),
    )

    result = service.search(
        RetrievalSearchRequest(query="contract", mode="hybrid", source_kinds=["transcription"])
    )

    assert result["semantic_status"] == "not_built"
    assert result["count"] == 1
    assert result["results"][0]["document_id"] == "transcription:one"


def test_semantic_filters_exclude_out_of_range_documents(conn, monkeypatch):
    service = UnifiedRetrievalService(
        ":memory:",
        FakeRegistry([FakeSource("transcription")]),
    )
    monkeypatch.setattr(
        "api.services.retrieval.service.get_sync_connection",
        lambda *args, **kwargs: _ConnectionContext(conn),
    )

    def _semantic(query, source_kinds, start, end, candidate_limit):
        assert start == "2026-07-24T00:00:00+00:00"
        assert end == "2026-07-24T23:59:59+00:00"
        return ["transcription:in-range"], "ready", {"transcription:in-range": 0.91}

    monkeypatch.setattr(service, "_semantic_candidate_ids", _semantic)
    result = service.search(
        RetrievalSearchRequest(
            query="budget",
            mode="semantic",
            source_kinds=["transcription"],
            start="2026-07-24T00:00:00+00:00",
            end="2026-07-24T23:59:59+00:00",
        )
    )

    assert result["semantic_status"] == "ready"
    assert result["results"][0]["document_id"] == "transcription:in-range"
    assert result["results"][0]["score_kind"] == "semantic_cosine"


def test_semantic_search_scans_past_global_neighbors_excluded_by_filter(
    conn, monkeypatch
):
    conn.execute(
        """
        INSERT INTO retrieval_index_state (
            embedding_model, embedding_dimension, generation_id, document_count
        ) VALUES ('all-MiniLM-L6-v2', 2, 'generation', 3)
        """
    )
    conn.executemany(
        """
        INSERT INTO retrieval_documents (
            document_id, source_kind, source_id, content_digest, occurred_at,
            updated_at, embedding_model, embedding_dimension, vector_id,
            generation_id, indexed_at, is_active
        ) VALUES (?, ?, ?, 'digest', ?, ?, 'all-MiniLM-L6-v2', 2, ?, 'generation', ?, 1)
        """,
        [
            ("assistant_output:outside-1", "assistant_output", "outside-1", "2026-07-24T10:00:00+00:00", "2026-07-24T10:00:00+00:00", 0, "2026-07-24T10:00:00+00:00"),
            ("assistant_output:outside-2", "assistant_output", "outside-2", "2026-07-24T10:00:00+00:00", "2026-07-24T10:00:00+00:00", 1, "2026-07-24T10:00:00+00:00"),
            ("transcription:eligible", "transcription", "eligible", "2026-07-24T10:00:00+00:00", "2026-07-24T10:00:00+00:00", 2, "2026-07-24T10:00:00+00:00"),
        ],
    )
    conn.commit()

    class FakeSidecar:
        def __init__(self, *args, **kwargs):
            pass

        def load(self, *args, **kwargs):
            return np.array(
                [[0.0, 1.0], [0.0, 0.5], [1.0, 0.0]],
                dtype=np.float32,
            )

    class FakeManager:
        def begin_use(self, model):
            pass

        def end_use(self, model):
            pass

        def get(self, model):
            return self

        def encode(self, texts, **kwargs):
            return np.array([[1.0, 0.0]], dtype=np.float32)

    service = UnifiedRetrievalService(
        "unused.db",
        FakeRegistry([FakeSource("transcription")]),
    )
    monkeypatch.setattr(
        "api.services.retrieval.service.get_sync_connection",
        lambda *args, **kwargs: _ConnectionContext(conn),
    )
    monkeypatch.setattr("api.services.retrieval.service.NumpyVectorSidecar", FakeSidecar)
    monkeypatch.setattr(
        "api.core.models.embeddings.embedding_model_manager.get_global_embedding_manager",
        lambda: FakeManager(),
    )

    ranked, status, scores = service._semantic_candidate_ids(
        "query", ["transcription"], None, None, candidate_limit=1
    )

    assert status == "ready"
    assert ranked == ["transcription:eligible"]
    assert scores["transcription:eligible"] == pytest.approx(1.0)


def test_exact_mode_preserves_source_scores(conn, monkeypatch):
    service = UnifiedRetrievalService(
        ":memory:",
        FakeRegistry([FakeSource("transcription", exact_ids=["transcription:one", "transcription:two"])]),
    )
    monkeypatch.setattr(
        "api.services.retrieval.service.get_sync_connection",
        lambda *args, **kwargs: _ConnectionContext(conn),
    )
    monkeypatch.setattr(
        service,
        "_semantic_candidate_ids",
        lambda *args, **kwargs: ([], "not_requested", {}),
    )

    result = service.search(
        RetrievalSearchRequest(query="budget", mode="exact", source_kinds=["transcription"], limit=1)
    )

    assert result["count"] == 1
    assert result["results"][0]["score_kind"] == "exact_fts"
    assert result["truncated"] is True


def test_exact_and_hybrid_modes_return_uncarded_raw_document(conn, monkeypatch):
    from api.services.retrieval.registry import build_default_retrieval_registry

    conn.execute(
        """
        INSERT INTO transcriptions (
            id, timestamp, transcription_text, model_name, status, zettel_id, audio_file_path
        ) VALUES (
            'raw-search-1', '2026-07-29T15:00:00+00:00', 'zebra raw retrieval phrase', 'm', 'completed', NULL, '/tmp/raw-search-1.wav'
        )
        """
    )
    conn.commit()
    source = ZettelBackedRetrievalSource("transcription")
    hits = list(source.search_exact(conn, "zebra", None, None, 10))
    assert len(hits) == 1
    assert hits[0].document_id == "transcription:raw-search-1"
    assert hits[0].score_kind == "exact_fts:raw"
    document = source.hydrate(conn, "raw-search-1")
    assert document is not None
    assert document.metadata["representation"] == "raw"

    service = UnifiedRetrievalService(":memory:", build_default_retrieval_registry())
    monkeypatch.setattr(
        "api.services.retrieval.service.get_sync_connection",
        lambda *args, **kwargs: _ConnectionContext(conn),
    )
    monkeypatch.setattr(
        service,
        "_semantic_candidate_ids",
        lambda *args, **kwargs: ([], "not_built", {}),
    )
    for mode in ("exact", "hybrid"):
        result = service.search(
            RetrievalSearchRequest(query="zebra", mode=mode, source_kinds=["transcription"])
        )
        assert result["count"] == 1
        assert result["results"][0]["document_id"] == "transcription:raw-search-1"
        assert result["results"][0]["metadata"]["representation"] == "raw"


def test_exact_mode_returns_pending_card_with_zettel_representation(conn):
    store.insert_card(
        conn,
        ZettelDraft(
            source_kind="transcription",
            source_id="pending-card-1",
            event_type="transcription",
            occurred_at="2026-07-29T16:00:00+00:00",
            title="Pending zebra card",
            summary="pending zebra card summary",
        ),
    )
    conn.commit()
    source = ZettelBackedRetrievalSource("transcription")
    hits = list(source.search_exact(conn, "zebra", None, None, 10))
    assert len(hits) == 1
    assert hits[0].document_id == "transcription:pending-card-1"
    document = source.hydrate(conn, "pending-card-1")
    assert document.metadata["representation"] == "zettel"
    assert document.metadata["narrative_state"] == "pending"


def test_semantic_mode_excludes_raw_and_pending_cards(conn, monkeypatch):
    conn.execute(
        """
        INSERT INTO transcriptions (
            id, timestamp, transcription_text, model_name, status, zettel_id, audio_file_path
        ) VALUES (
            'raw-semantic-1', '2026-07-29T17:00:00+00:00', 'semantic raw zebra phrase', 'm', 'completed', NULL, '/tmp/raw-semantic-1.wav'
        )
        """
    )
    store.insert_card(
        conn,
        ZettelDraft(
            source_kind="transcription",
            source_id="pending-semantic-1",
            event_type="transcription",
            occurred_at="2026-07-29T17:30:00+00:00",
            title="Pending semantic zebra card",
            summary="pending semantic zebra card summary",
        ),
    )
    conn.commit()

    service = UnifiedRetrievalService(
        ":memory:",
        FakeRegistry([FakeSource("transcription")]),
    )
    monkeypatch.setattr(
        "api.services.retrieval.service.get_sync_connection",
        lambda *args, **kwargs: _ConnectionContext(conn),
    )
    monkeypatch.setattr(
        service,
        "_semantic_candidate_ids",
        lambda *args, **kwargs: (
            ["transcription:final-only"],
            "ready",
            {"transcription:final-only": 0.99},
        ),
    )

    result = service.search(
        RetrievalSearchRequest(query="zebra", mode="semantic", source_kinds=["transcription"])
    )
    assert result["results"][0]["document_id"] == "transcription:final-only"
    assert all(
        hit["document_id"] not in {"transcription:raw-semantic-1", "transcription:pending-semantic-1"}
        for hit in result["results"]
    )


def test_search_exact_and_hybrid_include_coverage_metadata(conn, monkeypatch):
    service = UnifiedRetrievalService(
        ":memory:",
        FakeRegistry([FakeSource("transcription", exact_ids=["transcription:one"])]),
    )
    monkeypatch.setattr(
        "api.services.retrieval.service.get_sync_connection",
        lambda *args, **kwargs: _ConnectionContext(conn),
    )
    monkeypatch.setattr(
        service,
        "_semantic_candidate_ids",
        lambda *args, **kwargs: ([], "not_requested", {}),
    )
    exact = service.search(
        RetrievalSearchRequest(query="budget", mode="exact", source_kinds=["transcription"], limit=1)
    )
    assert exact["coverage"]["exact_raw_fallback"] is True
    assert exact["coverage"]["semantic_corpus"] == "finalized_zettels_only"


def test_browse_switches_from_raw_to_zettel_after_stamping(conn, monkeypatch):
    from api.services.retrieval.registry import build_default_retrieval_registry
    from api.services.zettel import store as zettel_store
    from api.services.zettel.sources.base import ZettelDraft

    conn.execute(
        """
        INSERT INTO transcriptions (
            id, timestamp, transcription_text, model_name, status, zettel_id, audio_file_path
        ) VALUES (
            'browse-raw-1', '2026-07-29T18:00:00+00:00', 'browse raw phrase', 'm', 'completed', NULL, '/tmp/browse-raw-1.wav'
        )
        """
    )
    conn.commit()
    service = UnifiedRetrievalService(":memory:", build_default_retrieval_registry())
    monkeypatch.setattr(
        "api.services.retrieval.service.get_sync_connection",
        lambda *args, **kwargs: _ConnectionContext(conn),
    )

    before = service.browse(
        RetrievalBrowseRequest(
            source_kinds=["transcription"],
            start="2026-07-29T00:00:00+00:00",
            end="2026-07-29T23:59:59+00:00",
            limit=10,
        )
    )
    assert before["representation_counts"]["raw"] == 1
    assert before["representation_counts"]["zettel"] == 0
    assert before["events"][0]["representation"] == "raw"

    zettel_store.insert_card(
        conn,
        ZettelDraft(
            source_kind="transcription",
            source_id="browse-raw-1",
            event_type="transcription",
            occurred_at="2026-07-29T18:00:00+00:00",
            title="Browse raw phrase",
            summary="browse raw phrase",
        ),
    )
    zettel_store.stamp_source(
        conn,
        table="transcriptions",
        id_column="id",
        source_ids=["browse-raw-1"],
        zettel_id="transcription:browse-raw-1",
    )
    conn.commit()

    after = service.browse(
        RetrievalBrowseRequest(
            source_kinds=["transcription"],
            start="2026-07-29T00:00:00+00:00",
            end="2026-07-29T23:59:59+00:00",
            limit=10,
        )
    )
    assert after["representation_counts"]["raw"] == 0
    assert after["representation_counts"]["zettel"] == 1
    assert after["count"] == 1
    assert after["events"][0]["representation"] == "zettel"


def test_aggregate_moves_representation_bucket_without_changing_total(conn, monkeypatch):
    from api.services.retrieval.registry import build_default_retrieval_registry
    from api.services.zettel import store as zettel_store
    from api.services.zettel.sources.base import ZettelDraft

    conn.execute(
        """
        INSERT INTO transcriptions (
            id, timestamp, transcription_text, model_name, status, zettel_id, audio_file_path
        ) VALUES (
            'aggregate-raw-1', '2026-07-29T19:00:00+00:00', 'aggregate raw phrase', 'm', 'completed', NULL, '/tmp/aggregate-raw-1.wav'
        )
        """
    )
    conn.commit()
    service = UnifiedRetrievalService(":memory:", build_default_retrieval_registry())
    monkeypatch.setattr(
        "api.services.retrieval.service.get_sync_connection",
        lambda *args, **kwargs: _ConnectionContext(conn),
    )
    request = RetrievalAggregateRequest(
        group_by="source_kind",
        source_kinds=["transcription"],
        start="2026-07-29T00:00:00+00:00",
        end="2026-07-29T23:59:59+00:00",
    )
    before = service.aggregate(request)
    assert before["representation_counts"] == {"zettel": 0, "raw": 1}
    assert before["grouped_counts"]["transcription"] == 1

    zettel_store.insert_card(
        conn,
        ZettelDraft(
            source_kind="transcription",
            source_id="aggregate-raw-1",
            event_type="transcription",
            occurred_at="2026-07-29T19:00:00+00:00",
            title="Aggregate raw phrase",
            summary="aggregate raw phrase",
        ),
    )
    zettel_store.stamp_source(
        conn,
        table="transcriptions",
        id_column="id",
        source_ids=["aggregate-raw-1"],
        zettel_id="transcription:aggregate-raw-1",
    )
    conn.commit()

    after = service.aggregate(request)
    assert after["representation_counts"] == {"zettel": 1, "raw": 0}
    assert after["grouped_counts"]["transcription"] == 1
