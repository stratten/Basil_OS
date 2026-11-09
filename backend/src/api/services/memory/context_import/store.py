"""Writes imported items into the zettel stream and removes whole import batches again.

Imported entries are written already final, with their text as the narrative, so the model summarizing pass never spends tokens on them and the existing full-text index (maintained by triggers on zettel_entries) makes them findable by the retrieval search. Their source_id is a hash of the content and date, so INSERT OR IGNORE makes re-importing the same file add nothing.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Dict, List, Sequence

from api.services.zettel.normalization import (
    SUMMARY_MAX_CHARS,
    TITLE_MAX_CHARS,
    content_digest,
    truncate,
    utc_now_iso,
)

from .models import EVENT_TYPE, SOURCE_KIND, ImportItem


@dataclass(frozen=True)
class BatchSummary:
    batch_id: str
    imported_at: str
    label: str
    entry_count: int


def write_items(
    conn: sqlite3.Connection,
    *,
    batch_id: str,
    label: str,
    items: Sequence[ImportItem],
) -> Dict[str, int]:
    """Insert *items* as final zettel entries. Returns how many were added and how many already existed."""
    now = utc_now_iso()
    added = 0
    for item in items:
        occurred_at = item.occurred_at or now
        title = truncate(item.title, TITLE_MAX_CHARS) or "Imported note"
        summary = truncate(item.text, SUMMARY_MAX_CHARS)
        payload = json.dumps(
            {"import_batch_id": batch_id, "import_label": label, "category": item.category, "section": item.section, "dated": item.occurred_at is not None},
            ensure_ascii=False,
        )
        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO zettel_entries (
                id, source_kind, source_id, event_type, occurred_at, ended_at,
                title, summary, outcome, source_status, payload_json,
                narrative, narrative_state, narrative_model, narrative_at, narrative_attempts,
                is_open, content_digest, materialized_at
            ) VALUES (?, ?, ?, ?, ?, NULL, ?, ?, NULL, 'imported', ?, ?, 'final', 'import', ?, 0, 0, ?, ?)
            """,
            (
                f"{SOURCE_KIND}:{item.item_id}", SOURCE_KIND, item.item_id, EVENT_TYPE, occurred_at,
                title, summary, payload, item.text, now,
                content_digest(EVENT_TYPE, occurred_at, None, title, summary, None, "imported", payload),
                now,
            ),
        )
        if cursor.rowcount > 0:
            added += 1
    return {"added": added, "already_present": len(items) - added}


def list_batches(conn: sqlite3.Connection) -> List[BatchSummary]:
    rows = conn.execute(
        """
        SELECT json_extract(payload_json, '$.import_batch_id') AS batch_id,
               MIN(materialized_at) AS imported_at,
               MAX(json_extract(payload_json, '$.import_label')) AS label,
               COUNT(*) AS entry_count
        FROM zettel_entries
        WHERE source_kind = ?
        GROUP BY json_extract(payload_json, '$.import_batch_id')
        ORDER BY imported_at DESC
        """,
        (SOURCE_KIND,),
    ).fetchall()
    return [
        BatchSummary(
            batch_id=str(row["batch_id"]),
            imported_at=str(row["imported_at"]),
            label=str(row["label"] or ""),
            entry_count=int(row["entry_count"]),
        )
        for row in rows
        if row["batch_id"]
    ]


def undo_batch(conn: sqlite3.Connection, batch_id: str) -> int:
    """Delete every entry of one batch. The search index follows through the delete trigger. Returns the number removed."""
    cursor = conn.execute(
        "DELETE FROM zettel_entries WHERE source_kind = ? AND json_extract(payload_json, '$.import_batch_id') = ?",
        (SOURCE_KIND, batch_id),
    )
    return int(cursor.rowcount)

