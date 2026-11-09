"""The change journal: durable, capped, and tolerant of a damaged file."""

from api.services.app_control.journal import MAX_JOURNAL_ENTRIES, ChangeJournal


def _record(journal, key="appearance.text_scale"):
    return journal.record(
        agent_task_id="task-1",
        reason="because",
        approved_by_user=False,
        changes=[{"key": key, "label": "Text size", "before_raw": 1.0, "after_raw": 1.25, "before": 1.0, "after": 1.25}],
    )


def test_a_record_survives_reopening_the_file(tmp_path):
    path = tmp_path / "j.json"
    entry = _record(ChangeJournal(path))
    reopened = ChangeJournal(path)
    assert reopened.get(entry["id"])["changes"][0]["after_raw"] == 1.25
    assert reopened.latest_undoable()["id"] == entry["id"]


def test_a_damaged_file_reads_as_empty_and_can_be_written_again(tmp_path):
    path = tmp_path / "j.json"
    path.write_text("{not json", encoding="utf-8")
    journal = ChangeJournal(path)
    assert journal.recent(5) == []
    assert journal.latest_undoable() is None
    _record(journal)
    assert len(journal.recent(5)) == 1


def test_the_journal_is_capped(tmp_path):
    journal = ChangeJournal(tmp_path / "j.json")
    for _ in range(MAX_JOURNAL_ENTRIES + 5):
        _record(journal)
    assert len(journal.recent(10_000)) == MAX_JOURNAL_ENTRIES


def test_undone_entries_are_skipped_and_counts_use_the_window(tmp_path):
    journal = ChangeJournal(tmp_path / "j.json")
    first = _record(journal)
    second = _record(journal)
    assert journal.mark_undone(second["id"])
    assert journal.latest_undoable()["id"] == first["id"]
    assert journal.count_since(60) == 2
    assert journal.count_since(60, now=first["at_epoch"] + 3600) == 0
    assert journal.mark_undone("missing") is False
