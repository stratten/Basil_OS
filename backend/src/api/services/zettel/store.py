"""Persistence for the zettel stream: carding inserts, stamps, narrative writes, reads."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from api.services.zettel.normalization import utc_now_iso
from api.services.zettel.sources.base import ZettelDraft


@dataclass(frozen=True)
class PendingEntry:
    entry_id: str
    source_kind: str
    source_id: str
    event_type: str
    occurred_at: str
    title: str
    summary: Optional[str]
    outcome: Optional[str]
    source_status: Optional[str]
    payload: Dict[str, Any]


def insert_card(conn: sqlite3.Connection, draft: ZettelDraft) -> bool:
    """Insert one thin card. Returns True if a row was created, False if it
    already existed. Idempotent via the (source_kind, source_id) uniqueness, so
    a re-run of the carding pass never duplicates.
    """
    now = utc_now_iso()
    cursor = conn.execute(
        """
        INSERT OR IGNORE INTO zettel_entries (
            id, source_kind, source_id, event_type, occurred_at, ended_at,
            title, summary, outcome, source_status, payload_json,
            narrative_state, narrative_attempts, content_digest, materialized_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', 0, ?, ?)
        """,
        (
            draft.entry_id, draft.source_kind, draft.source_id, draft.event_type,
            draft.occurred_at, draft.ended_at, draft.bounded_title(),
            draft.bounded_summary(), draft.outcome, draft.source_status,
            draft.payload_text(), draft.digest(), now,
        ),
    )
    return cursor.rowcount > 0


def stamp_source(
    conn: sqlite3.Connection,
    *,
    table: str,
    id_column: str,
    source_ids: Sequence[str],
    zettel_id: str,
) -> None:
    """Write the zettel_id back onto every source row a card was built from.

    For one-row sources that is a single id; for a coalesced screen block it is
    every member capture, so none is left un-stamped to be re-carded next pass.
    The table and id_column come from trusted source configs, never user input.
    """
    ids = [str(value) for value in source_ids]
    if not ids:
        return
    placeholders = ",".join("?" * len(ids))
    conn.execute(
        f"UPDATE {table} SET zettel_id = ? "
        f"WHERE zettel_id IS NULL AND CAST({id_column} AS TEXT) IN ({placeholders})",
        [zettel_id, *ids],
    )


def load_pending(
    conn: sqlite3.Connection,
    *,
    limit: int,
    max_attempts: int,
    touched_before: Optional[str] = None,
) -> List[PendingEntry]:
    """Entries still awaiting a successful narrative swing, newest first.

    Newest first because a large backlog is drained over many passes and recent
    events are the ones worth summarizing soonest; oldest-first spends the whole
    model budget on the far end of the history before reaching this week.
    Downstream consumption does not depend on this order - the memory sweep finds
    its work by the memory_swept_at stamp, not by a timestamp cursor.

    *touched_before* excludes rows already handled this run (narrative_at at or
    after the run's start), so a drain loop that repeatedly pulls a chunk cannot
    keep re-fetching the same still-open entries — every entry is visited at most
    once per run, and the loop terminates when nothing untouched remains.
    """
    clauses = ["narrative_state = 'pending'", "narrative_attempts < ?"]
    params: List[Any] = [max_attempts]
    if touched_before is not None:
        clauses.append("(narrative_at IS NULL OR narrative_at < ?)")
        params.append(touched_before)
    params.append(limit)
    rows = conn.execute(
        "SELECT id, source_kind, source_id, event_type, occurred_at, title, "
        "summary, outcome, source_status, payload_json FROM zettel_entries "
        f"WHERE {' AND '.join(clauses)} "
        "ORDER BY occurred_at DESC LIMIT ?",
        params,
    ).fetchall()
    return [
        PendingEntry(
            entry_id=row["id"],
            source_kind=row["source_kind"],
            source_id=row["source_id"],
            event_type=row["event_type"],
            occurred_at=row["occurred_at"],
            title=row["title"],
            summary=row["summary"],
            outcome=row["outcome"],
            source_status=row["source_status"],
            payload=_safe_payload(row["payload_json"]),
        )
        for row in rows
    ]


def count_pending(
    conn: sqlite3.Connection,
    *,
    max_attempts: int,
    touched_before: Optional[str] = None,
) -> int:
    """How many entries still await a narrative swing.

    Mirrors load_pending's WHERE exactly so the count and the queue can never
    disagree; used as the total for a drain's progress readout.
    """
    clauses = ["narrative_state = 'pending'", "narrative_attempts < ?"]
    params: List[Any] = [max_attempts]
    if touched_before is not None:
        clauses.append("(narrative_at IS NULL OR narrative_at < ?)")
        params.append(touched_before)
    row = conn.execute(
        f"SELECT COUNT(*) AS total FROM zettel_entries WHERE {' AND '.join(clauses)}",
        params,
    ).fetchone()
    return int(row["total"]) if row is not None else 0


def count_pending_by_attempt_eligibility(
    conn: sqlite3.Connection,
    *,
    max_attempts: int,
) -> Tuple[int, int]:
    """Return runnable pending entries and pending entries needing a reset.

    A user can lower ``max_attempts`` after entries have already accumulated
    more attempts. Those entries remain ``pending`` in durable state, but the
    narrative runner intentionally excludes them until a reset. Keeping the
    counts separate prevents the settings UI from advertising blocked work as
    immediately runnable work.
    """
    row = conn.execute(
        """
        SELECT
            SUM(CASE
                WHEN narrative_state = 'pending' AND narrative_attempts < ?
                THEN 1 ELSE 0
            END) AS runnable,
            SUM(CASE
                WHEN narrative_state = 'pending' AND narrative_attempts >= ?
                THEN 1 ELSE 0
            END) AS needs_retry
        FROM zettel_entries
        """,
        (max_attempts, max_attempts),
    ).fetchone()
    if row is None:
        return (0, 0)
    return (int(row["runnable"] or 0), int(row["needs_retry"] or 0))


def _safe_payload(payload_json: Optional[str]) -> Dict[str, Any]:
    try:
        decoded = json.loads(payload_json) if payload_json else {}
    except (TypeError, ValueError):
        return {}
    return decoded if isinstance(decoded, dict) else {}


def write_narrative(
    conn: sqlite3.Connection,
    entry_id: str,
    *,
    narrative: Optional[str],
    model: Optional[str],
    is_open: Optional[bool] = None,
    open_note: Optional[str] = None,
) -> None:
    """Persist a valid synthesized narrative as a final memory.

    The retired lifecycle arguments are accepted while existing integrations upgrade, but are deliberately ignored: valid model output is always final.
    """
    narrative_at = utc_now_iso()
    conn.execute(
        "UPDATE zettel_entries SET "
        "narrative = ?, narrative_model = ?, is_open = ?, open_note = ?, "
        "narrative_state = ?, narrative_at = ?, narrative_error = NULL "
        "WHERE id = ?",
        (narrative, model, 0, None, "final", narrative_at, entry_id),
    )


def record_failure(
    conn: sqlite3.Connection, entry_id: str, *, error: str, max_attempts: int
) -> None:
    """Bump the attempt count on a failed swing and give up once capped.

    Staying 'pending' below the cap lets a later pass retry a transient model
    outage; crossing it flips to 'failed' so one poison entry cannot stall the
    queue forever. The cap is applied in SQL against the freshly bumped count.
    """
    conn.execute(
        "UPDATE zettel_entries SET "
        "narrative_attempts = narrative_attempts + 1, "
        "narrative_error = ?, narrative_at = ?, "
        "narrative_state = CASE WHEN narrative_attempts + 1 >= ? THEN 'failed' "
        "ELSE 'pending' END "
        "WHERE id = ? AND narrative_state != 'final'",
        (error[:1000], utc_now_iso(), max_attempts, entry_id),
    )


def requeue_failed(conn: sqlite3.Connection) -> int:
    """Give every unfinished entry a clean slate for another pass.

    Scoped to any non-final row, not just rows already marked 'failed'. A bad
    model choice burns attempts on entries that stay 'pending' below the cap, so
    a 'failed'-only reset returned almost nothing while the real damage sat
    invisible: entries one swing away from being abandoned for a reason that no
    longer applies. Trying a different model must not cost retry budget.

    Resets ``narrative_attempts`` to 0 so ``load_pending``'s attempt cap can
    admit them again (e.g. 3 >= 3 would otherwise keep them invisible).
    Clears ``narrative_at`` so a running pass's ``touched_before`` filter
    cannot exclude a row that was just requeued. Rows already 'final' are left
    untouched; a completed narrative is never discarded by a reset.
    """
    cursor = conn.execute(
        "UPDATE zettel_entries SET "
        "narrative_state = 'pending', narrative_attempts = 0, "
        "narrative_error = NULL, narrative_at = NULL "
        "WHERE narrative_state != 'final' "
        "AND (narrative_state != 'pending' OR narrative_attempts > 0 "
        "     OR narrative_error IS NOT NULL)"
    )
    return cursor.rowcount


# Grouping expressions are a fixed allowlist because they are interpolated
# into SQL; the dimension never reaches the query as a caller-supplied string.
_GROUP_EXPRESSIONS = {
    "source_kind": "source_kind",
    "event_type": "event_type",
    "outcome": "COALESCE(outcome, 'none')",
    "narrative_state": "narrative_state",
    # Local calendar day, matching how users name days and how relative tokens resolve.
    "day": "date(occurred_at, 'localtime')",
}


def _build_filters(
    *,
    start: Optional[str],
    end: Optional[str],
    source_kinds: Optional[List[str]],
    event_types: Optional[List[str]],
    outcome: Optional[str],
) -> Tuple[str, List[Any]]:
    """Shared WHERE builder so reads and aggregates cannot drift apart."""
    clauses: List[str] = []
    params: List[Any] = []
    if start:
        clauses.append("occurred_at >= ?")
        params.append(start)
    if end:
        clauses.append("occurred_at <= ?")
        params.append(end)
    if source_kinds:
        clauses.append(f"source_kind IN ({','.join('?' * len(source_kinds))})")
        params.extend(source_kinds)
    if event_types:
        clauses.append(f"event_type IN ({','.join('?' * len(event_types))})")
        params.extend(event_types)
    if outcome:
        clauses.append("outcome = ?")
        params.append(outcome)
    return (f"WHERE {' AND '.join(clauses)}" if clauses else "", params)


KEYSET_BEFORE_CLAUSE = "(occurred_at, source_kind, source_id) < (?, ?, ?)"
NEWEST_FIRST_ORDER = "ORDER BY occurred_at DESC, source_kind DESC, source_id DESC"


def with_keyset_before(
    where: str,
    params: List[Any],
    before: Optional[Tuple[str, str, str]],
) -> Tuple[str, List[Any]]:
    """Restrict a WHERE clause to rows strictly older than a browse cursor key."""
    if before is None:
        return where, list(params)
    clause = f"{where} AND {KEYSET_BEFORE_CLAUSE}" if where else f"WHERE {KEYSET_BEFORE_CLAUSE}"
    return clause, [*params, *before]


def count_entries_by(
    conn: sqlite3.Connection,
    *,
    dimension: str,
    start: Optional[str] = None,
    end: Optional[str] = None,
    source_kinds: Optional[List[str]] = None,
    event_types: Optional[List[str]] = None,
    outcome: Optional[str] = None,
) -> Dict[str, int]:
    """Count matching entries per bucket across the whole filtered range.

    Deliberately independent of any row limit: aggregating the returned page
    instead would silently under-report totals whenever the page is truncated.
    """
    expression = _GROUP_EXPRESSIONS.get(dimension)
    if expression is None:
        return {}
    where, params = _build_filters(
        start=start, end=end, source_kinds=source_kinds,
        event_types=event_types, outcome=outcome,
    )
    rows = conn.execute(
        f"SELECT {expression} AS bucket, COUNT(*) AS total "
        f"FROM zettel_entries {where} GROUP BY bucket ORDER BY bucket",
        params,
    ).fetchall()
    return {str(row["bucket"] if row["bucket"] is not None else "none"): row["total"] for row in rows}


def query_entries(
    conn: sqlite3.Connection,
    *,
    start: Optional[str] = None,
    end: Optional[str] = None,
    source_kinds: Optional[List[str]] = None,
    event_types: Optional[List[str]] = None,
    outcome: Optional[str] = None,
    limit: int = 200,
    before: Optional[Tuple[str, str, str]] = None,
) -> List[Dict[str, Any]]:
    where, params = _build_filters(
        start=start, end=end, source_kinds=source_kinds,
        event_types=event_types, outcome=outcome,
    )
    where, params = with_keyset_before(where, params, before)
    params.append(max(1, min(limit, 1000)))
    rows = conn.execute(
        "SELECT source_kind, source_id, event_type, occurred_at, ended_at, title, "
        "summary, outcome, source_status, narrative, narrative_state, is_open, "
        "open_note, payload_json "
        f"FROM zettel_entries {where} {NEWEST_FIRST_ORDER} LIMIT ?",
        params,
    ).fetchall()
    return [_row_to_dict(row) for row in rows]


def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    try:
        payload = json.loads(row["payload_json"])
    except (TypeError, ValueError):
        payload = {}
    return {
        "source_kind": row["source_kind"],
        "source_id": row["source_id"],
        "event_type": row["event_type"],
        "occurred_at": row["occurred_at"],
        "ended_at": row["ended_at"],
        "title": row["title"],
        # Prefer the synthesized narrative; the raw card summary is the fallback
        # for entries the finalizing pass has not reached yet.
        "summary": row["narrative"] or row["summary"],
        "raw_summary": row["summary"],
        "narrative": row["narrative"],
        "narrative_state": row["narrative_state"],
        "is_open": bool(row["is_open"]) if row["is_open"] is not None else None,
        "open_note": row["open_note"],
        "outcome": row["outcome"],
        "source_status": row["source_status"],
        "payload": payload if isinstance(payload, dict) else {},
    }
