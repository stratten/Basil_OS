"""Coalescing adapter that turns screen captures into narrative blocks.

A block is a run of consecutive captures in the same app and work context with
no gap longer than BLOCK_GAP_SECONDS. Membership is bounded
by the zettel_id back-reference rather than a moving watermark: once a block is
carded, every member capture is stamped, so it can never be re-coalesced. A
still-open trailing block is left un-carded until it closes, so a whole session
becomes one block rather than fragmenting across passes.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence

from api.services.zettel.normalization import to_utc_iso, truncate
from api.services.zettel.sources.base import ZettelDraft

BLOCK_GAP_SECONDS = 600
MAX_CAPTURES_PER_BLOCK = 500

# How many member captures are described to the narrative model. The prompt caps
# the gathered context at CONTEXT_MAX_CHARS and truncates the tail, so handing it
# every member of a long block would describe only the block's opening minutes.
# This many evenly spaced captures span the block and still fit the budget at the
# field limits below; test_large_block_context_stays_within_the_prompt_budget
# holds that relationship, since the two constants live in different modules.
MAX_CONTEXT_CAPTURES = 8

_COLUMNS = (
    "id", "timestamp", "created_at", "app_name", "window_title",
    "extracted_text", "ai_analysis", "duration", "context_hash",
)

_WORK_CONTEXT_METADATA_KEYS = (
    "work_context_key",
    "work_context_label",
    "work_context_kind",
    "work_context_confidence",
    "work_context_evidence",
    "work_context_version",
)

_SELECT_COLUMNS = ", ".join(f"a.{column}" for column in _COLUMNS)
_WORK_CONTEXT_SELECT = ", ".join(
    f"MAX(CASE WHEN m.key = '{key}' THEN m.value END) AS {key}"
    for key in _WORK_CONTEXT_METADATA_KEYS
)


class ScreenActivitySource:
    """Projects the activities table into coalesced blocks."""

    source_kind = "screen_block"

    def find_uncarded(
        self,
        conn: sqlite3.Connection,
        *,
        since_iso: Optional[str],
        limit: int,
    ) -> List[ZettelDraft]:
        # A block holds at most MAX_CAPTURES_PER_BLOCK captures, so fetch at
        # least one more than that regardless of the caller's chunk size. This
        # guarantees any single block fits entirely inside one window, so the
        # carding drain loop can never deadlock on a block larger than its chunk.
        effective_limit = max(limit, MAX_CAPTURES_PER_BLOCK + 1)
        clauses = ["a.zettel_id IS NULL"]
        params: List[Any] = []
        if since_iso:
            clauses.append("a.timestamp >= ?")
            params.append(since_iso)
        where = f"WHERE {' AND '.join(clauses)}"
        params.append(effective_limit)
        metadata_keys = ", ".join(f"'{key}'" for key in _WORK_CONTEXT_METADATA_KEYS)
        rows = conn.execute(
            f"""
            SELECT {_SELECT_COLUMNS}, {_WORK_CONTEXT_SELECT}
            FROM activities a
            LEFT JOIN activity_metadata m
                ON m.activity_id = a.id AND m.key IN ({metadata_keys})
            {where}
            GROUP BY a.id
            ORDER BY a.timestamp ASC, a.id ASC
            LIMIT ?
            """,
            params,
        ).fetchall()
        blocks = self._blocks(rows)
        if not blocks:
            return []
        if len(rows) >= effective_limit and len(blocks) > 1:
            # The window filled up, so more captures of the last block may sit
            # just beyond it. Defer that block; it is re-read whole next chunk.
            # Earlier blocks are complete and card now, so the loop advances.
            blocks = blocks[:-1]
        elif not self._is_closed(blocks[-1][-1]):
            # Window not full: the last block is the genuinely-latest one. Leave
            # it un-carded until it closes so a live session stays one block.
            blocks = blocks[:-1]
        return [self._draft(block) for block in blocks]

    def count_uncarded(
        self,
        conn: sqlite3.Connection,
        *,
        since_iso: Optional[str],
    ) -> int:
        """Un-carded raw captures in the window.

        Counts captures rather than blocks: the block count is not known until
        coalescing runs, and a raw-capture backlog is the honest, cheap measure
        of how much screen activity is still waiting to be collected.
        """
        clauses = ["zettel_id IS NULL"]
        params: List[Any] = []
        if since_iso:
            clauses.append("timestamp >= ?")
            params.append(since_iso)
        where = f"WHERE {' AND '.join(clauses)}"
        row = conn.execute(
            f"SELECT COUNT(*) AS total FROM activities {where}", params
        ).fetchone()
        return int(row["total"]) if row is not None else 0

    def stamp(
        self,
        conn: sqlite3.Connection,
        draft: ZettelDraft,
        zettel_id: str,
    ) -> None:
        from api.services.zettel import store

        store.stamp_source(
            conn,
            table="activities",
            id_column="id",
            source_ids=draft.stamp_ids,
            zettel_id=zettel_id,
        )

    def gather_context(
        self,
        conn: sqlite3.Connection,
        source_ids: Sequence[str],
    ) -> Dict[str, Dict[str, Any]]:
        """Reconstruct each block from the stamp, not by re-coalescing.

        source_id is the block's anchor capture id, and every member was
        stamped with zettel_id = 'screen_block:<anchor>', so the members are a
        single indexed lookup.
        """
        context: Dict[str, Dict[str, Any]] = {}
        metadata_keys = ", ".join(f"'{key}'" for key in _WORK_CONTEXT_METADATA_KEYS)
        for anchor in (str(value) for value in source_ids):
            rows = conn.execute(
                f"""
                SELECT a.app_name, a.window_title, a.extracted_text, a.ai_analysis,
                       a.timestamp, {_WORK_CONTEXT_SELECT}
                FROM activities a
                LEFT JOIN activity_metadata m
                    ON m.activity_id = a.id AND m.key IN ({metadata_keys})
                WHERE a.zettel_id = ?
                GROUP BY a.id
                ORDER BY a.timestamp ASC
                """,
                (f"screen_block:{anchor}",),
            ).fetchall()
            if not rows:
                continue
            shown = self._sample(rows)
            whole_block = len(shown) == len(rows)
            context[anchor] = {
                "app_name": rows[0]["app_name"],
                "capture_count": len(rows),
                "captures_shown": len(shown),
                "work_context": self._work_context_identity(rows[0]),
                "captures": [
                    self._capture_context(row, include_text=whole_block)
                    for row in shown
                ],
            }
        return context

    def _sample(self, rows: Sequence[sqlite3.Row]) -> List[sqlite3.Row]:
        """Evenly spaced captures spanning the block, first and last included.

        Taking the leading N instead would narrate a two-hour session from its
        first few minutes, since the prompt truncates whatever overflows.
        """
        if len(rows) <= MAX_CONTEXT_CAPTURES:
            return list(rows)
        step = (len(rows) - 1) / (MAX_CONTEXT_CAPTURES - 1)
        return [rows[round(index * step)] for index in range(MAX_CONTEXT_CAPTURES)]

    def _capture_context(
        self,
        row: sqlite3.Row,
        *,
        include_text: bool = True,
    ) -> Dict[str, Any]:
        """One capture as narrative source material.

        The analysis fields were previously unbounded, so a verbose analysis
        could consume the whole context budget on its own. Raw OCR text is
        dropped for sampled blocks: across a long session the per-capture
        analysis carries the meaning, and spending the budget on text from ten
        scattered moments buys less than covering the span.
        """
        analysis = self._parse_analysis(row["ai_analysis"])
        capture: Dict[str, Any] = {
            "window_title": truncate(row["window_title"], 120),
            "content_summary": truncate(analysis.get("content_summary"), 200),
            "context": truncate(analysis.get("context"), 200),
            "activity_type": analysis.get("activity_type"),
        }
        if include_text:
            capture["extracted_text"] = truncate(row["extracted_text"], 300)
        return capture

    def _parse_analysis(self, value: Any) -> Dict[str, Any]:
        if not value:
            return {}
        try:
            parsed = json.loads(value) if isinstance(value, str) else value
            return parsed if isinstance(parsed, dict) else {}
        except (TypeError, ValueError):
            return {}

    def _blocks(self, rows: Sequence[sqlite3.Row]) -> List[List[sqlite3.Row]]:
        blocks: List[List[sqlite3.Row]] = []
        current: List[sqlite3.Row] = []
        for row in rows:
            if not current:
                current = [row]
                continue
            if self._continues(current[-1], row) and len(current) < MAX_CAPTURES_PER_BLOCK:
                current.append(row)
                continue
            blocks.append(current)
            current = [row]
        if current:
            blocks.append(current)
        return blocks

    def _work_context_identity(self, row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "key": truncate(row["work_context_key"], 120),
            "label": truncate(row["work_context_label"], 120),
            "kind": row["work_context_kind"],
            "confidence": row["work_context_confidence"],
            "evidence": truncate(row["work_context_evidence"], 300),
        }

    def _continues(self, previous: sqlite3.Row, candidate: sqlite3.Row) -> bool:
        if previous["app_name"] != candidate["app_name"]:
            return False
        if previous["work_context_key"] != candidate["work_context_key"]:
            return False
        return self._gap_seconds(previous["timestamp"], candidate["timestamp"]) <= BLOCK_GAP_SECONDS

    def _gap_seconds(self, earlier: Any, later: Any) -> float:
        first = to_utc_iso(earlier)
        second = to_utc_iso(later)
        if first is None or second is None:
            return float("inf")
        return abs(
            (datetime.fromisoformat(second) - datetime.fromisoformat(first)).total_seconds()
        )

    def _draft(self, block: Sequence[sqlite3.Row]) -> ZettelDraft:
        first, last = block[0], block[-1]
        occurred_at = to_utc_iso(first["timestamp"]) or to_utc_iso(first["created_at"])
        ended_at = to_utc_iso(last["timestamp"])
        app_name = first["app_name"] or "Unknown app"
        window_title = truncate(first["window_title"], 120)
        title = f"{app_name}: {window_title}" if window_title else app_name
        return ZettelDraft(
            source_kind=self.source_kind,
            source_id=str(first["id"]),
            event_type="screen_block",
            occurred_at=occurred_at or "",
            ended_at=ended_at,
            title=title,
            summary=self._summary(block),
            source_status=None,
            payload={
                "app_name": app_name,
                "context_hash": first["context_hash"],
                "capture_count": len(block),
                "first_activity_id": str(first["id"]),
                "last_activity_id": str(last["id"]),
                "window_titles": self._window_titles(block),
                "duration_seconds": self._duration_seconds(block, occurred_at, ended_at),
                "work_context_key": first["work_context_key"],
                "work_context_label": first["work_context_label"],
                "work_context_kind": first["work_context_kind"],
                "work_context_confidence": first["work_context_confidence"],
                "work_context_evidence": first["work_context_evidence"],
            },
            member_source_ids=[str(row["id"]) for row in block],
        )

    def _summary(self, block: Sequence[sqlite3.Row]) -> Optional[str]:
        for row in block:
            analysis = self._parse_analysis(row["ai_analysis"])
            summary = analysis.get("content_summary")
            if summary:
                return truncate(str(summary), 500)
        for row in block:
            if row["extracted_text"]:
                return truncate(str(row["extracted_text"]), 500)
        return None

    def _window_titles(self, block: Sequence[sqlite3.Row]) -> List[str]:
        seen: List[str] = []
        for row in block:
            title = truncate(row["window_title"], 80)
            if title and title not in seen:
                seen.append(title)
            if len(seen) >= 5:
                break
        return seen

    def _duration_seconds(
        self,
        block: Sequence[sqlite3.Row],
        start: Optional[str],
        end: Optional[str],
    ) -> Optional[float]:
        """Time the block actually represents, not merely the span it covers.

        The span between first and last capture omits the final capture's own
        dwell entirely, so a single-capture block measures zero even though it
        stands for real elapsed time. The capture service records a per-capture
        duration; prefer summing it and fall back to the span only where it is
        missing.
        """
        recorded = [
            float(row["duration"]) for row in block if row["duration"] is not None
        ]
        if len(recorded) == len(block) and recorded:
            return round(sum(recorded), 3)

        span = self._span_seconds(start, end)
        if not recorded:
            return span
        return max(span, round(sum(recorded), 3)) if span is not None else round(sum(recorded), 3)

    def _span_seconds(self, start: Optional[str], end: Optional[str]) -> Optional[float]:
        if not start or not end:
            return None
        try:
            return (
                datetime.fromisoformat(end) - datetime.fromisoformat(start)
            ).total_seconds()
        except ValueError:
            return None

    def _is_closed(self, last: sqlite3.Row) -> bool:
        """A block is closed once no capture has extended it for a full gap."""
        last_seen = to_utc_iso(last["timestamp"])
        if last_seen is None:
            return True
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=BLOCK_GAP_SECONDS)
        try:
            return datetime.fromisoformat(last_seen) <= cutoff
        except ValueError:
            return True
