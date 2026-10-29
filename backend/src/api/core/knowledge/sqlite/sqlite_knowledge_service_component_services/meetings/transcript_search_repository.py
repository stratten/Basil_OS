"""Maintained FTS index over meeting transcripts/metadata.

Meetings live on disk, so this index is kept in sync explicitly by the meeting
search indexer (reindex on stop/post-process, remove on delete, backfill on
startup). The query path mirrors the agent-task search: an FTS5 MATCH unioned
with a LIKE substring fallback (so partial words the porter tokenizer drops are
still found). Each stored row is one meeting directory id; grouping of session
siblings into a single sidebar entry happens in the search route.
"""

import logging
import sqlite3
from dataclasses import dataclass
from typing import Iterable, List

from ..infrastructure.connection import get_sync_connection
from ..schema_management.fts.query import (
    format_fts_match_query,
    escape_like_token,
    search_tokens,
)
from ..schema_management.fts.tables import ensure_meeting_transcript_fts

logger = logging.getLogger(__name__)

# Generous cap on candidate ids returned for a single search. The route expands
# these to session-sibling groups and paginates the grouped output, so this only
# needs to comfortably exceed any realistic page of grouped results.
DEFAULT_SEARCH_LIMIT = 1000


@dataclass(frozen=True)
class MeetingSearchDocument:
    """Structured text persisted for one on-disk meeting directory."""
    name: str = ""
    purpose: str = ""
    participants: str = ""
    transcript: str = ""

    @property
    def is_empty(self) -> bool:
        return not any((self.name, self.purpose, self.participants, self.transcript))


@dataclass(frozen=True)
class MeetingSearchTerm:
    """One comma-delimited query value, optionally a quoted literal."""
    value: str
    is_literal: bool


TEXT_COLUMNS = ("name", "purpose", "participants", "transcript")


def parse_search_terms(raw_value: str) -> List[MeetingSearchTerm]:
    """Split commas outside paired quotes and preserve complete quoted literals."""
    pieces: List[str] = []
    current: List[str] = []
    in_quotes = False
    for character in raw_value or "":
        if character == '"':
            in_quotes = not in_quotes
        if character == "," and not in_quotes:
            pieces.append("".join(current))
            current = []
        else:
            current.append(character)
    pieces.append("".join(current))

    terms: List[MeetingSearchTerm] = []
    for piece in pieces:
        trimmed = piece.strip()
        is_literal = len(trimmed) >= 2 and trimmed.startswith('"') and trimmed.endswith('"')
        value = trimmed[1:-1] if is_literal else trimmed
        if value:
            terms.append(MeetingSearchTerm(value=value, is_literal=is_literal))
    return terms


class MeetingTranscriptSearchRepository:
    """Read/write access to the `meeting_transcript_fts` index."""

    def __init__(self, db_path: str):
        self.db_path = db_path

    def _get_connection(self) -> sqlite3.Connection:
        conn = get_sync_connection(self.db_path, ensure_schema=False)
        ensure_meeting_transcript_fts(conn)
        return conn

    def reindex_meeting(self, meeting_id: str, document: MeetingSearchDocument) -> None:
        """Replace the indexed document for a meeting (DELETE + INSERT)."""
        if not meeting_id:
            return
        with self._get_connection() as conn:
            conn.execute(
                "DELETE FROM meeting_transcript_fts WHERE meeting_id = ?",
                (meeting_id,),
            )
            conn.execute(
                """
                INSERT INTO meeting_transcript_fts(
                    meeting_id, name, purpose, participants, transcript
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    meeting_id,
                    document.name,
                    document.purpose,
                    document.participants,
                    document.transcript,
                ),
            )

    def remove_meeting(self, meeting_id: str) -> None:
        """Drop a meeting's indexed document (used on delete)."""
        if not meeting_id:
            return
        with self._get_connection() as conn:
            conn.execute(
                "DELETE FROM meeting_transcript_fts WHERE meeting_id = ?",
                (meeting_id,),
            )

    def clear_all(self) -> None:
        """Empty the index (used before a full backfill)."""
        with self._get_connection() as conn:
            conn.execute("DELETE FROM meeting_transcript_fts")

    def _matching_ids_for_term(
        self,
        conn: sqlite3.Connection,
        term: MeetingSearchTerm,
        column: str | None,
    ) -> set[str]:
        """Return IDs matching one value in its field or any text field."""
        columns = (column,) if column else TEXT_COLUMNS
        if term.is_literal:
            predicates = [f"LOWER({name}) LIKE ? ESCAPE '\\'" for name in columns]
            cursor = conn.execute(
                f"SELECT meeting_id FROM meeting_transcript_fts WHERE {' OR '.join(predicates)}",
                [f"%{escape_like_token(term.value.lower())}%"] * len(columns),
            )
            return {row[0] for row in cursor.fetchall()}

        tokens = search_tokens(term.value)
        fts_query = format_fts_match_query(term.value)
        if not tokens or not fts_query:
            return set()

        scoped_fts_query = f"{column} : ({fts_query})" if column else fts_query
        fts_cursor = conn.execute(
            "SELECT meeting_id FROM meeting_transcript_fts WHERE meeting_transcript_fts MATCH ?",
            (scoped_fts_query,),
        )
        matched_ids = {row[0] for row in fts_cursor.fetchall()}

        token_conditions = []
        params: List[str] = []
        for token in tokens:
            token_conditions.append(
                "(" + " OR ".join(f"LOWER({name}) LIKE ? ESCAPE '\\'" for name in columns) + ")"
            )
            params.extend([f"%{escape_like_token(token)}%"] * len(columns))
        like_cursor = conn.execute(
            f"SELECT meeting_id FROM meeting_transcript_fts WHERE {' AND '.join(token_conditions)}",
            params,
        )
        matched_ids.update(row[0] for row in like_cursor.fetchall())
        return matched_ids

    def _matching_ids_for_value_list(
        self,
        conn: sqlite3.Connection,
        raw_value: str,
        mode: str,
        column: str | None,
    ) -> set[str] | None:
        terms = parse_search_terms(raw_value)
        if not terms:
            return None
        matching_sets = [self._matching_ids_for_term(conn, term, column) for term in terms]
        if mode == "or":
            return set().union(*matching_sets)
        return set.intersection(*matching_sets)

    def search_meeting_ids(
        self,
        query: str = "",
        *,
        query_mode: str = "and",
        name: str = "",
        name_mode: str = "and",
        purpose: str = "",
        purpose_mode: str = "and",
        participants: str = "",
        participants_mode: str = "and",
        transcript: str = "",
        transcript_mode: str = "and",
        limit: int | None = None,
        offset: int = 0,
    ) -> List[str]:
        """Meeting IDs satisfying every populated textual field constraint."""
        constraints = (
            (query, query_mode, None),
            (name, name_mode, "name"),
            (purpose, purpose_mode, "purpose"),
            (participants, participants_mode, "participants"),
            (transcript, transcript_mode, "transcript"),
        )
        with self._get_connection() as conn:
            field_matches = [
                matches
                for value, mode, column in constraints
                if (matches := self._matching_ids_for_value_list(conn, value, mode, column)) is not None
            ]
        if not field_matches:
            return []

        matched_ids = sorted(set.intersection(*field_matches))
        result = matched_ids[offset:] if limit is None else matched_ids[offset:offset + limit]
        logger.info(
            "Meeting transcript search returned %d ids (query=%r, limit=%s, offset=%d)",
            len(result), query, limit, offset,
        )
        return result
