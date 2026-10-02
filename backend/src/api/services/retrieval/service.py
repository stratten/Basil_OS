"""Single local history service: search, browse, aggregate, and detail."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np

from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.infrastructure.connection import (
    get_sync_connection,
)
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.retrieval.repository import (
    RetrievalRepository,
)
from api.services.zettel import store

from .contracts import (
    RetrievalAggregateRequest,
    RetrievalBrowseRequest,
    RetrievalDetailRequest,
    RetrievalHit,
    RetrievalSearchRequest,
)
from .browse_paging import (
    build_page,
    clamp_page_limit,
    decode_cursor,
    resolve_output_budget,
    sort_newest_first,
)
from .indexer import DEFAULT_EMBEDDING_MODEL
from .numpy_vector_sidecar import NumpyVectorSidecar

RRF_K = 60
EXACT_RRF_WEIGHT = 1.0
SEMANTIC_RRF_WEIGHT = 1.0
CANDIDATE_MULTIPLIER = 3


def _parse_time(value: str | None, default: datetime) -> str:
    from api.services.agent_processing.tools.internal_basil_tools.unified_history_tool import _parse_time as legacy_parse
    return legacy_parse(value, default)


def _local_day(value: Any) -> str:
    """Local calendar day of a stored timestamp; offset-less values are UTC, as SQLite assumes."""
    text = str(value or "")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text[:10] or "none"
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone().date().isoformat()


def _fuse_ranked_candidates(
    exact_ids: list[str],
    semantic_ids: list[str],
    limit: int,
) -> list[tuple[str, float, str]]:
    scores: dict[str, float] = {}
    reasons: dict[str, set[str]] = {}

    for rank, document_id in enumerate(exact_ids, start=1):
        scores[document_id] = scores.get(document_id, 0.0) + EXACT_RRF_WEIGHT / (RRF_K + rank)
        reasons.setdefault(document_id, set()).add("exact")

    for rank, document_id in enumerate(semantic_ids, start=1):
        scores[document_id] = scores.get(document_id, 0.0) + SEMANTIC_RRF_WEIGHT / (RRF_K + rank)
        reasons.setdefault(document_id, set()).add("semantic")

    fused: list[tuple[str, float, str]] = []
    for document_id, score in sorted(scores.items(), key=lambda item: (-item[1], item[0])):
        source_reasons = reasons.get(document_id, set())
        if source_reasons == {"exact", "semantic"}:
            score_kind = "hybrid_rrf:exact+semantic"
        elif "exact" in source_reasons:
            score_kind = "hybrid_rrf:exact"
        else:
            score_kind = "hybrid_rrf:semantic"
        fused.append((document_id, score, score_kind))
    return fused[:limit]


def _raw_event(row: Any) -> dict[str, Any]:
    return {
        "source_kind": row["source_kind"],
        "source_id": row["source_id"],
        "event_type": row["event_type"],
        "occurred_at": row["occurred_at"],
        "ended_at": row["ended_at"],
        "title": row["title"],
        "summary": row["summary"],
        "raw_summary": row["summary"],
        "narrative": None,
        "narrative_state": "raw",
        "is_open": None,
        "open_note": None,
        "outcome": row["outcome"],
        "source_status": row["source_status"],
        "payload": {},
        "representation": "raw",
    }


def _raw_filters(
    start: str | None, end: str | None, source_kinds: list[str] | None, outcome: str | None
) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if start:
        clauses.append("occurred_at >= ?")
        params.append(start)
    if end:
        clauses.append("occurred_at <= ?")
        params.append(end)
    if source_kinds:
        clauses.append(f"source_kind IN ({','.join('?' * len(source_kinds))})")
        params.extend(source_kinds)
    if outcome:
        clauses.append("outcome = ?")
        params.append(outcome)
    return (f"WHERE {' AND '.join(clauses)}" if clauses else "", params)


class UnifiedRetrievalService:
    def __init__(self, db_path: str, registry, embedding_model: str = DEFAULT_EMBEDDING_MODEL) -> None:
        self.db_path = db_path
        self.registry = registry
        self.embedding_model = embedding_model

    def catalog(self) -> dict[str, Any]:
        return {
            "success": True,
            "action": "catalog",
            "sources": self.registry.describe_sources(),
        }

    def search(self, request: RetrievalSearchRequest) -> dict[str, Any]:
        if not request.query.strip():
            raise ValueError("query is required for search")
        sources = self.registry.sources(request.source_kinds)
        source_kinds = [source.source_kind for source in sources]
        now = datetime.now(timezone.utc)
        start = _parse_time(request.start, now - timedelta(days=1)) if request.start else None
        end = _parse_time(request.end, now) if request.end else None
        limit = max(1, min(request.limit, 50))
        candidate_limit = limit * CANDIDATE_MULTIPLIER
        exact_ranked: list[str] = []
        exact_scores: dict[str, tuple[float, str]] = {}
        semantic_ranked: list[str] = []
        semantic_scores: dict[str, float] = {}
        semantic_status = "not_requested"

        if request.mode in {"exact", "hybrid"}:
            with get_sync_connection(self.db_path) as conn:
                for source in sources:
                    for candidate in source.search_exact(
                        conn, request.query, start, end, candidate_limit
                    ):
                        if candidate.document_id not in exact_ranked:
                            exact_ranked.append(candidate.document_id)
                            exact_scores[candidate.document_id] = (
                                candidate.score,
                                candidate.score_kind,
                            )

        if request.mode in {"semantic", "hybrid"}:
            semantic_ranked, semantic_status, semantic_scores = self._semantic_candidate_ids(
                request.query, source_kinds, start, end, candidate_limit
            )

        hits: list[RetrievalHit] = []
        truncated = False
        with get_sync_connection(self.db_path) as conn:
            if request.mode == "exact":
                truncated = len(exact_ranked) > limit
                for document_id in exact_ranked[:limit]:
                    score, score_kind = exact_scores.get(document_id, (0.0, "exact_fts"))
                    hit = self._hydrate_hit(conn, document_id, score=score, score_kind=score_kind)
                    if hit:
                        hits.append(hit)
            elif request.mode == "semantic":
                truncated = len(semantic_ranked) > limit
                for document_id in semantic_ranked[:limit]:
                    hit = self._hydrate_hit(
                        conn,
                        document_id,
                        score=semantic_scores.get(document_id, 0.0),
                        score_kind="semantic_cosine",
                    )
                    if hit:
                        hits.append(hit)
            else:
                truncated = len(exact_ranked) > limit or len(semantic_ranked) > limit
                fused = _fuse_ranked_candidates(exact_ranked, semantic_ranked, limit)
                for document_id, score, score_kind in fused:
                    hit = self._hydrate_hit(conn, document_id, score=score, score_kind=score_kind)
                    if hit:
                        hits.append(hit)

        return {
            "success": True,
            "action": "search",
            "query": request.query,
            "mode": request.mode,
            "semantic_status": semantic_status,
            "coverage": {
                "exact_raw_fallback": request.mode in {"exact", "hybrid"},
                "semantic_corpus": "finalized_zettels_only",
            },
            "count": len(hits),
            "truncated": truncated,
            "results": [hit.__dict__ for hit in hits],
        }

    def browse(self, request: RetrievalBrowseRequest) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        start = _parse_time(request.start, now - timedelta(days=1))
        end = _parse_time(request.end, now)
        kinds = request.source_kinds
        page_limit = clamp_page_limit(request.limit)
        fetch_limit = page_limit + 1
        try:
            before = decode_cursor(request.cursor) if request.cursor else None
        except ValueError as exc:
            return {"success": False, "action": "browse", "error": str(exc)}
        with get_sync_connection(self.db_path) as conn:
            zettel_events = store.query_entries(
                conn,
                start=start,
                end=end,
                source_kinds=kinds,
                outcome=request.outcome,
                limit=fetch_limit,
                before=before,
            )
            for event in zettel_events:
                event["representation"] = "zettel"
            where, params = _raw_filters(start, end, kinds, request.outcome)
            raw_total = conn.execute(
                f"SELECT COUNT(*) FROM zettel_raw_search_fts {where}",
                params,
            ).fetchone()[0]
            page_where, page_params = store.with_keyset_before(where, params, before)
            raw_rows = conn.execute(
                f"SELECT * FROM zettel_raw_search_fts {page_where} "
                f"{store.NEWEST_FIRST_ORDER} LIMIT ?",
                [*page_params, fetch_limit],
            ).fetchall()
            raw_events = [_raw_event(row) for row in raw_rows]
            zettel_total = sum(
                store.count_entries_by(
                    conn,
                    dimension="source_kind",
                    start=start,
                    end=end,
                    source_kinds=kinds,
                    outcome=request.outcome,
                ).values()
            )
        candidates = sort_newest_first(zettel_events + raw_events)[:fetch_limit]
        page = build_page(
            candidates,
            page_limit=page_limit,
            max_output_chars=resolve_output_budget(request.max_output_chars),
            view=request.view,
        )
        next_cursor = page["next_cursor"]
        return {
            "success": True,
            "action": "browse",
            "count": len(page["events"]),
            "range": {"start": start, "end": end},
            "events": page["events"],
            "representation_counts": {"zettel": zettel_total, "raw": raw_total},
            "total_in_range": zettel_total + raw_total,
            "truncated": next_cursor is not None,
            "next_cursor": next_cursor,
            "page_limit": page_limit,
            "view": request.view,
            "budget_trimmed": page["budget_trimmed"],
        }

    def aggregate(self, request: RetrievalAggregateRequest) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        start = _parse_time(request.start, now - timedelta(days=1))
        end = _parse_time(request.end, now)
        with get_sync_connection(self.db_path) as conn:
            zettel_counts = store.count_entries_by(
                conn,
                dimension=request.group_by,
                start=start,
                end=end,
                source_kinds=request.source_kinds,
                outcome=request.outcome,
            )
            where, params = _raw_filters(start, end, request.source_kinds, request.outcome)
            raw_rows = conn.execute(
                f"SELECT source_kind, occurred_at, outcome FROM zettel_raw_search_fts {where}",
                params,
            ).fetchall()
            raw_counts: dict[str, int] = {}
            for row in raw_rows:
                if request.group_by == "source_kind":
                    bucket = str(row["source_kind"])
                elif request.group_by == "day":
                    bucket = _local_day(row["occurred_at"])
                else:
                    bucket = str(row["outcome"] or "none")
                raw_counts[bucket] = raw_counts.get(bucket, 0) + 1
            grouped_counts = dict(zettel_counts)
            for bucket, count in raw_counts.items():
                grouped_counts[bucket] = grouped_counts.get(bucket, 0) + count
            zettel_total = sum(
                store.count_entries_by(
                    conn,
                    dimension="source_kind",
                    start=start,
                    end=end,
                    source_kinds=request.source_kinds,
                    outcome=request.outcome,
                ).values()
            )
        return {
            "success": True,
            "action": "aggregate",
            "range": {"start": start, "end": end},
            "group_by": request.group_by,
            "grouped_counts": grouped_counts,
            "grouped_counts_cover": "entire range, not just returned events",
            "representation_counts": {
                "zettel": zettel_total,
                "raw": len(raw_rows),
            },
        }

    def detail(self, request: RetrievalDetailRequest) -> dict[str, Any]:
        with get_sync_connection(self.db_path) as conn:
            detail = self.registry.require(request.source_kind).detail(conn, request.source_id)
        return {"success": detail is not None, "source_kind": request.source_kind,
                "source_id": request.source_id, "detail": detail}

    def _hydrate_hit(
        self, conn, document_id: str, *, score: float, score_kind: str
    ) -> RetrievalHit | None:
        kind, source_id = document_id.split(":", 1)
        document = self.registry.require(kind).hydrate(conn, source_id)
        if not document:
            return None
        return RetrievalHit(
            document_id=document.document_id,
            source_kind=kind,
            source_id=source_id,
            occurred_at=document.occurred_at,
            title=document.title,
            excerpt=document.search_text[:800],
            score=score,
            score_kind=score_kind,
            metadata=document.metadata,
        )

    def _semantic_candidate_ids(
        self,
        query: str,
        source_kinds: list[str],
        start: str | None,
        end: str | None,
        candidate_limit: int,
    ) -> tuple[list[str], str, dict[str, float]]:
        from api.core.models.embeddings.embedding_model_manager import get_global_embedding_manager

        if not source_kinds:
            return [], "not_built", {}

        with get_sync_connection(self.db_path) as conn:
            repository = RetrievalRepository(self.db_path)
            state = repository.state(conn, self.embedding_model)
            if not state or not state["generation_id"]:
                return [], "not_built", {}
            document_count = int(state["document_count"] or 0)
            if document_count <= 0:
                return [], "not_built", {}

            clauses = [
                "embedding_model = ?",
                "is_active = 1",
                f"source_kind IN ({','.join('?' * len(source_kinds))})",
            ]
            params: list[Any] = [self.embedding_model, *source_kinds]
            if start:
                clauses.append("occurred_at >= ?")
                params.append(start)
            if end:
                clauses.append("occurred_at <= ?")
                params.append(end)
            rows = conn.execute(
                f"""
                SELECT document_id, vector_id
                FROM retrieval_documents
                WHERE {' AND '.join(clauses)}
                ORDER BY vector_id ASC
                """,
                params,
            ).fetchall()
            if not rows:
                return [], "ready", {}

            vector_ids = np.asarray(
                [int(row["vector_id"]) for row in rows],
                dtype=np.intp,
            )
            document_ids = [str(row["document_id"]) for row in rows]
            vectors = NumpyVectorSidecar(self.db_path, self.embedding_model).load(
                state["generation_id"],
                int(state["embedding_dimension"]),
                document_count,
            )
            if vectors is None:
                return [], "stale", {}
            if (
                vector_ids.size == 0
                or vector_ids.min() < 0
                or vector_ids.max() >= vectors.shape[0]
            ):
                return [], "stale", {}

            manager = get_global_embedding_manager()
            manager.begin_use(self.embedding_model)
            try:
                vector = manager.get(self.embedding_model).encode(
                    [query], convert_to_numpy=True, normalize_embeddings=True
                )
            finally:
                manager.end_use(self.embedding_model)

            query_vector = np.asarray(vector[0], dtype=np.float32)
            eligible_scores = np.asarray(
                vectors[vector_ids] @ query_vector,
                dtype=np.float32,
            )
            top_count = min(candidate_limit, len(document_ids))
            if top_count == 0:
                return [], "ready", {}
            top_positions = np.argpartition(eligible_scores, -top_count)[-top_count:]
            top_positions = top_positions[
                np.argsort(eligible_scores[top_positions])[::-1]
            ]
            ranked = [document_ids[int(position)] for position in top_positions]
            score_map = {
                document_ids[int(position)]: float(eligible_scores[int(position)])
                for position in top_positions
            }
            return ranked, "ready", score_map
