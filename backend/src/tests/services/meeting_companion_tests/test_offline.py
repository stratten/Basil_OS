import pytest

from api.services.meeting_companion import offline
from api.services.meeting_companion import store as store_module
from api.services.meeting_companion.models import CompanionItem, CompanionSettings, TimelineEvent, TranscriptRange
from api.services.meeting_companion.store import CompanionDocument, CompanionStore


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(store_module, "meetings_root", lambda: tmp_path)
    return tmp_path


def item_event(seq, item_id="i1"):
    item = CompanionItem(
        id=item_id,
        kind="insight",
        text="Retries were tuned last sprint.",
        confidence=0.8,
        transcript_range=TranscriptRange(start=8.0, end=10.0, turn_ids=[]),
        trigger="periodic",
    )
    return TimelineEvent(id=f"e{seq}", seq=seq, kind="item", meeting_time=10.0, wall_time="w", payload={"item": item.model_dump(mode="json")})


def save(home, meeting_id="m1", events=None, settings=None):
    directory = home / meeting_id
    directory.mkdir(parents=True, exist_ok=True)
    CompanionStore(directory).save(CompanionDocument(session_key=meeting_id, settings=settings or CompanionSettings(enabled=True), events=events or [], saved_at="w"))
    return directory


def test_meeting_exists_and_empty_snapshot(home):
    (home / "m1").mkdir()
    assert offline.meeting_exists("m1") is True and offline.meeting_exists("nope") is False
    snapshot = offline.empty_snapshot("m1")
    assert snapshot.meeting_id == "m1" and snapshot.status.enabled is False and snapshot.status.live is False and snapshot.items == []


def test_load_returns_none_when_nothing_is_saved(home):
    (home / "m1").mkdir()
    assert offline.load_stored_snapshot("m1") is None


def test_load_builds_a_stored_snapshot_in_sequence_order(home):
    save(home, events=[item_event(2, "i2"), item_event(1, "i1")])
    snapshot = offline.load_stored_snapshot("m1")
    assert [item.id for item in snapshot.items] == ["i1", "i2"]
    assert snapshot.status.live is False and snapshot.status.enabled is True and snapshot.last_seq == 2


def test_session_member_resolves_to_the_microphone_anchor(home):
    for meeting_id, source in (("mic1", "Microphone"), ("sys1", "Zoom")):
        directory = home / meeting_id
        directory.mkdir()
        (directory / "metadata.json").write_text(
            '{"id": "%s", "session_id": "s1", "audio_source": "%s", "start_time": "2026-01-01T10:00:00Z"}' % (meeting_id, source),
            encoding="utf-8",
        )
    CompanionStore(home / "mic1").save(CompanionDocument(session_key="s1", settings=CompanionSettings(enabled=True), events=[item_event(1)], saved_at="w"))
    snapshot = offline.load_stored_snapshot("sys1")
    assert snapshot is not None and snapshot.meeting_id == "sys1" and [item.id for item in snapshot.items] == ["i1"]


def test_record_feedback_persists_and_continues_the_sequence(home):
    save(home, events=[item_event(1)])
    assert offline.record_stored_feedback("m1", "i1", "pinned") is True
    snapshot = offline.load_stored_snapshot("m1")
    assert snapshot.items[0].pinned is True and snapshot.last_seq == 2
    assert offline.record_stored_feedback("m1", "i1", "dismissed") is True
    item = offline.load_stored_snapshot("m1").items[0]
    assert item.dismissed is True and item.pinned is False


def test_record_feedback_reports_missing_document_and_missing_item(home):
    (home / "m1").mkdir()
    assert offline.record_stored_feedback("m1", "i1", "pinned") is None
    save(home, events=[item_event(1)])
    assert offline.record_stored_feedback("m1", "missing", "pinned") is False
    assert offline.load_stored_snapshot("m1").last_seq == 1
