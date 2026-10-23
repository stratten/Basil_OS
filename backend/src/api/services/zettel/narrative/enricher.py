"""The finalizing pass: give every non-final zettel a narrative swing.

Source-agnostic. Reads the pending queue and gathers each source's context in
one synchronous phase, releases the connection across the model calls (which
are async and can be slow), then writes results back in a final phase. Holding
a SQLite connection open across awaits would serialize the whole app on it.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from api.services.zettel import store
from api.services.zettel.narrative.narrative_processing_run_policy import (
    NarrativeProcessingRunPolicy,
    SEQUENTIAL_NARRATIVE_CONCURRENCY,
)
from api.services.zettel.narrative.synthesizer import SynthesisError, synthesize
from api.services.zettel.normalization import utc_now_iso
from api.services.zettel.sources.base import ZettelSource, sources_by_kind

logger = logging.getLogger(__name__)

# A pass drains the whole backlog; this is the chunk it reads and summarizes per
# iteration, not a cap on the run. The run ends when nothing pending remains.
DEFAULT_BATCH_SIZE = 50
DEFAULT_MAX_ATTEMPTS = 3


@dataclass
class EnrichResult:
    finalized: int = 0
    still_open: int = 0
    failed: int = 0
    errors: List[str] = field(default_factory=list)


@dataclass
class NarrativeProgress:
    """Live state of a finalizing run, read by the progress endpoint.

    total is the pending count captured at run start (the drain target);
    processed increments as each entry resolves, so remaining and ETA can be
    derived without re-scanning the table on every poll.
    """
    active: bool = False
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    total: int = 0
    processed: int = 0
    finalized: int = 0
    still_open: int = 0
    failed: int = 0
    last_error: Optional[str] = None
    cancel_requested: bool = False
    analysis_concurrency: int = SEQUENTIAL_NARRATIVE_CONCURRENCY
    processing_strategy: str = "sequential"


@dataclass
class _WorkItem:
    entry: Dict[str, Any]
    context: Dict[str, Any]


class ZettelEnricher:
    def __init__(self, sources: Optional[Dict[str, ZettelSource]] = None) -> None:
        self._sources = sources if sources is not None else sources_by_kind()
        self._progress = NarrativeProgress()
        self._cancel_requested = False
        self._model_stage_semaphore = asyncio.Semaphore(1)

    def get_progress(self) -> NarrativeProgress:
        return self._progress

    def request_cancel(self) -> bool:
        """Ask an in-flight pass to stop after currently admitted entries resolve.

        Cooperative on purpose: canceling asyncio tasks mid-generation would abandon model calls and leave their entries' attempt counts unbumped, so workers check this flag before admitting queued entries. Returns whether a pass was actually running to cancel.
        """
        if not self._progress.active:
            return False
        self._cancel_requested = True
        self._progress.cancel_requested = True
        return True

    async def run_pass(
        self,
        *,
        batch_size: int = DEFAULT_BATCH_SIZE,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        model_id: Optional[str] = None,
        max_records: Optional[int] = None,
        run_policy: Optional[NarrativeProcessingRunPolicy] = None,
    ) -> EnrichResult:
        """Drain the pending backlog, one chunk of *batch_size* at a time.

        Runs to completion rather than to a fixed count: after each entry is
        summarized (or fails) its narrative_at moves to at/after run_start, so
        the next chunk excludes it. The loop stops once no untouched pending
        entry remains, and it is bounded by the attempt cap either way.

        *max_records* caps how many entries one run resolves; None or 0 means no
        cap. It bounds the run, not the queue - entries not reached simply stay
        pending for the next pass - which is what makes it safe to evaluate a
        prompt or model change against a subset instead of the whole backlog. It
        is also the ceiling on what a still-open entry can cost, because an open
        entry no longer consumes retry budget and would otherwise be revisited on
        every future pass.

        *run_policy*, when supplied, snapshots the selected model and bounded concurrency for the entire run. Without one, callers retain the legacy sequential behavior using *model_id*.
        """
        effective_model_id = run_policy.model_id if run_policy is not None else model_id
        effective_concurrency = (
            run_policy.analysis_concurrency
            if run_policy is not None
            else SEQUENTIAL_NARRATIVE_CONCURRENCY
        )
        effective_strategy = run_policy.processing_strategy if run_policy is not None else "sequential"
        result = EnrichResult()
        run_start = utc_now_iso()
        self._cancel_requested = False
        pending_total = self._count_pending(max_attempts=max_attempts)
        limit = max_records if max_records and max_records > 0 else None
        self._progress = NarrativeProgress(
            active=True,
            started_at=run_start,
            # The drain target for *this* run, so remaining and the ETA describe
            # work the run will actually do rather than a backlog it was never
            # going to reach.
            total=min(pending_total, limit) if limit else pending_total,
            analysis_concurrency=effective_concurrency,
            processing_strategy=effective_strategy,
        )
        try:
            while True:
                if self._cancel_requested:
                    logger.info(
                        "Zettel narrative pass canceled after %s entries",
                        self._progress.processed,
                    )
                    break
                if limit is not None and self._progress.processed >= limit:
                    logger.info("Zettel narrative pass reached its %s-record limit", limit)
                    break
                work = self._collect(
                    batch_size=self._chunk_limit(batch_size, limit),
                    max_attempts=max_attempts,
                    touched_before=run_start,
                )
                if not work:
                    break
                await self._run_chunk(
                    work,
                    model_id=effective_model_id,
                    max_attempts=max_attempts,
                    result=result,
                    limit=limit,
                    concurrency=effective_concurrency,
                )
        finally:
            self._progress.active = False
            self._progress.finished_at = utc_now_iso()
        return result

    async def _run_chunk(
        self,
        work: List[_WorkItem],
        *,
        model_id: Optional[str],
        max_attempts: int,
        result: EnrichResult,
        limit: Optional[int],
        concurrency: int,
    ) -> None:
        """Resolve one fetched chunk with a bounded number of in-flight entries.

        The caller fetches each chunk exactly once before workers are admitted. This is essential because load_pending does not claim rows, so concurrent fetches could schedule the same pending entry more than once.
        """
        semaphore = asyncio.Semaphore(max(1, concurrency))

        async def process_item(item: _WorkItem) -> None:
            async with semaphore:
                if self._cancel_requested:
                    return
                if limit is not None and self._progress.processed >= limit:
                    return
                entry_id = item.entry["entry_id"]
                try:
                    synthesis_kwargs: Dict[str, Any] = {"model_id": model_id}
                    if concurrency > SEQUENTIAL_NARRATIVE_CONCURRENCY:
                        synthesis_kwargs["model_stage_semaphore"] = self._model_stage_semaphore
                    synthesis = await synthesize(item.entry, item.context, **synthesis_kwargs)
                except SynthesisError as exc:
                    self._record_failure(entry_id, str(exc), max_attempts, result)
                    return
                except Exception as exc:
                    logger.exception("Narrative synthesis crashed for %s", entry_id)
                    self._record_failure(entry_id, str(exc), max_attempts, result)
                    return
                self._record_success(entry_id, synthesis, result)

        outcomes = await asyncio.gather(
            *(process_item(item) for item in work),
            return_exceptions=True,
        )
        for outcome in outcomes:
            if isinstance(outcome, BaseException):
                # Do not mark the run inactive while sibling generations are still running. gather(return_exceptions=True) settles every admitted worker before the first infrastructure error escapes.
                raise outcome

    def _count_pending(self, *, max_attempts: int) -> int:
        with self._connection() as conn:
            return store.count_pending(conn, max_attempts=max_attempts)

    def _chunk_limit(self, batch_size: int, limit: Optional[int]) -> int:
        """Never read a larger chunk than the run still has allowance for.

        _collect calls gather_context for everything it reads, which for screen
        blocks queries every member capture. Reading a full chunk when only two
        records remain in the allowance would pay that cost for entries this run
        will not touch.
        """
        if limit is None:
            return batch_size
        return max(1, min(batch_size, limit - self._progress.processed))

    def _collect(
        self, *, batch_size: int, max_attempts: int, touched_before: Optional[str] = None
    ) -> List[_WorkItem]:
        with self._connection() as conn:
            pending = store.load_pending(
                conn,
                limit=batch_size,
                max_attempts=max_attempts,
                touched_before=touched_before,
            )
            if not pending:
                return []
            ids_by_kind: Dict[str, List[str]] = {}
            for entry in pending:
                ids_by_kind.setdefault(entry.source_kind, []).append(entry.source_id)

            context_by_kind: Dict[str, Dict[str, Dict[str, Any]]] = {}
            for kind, ids in ids_by_kind.items():
                source = self._sources.get(kind)
                if source is None:
                    continue
                try:
                    context_by_kind[kind] = source.gather_context(conn, ids)
                except Exception:
                    logger.exception("Context gathering failed for %s", kind)
                    context_by_kind[kind] = {}

            return [
                _WorkItem(
                    entry={
                        "entry_id": entry.entry_id,
                        "source_kind": entry.source_kind,
                        "source_id": entry.source_id,
                        "event_type": entry.event_type,
                        "occurred_at": entry.occurred_at,
                        "title": entry.title,
                        "summary": entry.summary,
                        "outcome": entry.outcome,
                        "source_status": entry.source_status,
                        "payload": entry.payload,
                    },
                    context=context_by_kind.get(entry.source_kind, {}).get(entry.source_id, {}),
                )
                for entry in pending
            ]

    def _record_success(self, entry_id, synthesis, result: EnrichResult) -> None:
        with self._connection() as conn:
            store.write_narrative(
                conn,
                entry_id,
                narrative=synthesis.narrative,
                model=synthesis.model_name,
            )
            conn.commit()
        self._progress.processed += 1
        result.finalized += 1
        self._progress.finalized += 1

    def _record_failure(self, entry_id, error, max_attempts, result: EnrichResult) -> None:
        with self._connection() as conn:
            store.record_failure(conn, entry_id, error=error, max_attempts=max_attempts)
            conn.commit()
        result.failed += 1
        result.errors.append(f"{entry_id}: {error}")
        self._progress.processed += 1
        self._progress.failed += 1
        self._progress.last_error = error

    def _connection(self):
        from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.infrastructure.connection import (
            get_sync_connection,
        )
        from api.dependencies import get_sqlite_knowledge_service

        return get_sync_connection(get_sqlite_knowledge_service().db_path)


_enricher_singleton: Optional[ZettelEnricher] = None


def get_zettel_enricher() -> ZettelEnricher:
    global _enricher_singleton
    if _enricher_singleton is None:
        _enricher_singleton = ZettelEnricher()
    return _enricher_singleton
