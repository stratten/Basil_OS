from pathlib import Path

from api.services.meeting_companion.event_log import CompanionEventLog
from api.services.meeting_companion.models import CompanionSettings
from api.services.meeting_companion.store import COMPANION_FILE_NAME, CompanionStore


def make_log(directory_holder, **overrides):
    return CompanionEventLog(
        session_key="s1",
        resolve_directory=lambda: directory_holder[0],
        settings_provider=lambda: CompanionSettings(enabled=True),
        wall_clock=lambda: "2026-01-01T00:00:00.000000Z",
        **overrides,
    )


def test_append_assigns_monotonic_seq_rounds_time_and_notifies(tmp_path):
    log = make_log([tmp_path])
    seen = []
    log.subscribe(seen.append)
    first = log.append("status", 1.23456, {"enabled": True})
    second = log.append("error", -5, {"code": "c", "message": "m"})
    assert (first.seq, second.seq) == (1, 2)
    assert first.meeting_time == 1.235 and second.meeting_time == 0.0
    assert [event.seq for event in seen] == [1, 2]
    assert log.last_seq() == 2 and [event.seq for event in log.events_since(1)] == [2]


def test_broken_subscriber_does_not_block_append(tmp_path):
    log = make_log([tmp_path])

    def broken(event):
        raise RuntimeError("boom")

    log.subscribe(broken)
    log.append("status", 0, {"enabled": True})
    assert log.last_seq() == 1


def test_flush_is_debounced_and_atomic(tmp_path):
    log = make_log([tmp_path], flush_interval_seconds=2.0)
    log.append("status", 0, {"enabled": True})
    assert log.flush_if_due(100.0) is True
    assert CompanionStore(tmp_path).load().events[0].seq == 1
    log.append("error", 1, {"code": "c", "message": "m"})
    assert log.flush_if_due(100.5) is False
    assert len(CompanionStore(tmp_path).load().events) == 1
    assert log.flush_if_due(102.5) is True
    assert len(CompanionStore(tmp_path).load().events) == 2
    assert log.flush() is False


def test_load_existing_restores_events_and_continues_sequence(tmp_path):
    first = make_log([tmp_path])
    first.append("status", 0, {"enabled": True})
    first.append("error", 1, {"code": "c", "message": "m"})
    first.flush()
    second = make_log([tmp_path])
    settings = second.load_existing([tmp_path / "missing", tmp_path])
    assert settings is not None and settings.enabled is True
    assert second.last_seq() == 2
    assert second.append("status", 2, {"enabled": False}).seq == 3


def test_anchor_change_moves_the_file(tmp_path):
    old_dir, new_dir = tmp_path / "sys", tmp_path / "mic"
    holder = [old_dir]
    log = make_log(holder)
    log.append("status", 0, {"enabled": True})
    log.flush()
    assert (old_dir / COMPANION_FILE_NAME).exists()
    holder[0] = new_dir
    log.append("error", 1, {"code": "c", "message": "m"})
    log.flush()
    assert (new_dir / COMPANION_FILE_NAME).exists()
    assert not (old_dir / COMPANION_FILE_NAME).exists()


def test_is_dirty_tracks_unsaved_state(tmp_path):
    log = make_log([tmp_path])
    assert log.is_dirty() is False
    log.append("status", 0, {"enabled": True})
    assert log.is_dirty() is True
    log.flush()
    assert log.is_dirty() is False
    log.mark_dirty()
    assert log.is_dirty() is True


def test_discard_prevents_any_further_write(tmp_path):
    log = make_log([tmp_path])
    log.append("status", 0, {"enabled": True})
    log.discard()
    assert log.is_dirty() is False
    assert log.flush() is False
    assert not (tmp_path / COMPANION_FILE_NAME).exists()


def test_failed_write_keeps_the_log_dirty(tmp_path, monkeypatch):
    log = make_log([tmp_path])
    log.append("status", 0, {"enabled": True})

    def failing_save(self, document):
        raise OSError("disk full")

    monkeypatch.setattr(CompanionStore, "save", failing_save)
    assert log.flush() is False
    monkeypatch.undo()
    assert log.flush() is True


def test_trim_drops_only_retrieval_events(tmp_path):
    log = make_log([tmp_path], max_events=3)
    log.append("status", 0, {"enabled": True})
    for index in range(4):
        log.append("retrieval", index, {"purpose": "prefetch", "queries": [], "hit_count": 0, "paths": [], "duration_ms": 1, "cache": "miss"})
    kinds = [event.kind for event in log.events()]
    assert kinds.count("status") == 1 and len(kinds) == 3
    log.append("error", 9, {"code": "c", "message": "m"})
    assert [event.kind for event in log.events()].count("error") == 1
