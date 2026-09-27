"""Adapts settled zettel entries into the memory system's input contract."""

from __future__ import annotations

import logging
from typing import List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

DEFAULT_SIGNAL_LIMIT = 300

# Kinds worth reflecting on. Screen blocks are excluded: they are numerous,
# low-signal per row, and would swamp the evaluator's context.
SIGNAL_SOURCE_KINDS = (
    "agent_task", "transcription", "assistant_output", "scheduled_run",
)


def load_unswept_signals(
    *,
    limit: int = DEFAULT_SIGNAL_LIMIT,
) -> Tuple[List["ActivitySignal"], List[str]]:  # noqa: F821
    """Settled entries the memory evaluator has not consumed yet.

    Progress is the ``memory_swept_at`` stamp on each row, matching ``zettel_id``
    on source rows and ``narrative_state`` here: an indexed IS NULL scan rather
    than a moving cursor. This is what makes consumption independent of the order
    the narrative pass happens to settle entries in - a timestamp cursor would
    advance to the newest entry seen and permanently skip older entries settled
    on a later pass.

    Returns the signals plus the entry ids to stamp, which the caller passes to
    ``mark_swept`` only after evaluation actually succeeds. Ids are returned for
    every row read, including rows declined for having no usable text, so a page
    of unusable rows cannot stall the scan.
    """
    from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.infrastructure.connection import (
        get_sync_connection,
    )
    from api.dependencies import get_sqlite_knowledge_service
    from api.services.memory.memory_evaluator import ActivitySignal

    placeholders = ",".join("?" * len(SIGNAL_SOURCE_KINDS))
    params: List[object] = [*SIGNAL_SOURCE_KINDS, max(1, limit)]

    try:
        with get_sync_connection(get_sqlite_knowledge_service().db_path) as conn:
            rows = conn.execute(
                "SELECT id, source_kind, source_id, event_type, occurred_at, "
                "title, summary, narrative, outcome FROM zettel_entries "
                "WHERE narrative_state = 'final' AND memory_swept_at IS NULL "
                f"AND source_kind IN ({placeholders}) "
                "ORDER BY narrative_at ASC LIMIT ?",
                params,
            ).fetchall()
    except Exception:
        logger.exception("Failed to load zettel signals for memory evaluation")
        return [], []

    signals: List[ActivitySignal] = []
    entry_ids: List[str] = []
    for row in rows:
        entry_ids.append(row["id"])
        # The synthesized narrative is the point of the pass; fall back only
        # for older finalized entries that predate narrative generation.
        summary = row["narrative"] or row["summary"] or row["title"]
        if not summary:
            continue
        signals.append(
            ActivitySignal(
                source=row["source_kind"],
                occurred_at=row["occurred_at"],
                summary=summary,
                metadata={
                    "source_id": row["source_id"],
                    "event_type": row["event_type"],
                    "outcome": row["outcome"],
                },
            )
        )

    return signals, entry_ids


def mark_swept(entry_ids: Sequence[str], *, swept_at: Optional[str] = None) -> int:
    """Stamp entries as consumed by the memory evaluator.

    Called only after evaluation succeeded, so a failed or skipped run leaves the
    rows unstamped and the next sweep picks them up again.
    """
    if not entry_ids:
        return 0

    from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.infrastructure.connection import (
        get_sync_connection,
    )
    from api.dependencies import get_sqlite_knowledge_service
    from api.services.zettel.normalization import utc_now_iso

    stamp = swept_at or utc_now_iso()
    placeholders = ",".join("?" * len(entry_ids))
    try:
        with get_sync_connection(get_sqlite_knowledge_service().db_path) as conn:
            cursor = conn.execute(
                f"UPDATE zettel_entries SET memory_swept_at = ? "
                f"WHERE id IN ({placeholders}) AND memory_swept_at IS NULL",
                [stamp, *entry_ids],
            )
            conn.commit()
            return cursor.rowcount
    except Exception:
        logger.exception("Failed to stamp zettel entries as memory-swept")
        return 0
