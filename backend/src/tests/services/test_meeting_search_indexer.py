"""Tests for meeting_search_indexer.build_document (disk -> searchable text)."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from api.services.meetings import meeting_search_indexer


def _write_meeting(home: Path, meeting_id: str, metadata: dict, segments: list) -> None:
    meeting_dir = home / ".basil" / "meetings" / meeting_id
    meeting_dir.mkdir(parents=True, exist_ok=True)
    (meeting_dir / "metadata.json").write_text(json.dumps(metadata))
    (meeting_dir / "transcript.json").write_text(
        json.dumps({"meeting_id": meeting_id, "segments": segments})
    )


def test_build_document_combines_metadata_and_transcript(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    _write_meeting(
        tmp_path,
        "m1",
        {
            "id": "m1",
            "name": "Budget Review - Microphone",
            "purpose": "Discuss Q3 budget",
            "participants": ["Alice", "Bob"],
            "audio_source": "Microphone",
        },
        [
            {"start": 0.0, "end": 1.0, "text": "Hello team", "speaker": "Microphone", "is_interim": False},
            {"start": 1.0, "end": 2.0, "text": "   ", "speaker": "Microphone", "is_interim": False},
            {"start": 2.0, "end": 3.0, "text": "quarterly numbers", "speaker": "Microphone", "is_interim": False},
        ],
    )

    document = meeting_search_indexer.build_document("m1")
    assert document is not None
    # Name is cleaned of its " - Microphone" suffix.
    assert document.name == "Budget Review"
    assert document.purpose == "Discuss Q3 budget"
    assert document.participants == "Alice Bob"
    assert "Hello team" in document.transcript
    assert "quarterly numbers" in document.transcript
    # Whitespace-only segment contributes nothing.
    assert "   \n" not in document.transcript


def test_build_document_missing_meeting_returns_none(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert meeting_search_indexer.build_document("does-not-exist") is None


def test_build_document_includes_participant_email_addresses(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    _write_meeting(
        tmp_path,
        "m1",
        {
            "id": "m1",
            "name": "Budget Review",
            "participants": ["Alice <alice@example.com>"],
        },
        [],
    )

    document = meeting_search_indexer.build_document("m1")

    assert document is not None
    assert document.participants == "Alice <alice@example.com>"
