"""Tests for keeping meeting FTS documents current after metadata edits."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from api.routes.meetings import lifecycle_routes
from api.routes.meetings.models import MeetingMetadataUpdate
from api.services.meetings.meeting_recorder import MeetingMetadata


def test_metadata_update_reindexes_every_session_member(monkeypatch):
    primary = MeetingMetadata(
        id="microphone-member",
        name="Original - Microphone",
        session_id="session-1",
        audio_source="Microphone",
    )
    sibling = MeetingMetadata(
        id="system-member",
        name="Original - System Audio",
        session_id="session-1",
        audio_source="System Audio",
    )
    indexed_ids: list[str] = []

    monkeypatch.setattr(
        lifecycle_routes.MeetingRecorder,
        "load_metadata",
        staticmethod(lambda meeting_id: primary if meeting_id == primary.id else None),
    )
    monkeypatch.setattr(
        lifecycle_routes,
        "_load_session_sibling_metadata",
        lambda session_id, exclude_meeting_id: [sibling],
    )
    monkeypatch.setattr(lifecycle_routes, "_save_meeting_metadata", lambda metadata: None)
    monkeypatch.setattr(
        lifecycle_routes.meeting_search_indexer,
        "reindex",
        indexed_ids.append,
    )

    asyncio.run(
        lifecycle_routes.update_meeting_metadata(
            primary.id,
            MeetingMetadataUpdate(
                name="Budget review",
                purpose=None,
                participants=["Alice <alice@example.com>"],
            ),
        )
    )

    assert indexed_ids == [primary.id, sibling.id]
    assert primary.participants == ["Alice <alice@example.com>"]
    assert sibling.participants == ["Alice <alice@example.com>"]
