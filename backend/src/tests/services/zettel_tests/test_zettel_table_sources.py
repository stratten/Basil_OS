"""find_uncarded projection, stamping, and finalize context for table sources."""

from api.services.zettel.sources.configs import (
    AGENT_TASK_CONFIG,
    SCHEDULED_RUN_CONFIG,
    build_table_sources,
)
from api.services.zettel.sources.table_source import TableZettelSource


def _insert_task(conn, task_id, status, *, prompt="p", **cols):
    columns = ["id", "timestamp", "original_prompt", "transcribed_prompt", "status",
               "created_at", "updated_at"]
    values = [task_id, "2026-07-24 10:00:00", prompt, prompt, status,
              "2026-07-24 10:00:00", "2026-07-24 10:05:00"]
    for name, value in cols.items():
        columns.append(name)
        values.append(value)
    placeholders = ",".join("?" * len(values))
    conn.execute(
        f"INSERT INTO agent_tasks ({', '.join(columns)}) VALUES ({placeholders})",
        values,
    )


def test_uncarded_rows_are_found_and_stamped(conn):
    _insert_task(conn, "t1", "completed")
    source = TableZettelSource(AGENT_TASK_CONFIG)
    drafts = source.find_uncarded(conn, since_iso=None, limit=10)
    assert [d.source_id for d in drafts] == ["t1"]

    source.stamp(conn, drafts[0], "agent_task:t1")
    assert conn.execute("SELECT zettel_id FROM agent_tasks WHERE id='t1'").fetchone()[0] == (
        "agent_task:t1"
    )
    # Once stamped, the row is no longer uncarded.
    assert source.find_uncarded(conn, since_iso=None, limit=10) == []


def test_since_iso_excludes_older_rows(conn):
    _insert_task(conn, "old", "completed")  # timestamp 2026-07-24 10:00:00
    source = TableZettelSource(AGENT_TASK_CONFIG)
    assert source.find_uncarded(conn, since_iso="2026-07-25T00:00:00+00:00", limit=10) == []
    assert len(source.find_uncarded(conn, since_iso="2026-07-01T00:00:00+00:00", limit=10)) == 1


def test_outcome_maps_from_status(conn):
    _insert_task(conn, "t2", "completed")
    draft = TableZettelSource(AGENT_TASK_CONFIG).find_uncarded(conn, since_iso=None, limit=10)[0]
    assert draft.outcome == "succeeded"


def test_agent_task_context_includes_result_data(conn):
    _insert_task(conn, "t3", "completed", result_data='{"answer": 42}')
    source = TableZettelSource(AGENT_TASK_CONFIG)
    context = source.gather_context(conn, ["t3"])
    assert "result_data" in context["t3"]
    assert context["t3"]["result_data"] == '{"answer": 42}'


def test_successful_scheduled_run_resolves_through_to_its_task(conn):
    _insert_task(conn, "task-1", "completed", result_data='{"did": "work"}', title="Nightly job")
    conn.execute(
        "INSERT INTO scheduled_agent_tasks (id, title, agent_task_text, schedule_type, "
        "schedule_config) VALUES ('s1', 't', 'x', 'one_time', '{}')"
    )
    conn.execute(
        "INSERT INTO scheduled_agent_task_runs (id, scheduled_agent_task_id, agent_task_id, "
        "scheduled_for, status, created_at) VALUES ('r1', 's1', 'task-1', "
        "'2026-07-24 09:00:00', 'completed', '2026-07-24 09:00:00')"
    )
    context = TableZettelSource(SCHEDULED_RUN_CONFIG).gather_context(conn, ["r1"])
    assert context["r1"]["result_data"] == '{"did": "work"}'
    assert context["r1"]["task_title"] is not None


def test_every_source_finds_nothing_on_empty_tables(conn):
    sources = build_table_sources()
    assert [source.source_kind for source in sources] == [
        "agent_task",
        "transcription",
        "assistant_output",
        "scheduled_run",
    ]
    for source in sources:
        assert source.find_uncarded(conn, since_iso=None, limit=10) == []


def test_bounds_are_enforced_on_projected_text(conn):
    _insert_task(conn, "t5", "completed", prompt="p" * 900, title="z" * 900)
    draft = TableZettelSource(AGENT_TASK_CONFIG).find_uncarded(conn, since_iso=None, limit=10)[0]
    assert len(draft.bounded_title()) <= 200
    summary = draft.bounded_summary()
    assert summary is None or len(summary) <= 500
