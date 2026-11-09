"""Discard memory entries that factually have nothing to summarize.

An entry whose source carries no content, such as a transcription with an empty transcript, can never be summarized: the model has nothing to read, so it replies with no narrative, the entry burns its retries, and it ends up in "Couldn't summarize" forever.
These entries are discarded instead.
Discarding removes only the derived memory entry.
The source row keeps the stamp that marks it as already carded, so the carding pass does not create the entry again.

The rule is deliberately narrow, so a summarizable entry is never lost.
An entry is discarded only when all of these hold:

* it is not final, so a finished summary is never deleted;
* its own summary is blank;
* every value the source gathers for the model is empty;
* its source status is terminal or absent, so a transcription that is still being produced is left alone.
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Any, Dict, List, Mapping, Optional

from api.services.zettel.sources.base import ZettelSource

logger = logging.getLogger(__name__)

# Statuses after which a source will not gain content. A missing status belongs to sources that have no lifecycle, such as meetings and screen blocks.
DISCARDABLE_SOURCE_STATUSES = frozenset({"", "completed", "failed", "canceled", "skipped", "missed"})
CONTEXT_CHUNK_SIZE = 500


def value_has_content(value: Any) -> bool:
    """True when a gathered value, however nested, holds any non-blank text or any number."""
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, Mapping):
        return any(value_has_content(item) for item in value.values())
    if isinstance(value, (list, tuple, set)):
        return any(value_has_content(item) for item in value)
    return True


def is_unsummarizable(*, summary: Optional[str], source_status: Optional[str], context: Optional[Mapping[str, Any]]) -> bool:
    """The discard rule for one non-final entry."""
    if (summary or "").strip():
        return False
    if (source_status or "") not in DISCARDABLE_SOURCE_STATUSES:
        return False
    return not value_has_content(context or {})


def discard_unsummarizable(conn: sqlite3.Connection, sources: Mapping[str, ZettelSource]) -> int:
    """Delete every non-final entry that has nothing to summarize, and return how many were deleted.

    Reads context with each source's own ``gather_context``, so "nothing to read" means exactly what the summarizer would have seen.
    A source that fails to gather context is skipped for this call, never treated as empty.
    """
    rows = conn.execute(
        "SELECT id, source_kind, source_id, summary, source_status FROM zettel_entries "
        "WHERE narrative_state != 'final' AND COALESCE(TRIM(summary), '') = ''"
    ).fetchall()
    by_kind: Dict[str, List[sqlite3.Row]] = {}
    for row in rows:
        by_kind.setdefault(row["source_kind"], []).append(row)

    doomed: List[str] = []
    for kind, kind_rows in by_kind.items():
        source = sources.get(kind)
        if source is None:
            continue
        for start in range(0, len(kind_rows), CONTEXT_CHUNK_SIZE):
            chunk = kind_rows[start:start + CONTEXT_CHUNK_SIZE]
            try:
                context = source.gather_context(conn, [row["source_id"] for row in chunk])
            except Exception:
                logger.exception("Could not check %s entries for unsummarizable content", kind)
                continue
            doomed.extend(
                row["id"]
                for row in chunk
                if is_unsummarizable(
                    summary=row["summary"],
                    source_status=row["source_status"],
                    context=context.get(str(row["source_id"])),
                )
            )

    # The retrieval table is created by the retrieval runtime, so a database that has not run it yet has nothing to clean there.
    has_retrieval_documents = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'retrieval_documents'"
    ).fetchone() is not None
    for start in range(0, len(doomed), CONTEXT_CHUNK_SIZE):
        chunk_ids = doomed[start:start + CONTEXT_CHUNK_SIZE]
        placeholders = ",".join("?" * len(chunk_ids))
        if has_retrieval_documents:
            conn.execute(f"DELETE FROM retrieval_documents WHERE document_id IN ({placeholders})", chunk_ids)
        conn.execute(
            f"DELETE FROM zettel_entries WHERE id IN ({placeholders}) AND narrative_state != 'final'",
            chunk_ids,
        )
    if doomed:
        logger.info("Discarded %s memory entries with nothing to summarize", len(doomed))
    return len(doomed)
