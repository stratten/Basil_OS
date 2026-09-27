"""One generic table-backed adapter, driven by declarative config.

Five sources share identical SQL and differ only in column names and the
functions that build display text. Five near-identical classes would be
duplication; this is the shared abstraction.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence

from api.services.zettel.normalization import to_utc_iso
from api.services.zettel.sources.base import ZettelDraft

logger = logging.getLogger(__name__)

# A source-specific builder that gathers finalize context for many rows at
# once (used where the material lives in another table, e.g. a joined thread).
ContextBuilder = Callable[[sqlite3.Connection, Sequence[str]], Dict[str, Dict[str, Any]]]


@dataclass(frozen=True)
class TableSourceConfig:
    """Everything that distinguishes one table projection from another."""

    source_kind: str
    event_type: str
    table: str
    id_column: str
    columns: Sequence[str]
    occurred_column: str
    title_of: Callable[[sqlite3.Row], str]
    summary_of: Callable[[sqlite3.Row], Optional[str]]
    payload_of: Callable[[sqlite3.Row], Dict[str, Any]]
    outcome_of: Callable[[sqlite3.Row], Optional[str]]
    status_column: Optional[str] = None
    ended_column: Optional[str] = None
    where_clause: Optional[str] = None
    # Columns pulled straight from this table for narrative synthesis.
    narrative_columns: Sequence[str] = ()
    # Overrides the default same-table context gather when the material is
    # elsewhere (scheduled_run joins its task; conversation joins its messages).
    context_builder: Optional[ContextBuilder] = None


class TableZettelSource:
    """Projects rows of one table into cards according to its config."""

    def __init__(self, config: TableSourceConfig) -> None:
        self._config = config
        self.source_kind = config.source_kind

    def find_uncarded(
        self,
        conn: sqlite3.Connection,
        *,
        since_iso: Optional[str],
        limit: int,
    ) -> List[ZettelDraft]:
        config = self._config
        clauses = ["zettel_id IS NULL"]
        params: List[Any] = []
        if since_iso:
            clauses.append(f"{config.occurred_column} >= ?")
            params.append(since_iso)
        if config.where_clause:
            clauses.append(config.where_clause)
        where = f"WHERE {' AND '.join(clauses)}"
        params.append(limit)
        sql = (
            f"SELECT {', '.join(config.columns)} FROM {config.table} {where} "
            f"ORDER BY {config.occurred_column} ASC, {config.id_column} ASC LIMIT ?"
        )
        drafts: List[ZettelDraft] = []
        for row in conn.execute(sql, params).fetchall():
            draft = self._draft(row)
            if draft is not None:
                drafts.append(draft)
        return drafts

    def count_uncarded(
        self,
        conn: sqlite3.Connection,
        *,
        since_iso: Optional[str],
    ) -> int:
        config = self._config
        clauses = ["zettel_id IS NULL"]
        params: List[Any] = []
        if since_iso:
            clauses.append(f"{config.occurred_column} >= ?")
            params.append(since_iso)
        if config.where_clause:
            clauses.append(config.where_clause)
        where = f"WHERE {' AND '.join(clauses)}"
        row = conn.execute(
            f"SELECT COUNT(*) AS total FROM {config.table} {where}", params
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
            table=self._config.table,
            id_column=self._config.id_column,
            source_ids=draft.stamp_ids,
            zettel_id=zettel_id,
        )

    def gather_context(
        self,
        conn: sqlite3.Connection,
        source_ids: Sequence[str],
    ) -> Dict[str, Dict[str, Any]]:
        config = self._config
        if config.context_builder is not None:
            return config.context_builder(conn, source_ids)
        cols = list(config.narrative_columns)
        ids = [str(value) for value in source_ids]
        if not cols or not ids:
            return {}
        placeholders = ",".join("?" * len(ids))
        select = ", ".join([config.id_column, *cols])
        rows = conn.execute(
            f"SELECT {select} FROM {config.table} "
            f"WHERE CAST({config.id_column} AS TEXT) IN ({placeholders})",
            ids,
        ).fetchall()
        return {
            str(row[config.id_column]): {col: row[col] for col in cols}
            for row in rows
        }

    def _draft(self, row: sqlite3.Row) -> Optional[ZettelDraft]:
        config = self._config
        occurred_at = to_utc_iso(row[config.occurred_column])
        if occurred_at is None:
            logger.debug(
                "Skipping %s row %s: no parseable timestamp",
                config.table,
                row[config.id_column],
            )
            return None
        status = None
        if config.status_column is not None and row[config.status_column] is not None:
            status = str(row[config.status_column])
        return ZettelDraft(
            source_kind=config.source_kind,
            source_id=str(row[config.id_column]),
            event_type=config.event_type,
            occurred_at=occurred_at,
            ended_at=to_utc_iso(row[config.ended_column]) if config.ended_column else None,
            title=config.title_of(row),
            summary=config.summary_of(row),
            outcome=config.outcome_of(row),
            source_status=status,
            payload=config.payload_of(row),
        )
