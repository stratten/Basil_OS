"""The contract every zettel source adapter satisfies."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, Sequence, runtime_checkable

from api.services.zettel.normalization import (
    SUMMARY_MAX_CHARS,
    TITLE_MAX_CHARS,
    bounded_payload,
    content_digest,
    truncate,
)


@dataclass(frozen=True)
class ZettelDraft:
    """One projected event, before it is carded into the stream.

    Bounds are applied by the accessor methods rather than at construction so
    an adapter cannot accidentally bypass them and the store has exactly one
    enforcement point.
    """

    source_kind: str
    source_id: str
    event_type: str
    occurred_at: str
    title: str
    ended_at: Optional[str] = None
    summary: Optional[str] = None
    outcome: Optional[str] = None
    source_status: Optional[str] = None
    payload: Dict[str, Any] = field(default_factory=dict)

    # Every source row this card was built from, so the carding pass can stamp
    # each one with the zettel_id. A one-row source leaves this None and the
    # single source_id is stamped; a coalesced block lists all its captures.
    member_source_ids: Optional[Sequence[str]] = None

    @property
    def entry_id(self) -> str:
        return f"{self.source_kind}:{self.source_id}"

    @property
    def stamp_ids(self) -> Sequence[str]:
        return self.member_source_ids if self.member_source_ids is not None else [self.source_id]

    def bounded_title(self) -> str:
        return truncate(self.title, TITLE_MAX_CHARS) or f"{self.event_type} event"

    def bounded_summary(self) -> Optional[str]:
        return truncate(self.summary, SUMMARY_MAX_CHARS)

    def payload_text(self) -> str:
        return bounded_payload(self.payload)

    def digest(self) -> str:
        return content_digest(
            self.event_type,
            self.occurred_at,
            self.ended_at,
            self.bounded_title(),
            self.bounded_summary(),
            self.outcome,
            self.source_status,
            self.payload_text(),
        )


@runtime_checkable
class ZettelSource(Protocol):
    """Projects one underlying table into cards and gathers finalize context."""

    source_kind: str

    def find_uncarded(
        self,
        conn: sqlite3.Connection,
        *,
        since_iso: Optional[str],
        limit: int,
    ) -> List[ZettelDraft]:
        """Rows with no zettel_id yet, occurring at/after *since_iso*, oldest first."""
        ...

    def count_uncarded(
        self,
        conn: sqlite3.Connection,
        *,
        since_iso: Optional[str],
    ) -> int:
        """How many source rows are still un-carded within the window.

        Powers the "waiting to be collected" metric, so it must count over the
        whole range independent of any pass limit.
        """
        ...

    def stamp(
        self,
        conn: sqlite3.Connection,
        draft: ZettelDraft,
        zettel_id: str,
    ) -> None:
        """Write *zettel_id* back onto every source row the draft consumed."""
        ...

    def gather_context(
        self,
        conn: sqlite3.Connection,
        source_ids: Sequence[str],
    ) -> Dict[str, Dict[str, Any]]:
        """Rich raw material for narrative synthesis, keyed by source_id."""
        ...


def get_zettel_sources() -> List[ZettelSource]:
    """Build the active source set. Imports are local to avoid a cycle."""
    from api.services.zettel.sources.configs import build_table_sources
    from api.services.zettel.sources.conversation_turn_source import ConversationTurnSource
    from api.services.zettel.sources.meeting_source import MeetingZettelSource
    from api.services.zettel.sources.screen_source import ScreenActivitySource

    return [
        *build_table_sources(),
        ConversationTurnSource(),
        ScreenActivitySource(),
        MeetingZettelSource(),
    ]


def sources_by_kind() -> Dict[str, ZettelSource]:
    return {source.source_kind: source for source in get_zettel_sources()}
