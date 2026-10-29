"""Round-trip tests for the meeting transcript FTS repository."""

import sys
import sqlite3
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.meetings.transcript_search_repository import (
    MeetingSearchDocument,
    MeetingSearchTerm,
    MeetingTranscriptSearchRepository,
    parse_search_terms,
)


@pytest.fixture
def repo(tmp_path) -> MeetingTranscriptSearchRepository:
    # Fresh db file; the repo ensures the FTS table on first connection.
    return MeetingTranscriptSearchRepository(str(tmp_path / "knowledge.db"))


def test_reindex_and_match_search(repo):
    repo.reindex_meeting("m1", MeetingSearchDocument(transcript="Quarterly budget review and onboarding plan"))
    repo.reindex_meeting("m2", MeetingSearchDocument(transcript="Daily standup notes"))

    assert repo.search_meeting_ids("budget") == ["m1"]
    assert repo.search_meeting_ids("standup") == ["m2"]
    # Token prefix matching (FTS MATCH): "onboard" -> "onboarding".
    assert repo.search_meeting_ids("onboard") == ["m1"]


def test_substring_like_fallback(repo):
    # "board" is an infix of "onboarding"; the porter prefix MATCH alone misses
    # it, so this proves the LIKE substring fallback is wired.
    repo.reindex_meeting("m1", MeetingSearchDocument(transcript="Quarterly onboarding plan"))
    assert repo.search_meeting_ids("board") == ["m1"]


def test_reindex_replaces_previous_document(repo):
    repo.reindex_meeting("m1", MeetingSearchDocument(transcript="budget review"))
    repo.reindex_meeting("m1", MeetingSearchDocument(transcript="vacation planning"))  # replaces
    assert repo.search_meeting_ids("budget") == []
    assert repo.search_meeting_ids("vacation") == ["m1"]


def test_empty_query_returns_nothing(repo):
    repo.reindex_meeting("m1", MeetingSearchDocument(transcript="anything at all"))
    assert repo.search_meeting_ids("") == []
    assert repo.search_meeting_ids("   ") == []
    # Punctuation-only query has no usable tokens -> no invalid MATCH issued.
    assert repo.search_meeting_ids("!!! ???") == []


def test_remove_and_clear(repo):
    repo.reindex_meeting("m1", MeetingSearchDocument(transcript="budget review"))
    repo.reindex_meeting("m2", MeetingSearchDocument(transcript="standup notes"))

    repo.remove_meeting("m1")
    assert repo.search_meeting_ids("budget") == []
    assert repo.search_meeting_ids("standup") == ["m2"]

    repo.clear_all()
    assert repo.search_meeting_ids("standup") == []


def test_pagination_over_matches(repo):
    for i in range(5):
        repo.reindex_meeting(f"m{i}", MeetingSearchDocument(transcript="shared keyword content"))
    # Ordered by meeting_id; offset/limit slice the candidate set.
    page = repo.search_meeting_ids("keyword", limit=2, offset=1)
    assert page == ["m1", "m2"]


def test_structured_fields_intersect_and_global_searches_all_columns(repo):
    repo.reindex_meeting(
        "m1",
        MeetingSearchDocument(
            name="Revenue Review",
            participants="Miriam <miriam@example.com>",
            transcript="A new opportunity reached the next stage.",
        ),
    )
    repo.reindex_meeting(
        "m2",
        MeetingSearchDocument(
            name="Revenue Review",
            participants="Another person",
            transcript="A new opportunity reached the next stage.",
        ),
    )

    assert repo.search_meeting_ids(participants="miriam", transcript="opportunity") == ["m1"]
    assert repo.search_meeting_ids(query="miriam") == ["m1"]
    assert repo.search_meeting_ids(name="opportunity") == []


def test_comma_terms_support_and_or_and_literal_commas(repo):
    repo.reindex_meeting("both", MeetingSearchDocument(transcript="opportunity stage"))
    repo.reindex_meeting("opportunity", MeetingSearchDocument(transcript="opportunity only"))
    repo.reindex_meeting("literal", MeetingSearchDocument(transcript="opportunity, stage"))

    assert repo.search_meeting_ids(transcript="opportunity,stage") == ["both", "literal"]
    assert repo.search_meeting_ids(
        transcript="opportunity,stage", transcript_mode="or"
    ) == ["both", "literal", "opportunity"]
    assert repo.search_meeting_ids(transcript='"opportunity, stage"') == ["literal"]
    assert repo.search_meeting_ids(
        transcript='opportunity,"opportunity, stage"'
    ) == ["literal"]


def test_quote_aware_parser_ignores_empty_values_and_unmatched_quotes():
    assert parse_search_terms('opportunity, "stage, gate", ,') == [
        MeetingSearchTerm("opportunity", False),
        MeetingSearchTerm("stage, gate", True),
    ]
    assert parse_search_terms('"unfinished') == [MeetingSearchTerm('"unfinished', False)]


def test_legacy_index_schema_is_rebuilt(repo):
    with sqlite3.connect(repo.db_path) as conn:
        conn.execute("CREATE VIRTUAL TABLE meeting_transcript_fts USING fts5(meeting_id UNINDEXED, content)")

    with repo._get_connection() as conn:
        columns = [row[1] for row in conn.execute("PRAGMA table_info(meeting_transcript_fts)")]

    assert columns == ["meeting_id", "name", "purpose", "participants", "transcript"]
