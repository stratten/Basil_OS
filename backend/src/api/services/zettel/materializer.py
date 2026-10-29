"""The carding pass: create thin zettels for un-carded source rows.

Deterministic and model-free. State lives on the row (zettel_id), so there is
no cursor to advance and re-running is a safe no-op: find_uncarded returns
nothing once every row is stamped.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set

from api.services.zettel import store
from api.services.zettel.sources.base import ZettelSource, get_zettel_sources

logger = logging.getLogger(__name__)

DEFAULT_LIMIT_PER_SOURCE = 500


@dataclass
class CardingResult:
    carded: int = 0
    existing: int = 0
    stamped: int = 0
    errors: List[str] = field(default_factory=list)


def since_iso_for_days(history_days: int) -> Optional[str]:
    """Lower time bound for carding, or None when history_days is 0 (all)."""
    if history_days and history_days > 0:
        floor = datetime.now(timezone.utc) - timedelta(days=history_days)
        return floor.isoformat()
    return None


class ZettelMaterializer:
    """Cards un-carded source rows into the stream. Safe to run concurrently."""

    def __init__(self, sources: Optional[List[ZettelSource]] = None) -> None:
        self._sources = sources if sources is not None else get_zettel_sources()

    def run_pass(
        self,
        *,
        limit_per_source: int = DEFAULT_LIMIT_PER_SOURCE,
        since_iso: Optional[str] = None,
        enabled_kinds: Optional[Set[str]] = None,
    ) -> CardingResult:
        result = CardingResult()
        with self._connection() as conn:
            from api.services.zettel.conversation_turn_reconciler import (
                reconcile_stale_conversation_turns,
            )

            reconciliation = reconcile_stale_conversation_turns(conn)
            if reconciliation.closed_turns or reconciliation.failed_agent_tasks:
                logger.info(
                    "Conversation turn reconciliation closed %s turn(s) and failed %s stale task(s)",
                    reconciliation.closed_turns,
                    reconciliation.failed_agent_tasks,
                )
            for source in self._sources:
                if enabled_kinds is not None and source.source_kind not in enabled_kinds:
                    continue
                self._card_source(conn, source, limit_per_source, since_iso, result)
            conn.commit()
        return result

    def scope_counts(
        self,
        *,
        since_iso: Optional[str] = None,
        enabled_kinds: Optional[Set[str]] = None,
    ) -> Dict[str, int]:
        """Un-carded rows still in scope, per source kind. Read-only."""
        counts: Dict[str, int] = {}
        with self._connection() as conn:
            for source in self._sources:
                if enabled_kinds is not None and source.source_kind not in enabled_kinds:
                    continue
                try:
                    counts[source.source_kind] = source.count_uncarded(
                        conn, since_iso=since_iso
                    )
                except Exception:
                    logger.exception(
                        "Zettel scope count failed for %s", source.source_kind
                    )
                    counts[source.source_kind] = 0
        return counts

    def stats(
        self,
        *,
        since_iso: Optional[str] = None,
        enabled_kinds: Optional[Set[str]] = None,
        narrative_max_attempts: int = 3,
    ) -> Dict[str, Any]:
        """Everything the settings UI needs in one read.

        Stream counts (collected, and the narrative states within it) are NOT
        window-scoped, because nothing that acts on the stream is: the narrative
        pass drains every pending entry regardless of age, and the memory sweep
        consumes every settled one. Scoping these to history_days reported "0
        summarized" while 197 entries were in fact summarized, simply because
        their events predated the window.

        "Waiting to be collected" IS window-scoped, because that is a real
        property of carding - it only ever picks up source rows inside the
        window, which the UI already explains.

        ``awaiting_summary`` is the runnable subset of pending entries, using
        the same attempt predicate as the narrative pass. Pending entries at or
        above that threshold are reported separately as ``awaiting_retry`` so
        they remain visible without inflating the next-run count.
        """
        kinds = sorted(enabled_kinds) if enabled_kinds else None
        with self._connection() as conn:
            by_state = store.count_entries_by(conn, dimension="narrative_state")
            awaiting_summary, awaiting_retry = store.count_pending_by_attempt_eligibility(
                conn,
                max_attempts=narrative_max_attempts,
            )
            carded_by_source = store.count_entries_by(
                conn, dimension="source_kind", source_kinds=kinds
            )
        uncarded_by_source = self.scope_counts(
            since_iso=since_iso, enabled_kinds=enabled_kinds
        )
        source_kinds = sorted(set(carded_by_source) | set(uncarded_by_source))
        return {
            "collected": sum(by_state.values()),
            "summarized": by_state.get("final", 0),
            "awaiting_summary": awaiting_summary,
            "awaiting_retry": awaiting_retry,
            "failed": by_state.get("failed", 0),
            "awaiting_collection": sum(uncarded_by_source.values()),
            "by_source": [
                {
                    "kind": kind,
                    "collected": carded_by_source.get(kind, 0),
                    "awaiting_collection": uncarded_by_source.get(kind, 0),
                }
                for kind in source_kinds
            ],
        }

    def _connection(self):
        from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.infrastructure.connection import (
            get_sync_connection,
        )
        from api.dependencies import get_sqlite_knowledge_service

        return get_sync_connection(get_sqlite_knowledge_service().db_path)

    def _card_source(self, conn, source, limit, since_iso, result) -> None:
        # Drain the source in *limit*-sized chunks rather than capping at one
        # chunk: stamping sets zettel_id, so each pass shrinks the un-carded pool
        # and find_uncarded returns nothing once the backlog (within the window)
        # is exhausted. limit is a chunk size, not a ceiling on the run.
        while True:
            try:
                drafts = source.find_uncarded(conn, since_iso=since_iso, limit=limit)
            except Exception as exc:
                logger.exception("Zettel carding failed for %s", source.source_kind)
                result.errors.append(f"{source.source_kind}: {exc}")
                return

            if not drafts:
                return

            stamped_this_round = 0
            for draft in drafts:
                try:
                    if store.insert_card(conn, draft):
                        result.carded += 1
                    else:
                        result.existing += 1
                    # Idempotent: the stamp only touches rows still NULL, so it is a
                    # no-op for an already-carded row and repairs any that slipped.
                    source.stamp(conn, draft, draft.entry_id)
                    result.stamped += 1
                    stamped_this_round += 1
                except Exception as exc:
                    logger.exception(
                        "Zettel carding failed for %s row %s", source.source_kind, draft.source_id
                    )
                    result.errors.append(f"{source.source_kind}:{draft.source_id}: {exc}")

            # No-progress guard: if a whole chunk was returned but nothing got
            # stamped (e.g. every draft in it errored), stop rather than re-read
            # the same rows forever.
            if stamped_this_round == 0:
                return


_materializer_singleton: Optional[ZettelMaterializer] = None


def get_zettel_materializer() -> ZettelMaterializer:
    global _materializer_singleton
    if _materializer_singleton is None:
        _materializer_singleton = ZettelMaterializer()
    return _materializer_singleton
