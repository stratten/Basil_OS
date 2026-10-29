import json
from pathlib import Path

from api.services.meeting_companion.models import CompanionGlobalSettings, CompanionSettings, TimelineEvent
from api.services.meeting_companion.store import (
    COMPANION_FILE_NAME,
    CompanionDocument,
    CompanionGlobalSettingsStore,
    CompanionStore,
    meeting_id_for_session_key,
    resolve_anchor_meeting_dir,
)


def write_metadata(root: Path, meeting_id: str, **fields):
    directory = root / meeting_id
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "metadata.json").write_text(json.dumps({"id": meeting_id, **fields}), encoding="utf-8")
    return directory


def sample_document() -> CompanionDocument:
    event = TimelineEvent(id="e1", seq=1, kind="status", meeting_time=0, wall_time="w", payload={"enabled": True})
    return CompanionDocument(session_key="s1", settings=CompanionSettings(enabled=True), events=[event], saved_at="now")


def test_roundtrip(tmp_path):
    store = CompanionStore(tmp_path)
    assert store.load() is None
    store.save(sample_document())
    loaded = store.load()
    assert loaded is not None and loaded.events[0].id == "e1" and loaded.settings.enabled is True


def test_corrupt_file_is_set_aside_and_load_returns_none(tmp_path):
    (tmp_path / COMPANION_FILE_NAME).write_text("{not json", encoding="utf-8")
    store = CompanionStore(tmp_path)
    assert store.load() is None
    assert not (tmp_path / COMPANION_FILE_NAME).exists()
    assert len(list(tmp_path.glob("companion.corrupt-*.json"))) == 1


def test_schema_invalid_file_is_set_aside(tmp_path):
    (tmp_path / COMPANION_FILE_NAME).write_text(json.dumps({"events": "nope"}), encoding="utf-8")
    assert CompanionStore(tmp_path).load() is None
    assert len(list(tmp_path.glob("companion.corrupt-*.json"))) == 1


def test_remove_missing_file_is_a_noop(tmp_path):
    CompanionStore(tmp_path).remove()


def test_anchor_for_standalone_recording_is_its_own_directory(tmp_path):
    write_metadata(tmp_path, "solo", start_time="2026-01-01T10:00:00")
    assert resolve_anchor_meeting_dir("solo", root=tmp_path) == tmp_path / "solo"


def test_anchor_prefers_microphone_member(tmp_path):
    write_metadata(tmp_path, "sys", session_id="s", audio_source="Zoom", start_time="2026-01-01T10:00:00", recording_part_index=0)
    write_metadata(tmp_path, "mic", session_id="s", audio_source="Microphone", start_time="2026-01-01T10:00:02", recording_part_index=0)
    assert resolve_anchor_meeting_dir("sys", root=tmp_path) == tmp_path / "mic"
    assert resolve_anchor_meeting_dir("mic", root=tmp_path) == tmp_path / "mic"


def test_anchor_without_microphone_is_earliest_by_part_then_start(tmp_path):
    write_metadata(tmp_path, "b", session_id="s", audio_source="Zoom", start_time="2026-01-01T10:00:05", recording_part_index=0)
    write_metadata(tmp_path, "a", session_id="s", audio_source="Teams", start_time="2026-01-01T10:00:01", recording_part_index=0)
    write_metadata(tmp_path, "c", session_id="s", audio_source="Zoom", start_time="2026-01-01T09:00:00", recording_part_index=1)
    assert resolve_anchor_meeting_dir("c", root=tmp_path) == tmp_path / "a"


def test_anchor_for_unknown_meeting_returns_the_would_be_directory(tmp_path):
    assert resolve_anchor_meeting_dir("ghost", root=tmp_path) == tmp_path / "ghost"


def test_meeting_id_for_a_standalone_session_key_is_the_meeting_itself(tmp_path):
    write_metadata(tmp_path, "solo", start_time="2026-01-01T10:00:00")
    assert meeting_id_for_session_key("solo", root=tmp_path) == "solo"


def test_meeting_id_for_a_session_id_is_the_representative_member(tmp_path):
    write_metadata(tmp_path, "sys", session_id="s", audio_source="Zoom", start_time="2026-01-01T10:00:00", recording_part_index=0)
    write_metadata(tmp_path, "mic", session_id="s", audio_source="Microphone", start_time="2026-01-01T10:00:02", recording_part_index=0)
    assert meeting_id_for_session_key("s", root=tmp_path) == "mic"


def test_meeting_id_for_a_member_directory_key_resolves_to_the_representative(tmp_path):
    write_metadata(tmp_path, "sys", session_id="s", audio_source="Zoom", start_time="2026-01-01T10:00:00", recording_part_index=0)
    write_metadata(tmp_path, "mic", session_id="s", audio_source="Microphone", start_time="2026-01-01T10:00:02", recording_part_index=0)
    assert meeting_id_for_session_key("sys", root=tmp_path) == "mic"


def test_meeting_id_is_none_for_unknown_blank_or_path_like_keys(tmp_path):
    write_metadata(tmp_path, "solo", start_time="2026-01-01T10:00:00")
    assert meeting_id_for_session_key("ghost", root=tmp_path) is None
    assert meeting_id_for_session_key("", root=tmp_path) is None
    assert meeting_id_for_session_key("   ", root=tmp_path) is None
    assert meeting_id_for_session_key("..", root=tmp_path) is None
    assert meeting_id_for_session_key("../solo", root=tmp_path) is None
    assert meeting_id_for_session_key("solo", root=tmp_path / "missing-root") is None


def test_meeting_id_ignores_a_directory_without_readable_metadata(tmp_path):
    (tmp_path / "bare").mkdir()
    (tmp_path / "bare" / "metadata.json").write_text("not json", encoding="utf-8")
    assert meeting_id_for_session_key("bare", root=tmp_path) is None


def test_global_settings_default_roundtrip_and_corruption(tmp_path):
    store = CompanionGlobalSettingsStore(tmp_path / "config" / "settings.json")
    assert store.load() == CompanionGlobalSettings()
    store.save(CompanionGlobalSettings(auto_enable=True, default_mode="passive"))
    assert store.load().auto_enable is True and store.load().default_mode == "passive"
    store.path.write_text("[1,2]", encoding="utf-8")
    assert store.load() == CompanionGlobalSettings()
    store.path.write_text(json.dumps({"default_mode": "bogus"}), encoding="utf-8")
    assert store.load() == CompanionGlobalSettings()


def test_global_settings_default_path_follows_home(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert CompanionGlobalSettingsStore().path == tmp_path / ".basil" / "config" / "meeting_companion_settings.json"
