"""Chain settings are validated at the API boundary and read leniently from storage."""

import json
import sqlite3
from types import SimpleNamespace

import pytest

from api.core.knowledge.sqlite.schema import get_schema_statements
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.scheduling.repository import (
    ScheduledAgentTaskRepository,
)
from api.services.scheduled_agent_tasks.scheduled_agent_task_service_components import scheduled_run_lifecycle
from api.services.scheduled_agent_tasks.scheduled_agent_task_service_components.scheduled_chain_config import (
    ChainConfig,
    normalize_chain_config,
    parse_chain_config,
)


@pytest.fixture
def repository(tmp_path):
    path = str(tmp_path / "schedules.db")
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA foreign_keys = OFF")
    for statement in get_schema_statements():
        lowered = statement.lower()
        if "create table if not exists scheduled_agent_task" in lowered or "create table if not exists agent_tasks" in lowered:
            connection.execute(statement)
    connection.commit()
    connection.close()
    return ScheduledAgentTaskRepository(path)


def test_none_and_independent_normalize_to_independent():
    assert normalize_chain_config(None) == {"mode": "independent"}
    assert normalize_chain_config({"mode": "independent", "max_runs": 5}) == {"mode": "independent"}


def test_chained_requires_a_limit():
    with pytest.raises(ValueError, match="run limit, a time limit, or both"):
        normalize_chain_config({"mode": "chained"})


def test_chained_normalizes_limits_and_defaults_carry_over_on():
    assert normalize_chain_config({"mode": "Chained", "max_runs": "8", "max_age_minutes": 360}) == {
        "mode": "chained",
        "carry_over": True,
        "max_runs": 8,
        "max_age_minutes": 360,
    }
    assert normalize_chain_config({"mode": "chained", "max_age_minutes": 60, "carry_over": False}) == {
        "mode": "chained",
        "carry_over": False,
        "max_age_minutes": 60,
    }


@pytest.mark.parametrize(
    "raw",
    [
        "chained",
        {"mode": "sideways"},
        {"mode": "chained", "max_runs": 0},
        {"mode": "chained", "max_runs": -3},
        {"mode": "chained", "max_runs": 2.5},
        {"mode": "chained", "max_runs": True},
        {"mode": "chained", "max_runs": "many"},
        {"mode": "chained", "max_runs": 1001},
        {"mode": "chained", "max_age_minutes": 60 * 24 * 367},
        {"mode": "chained", "max_runs": 3, "carry_over": "yes"},
    ],
)
def test_malformed_chain_config_is_rejected(raw):
    with pytest.raises(ValueError):
        normalize_chain_config(raw)


def test_parse_is_lenient_for_stored_values():
    assert parse_chain_config(None) == ChainConfig()
    assert parse_chain_config("") == ChainConfig()
    assert parse_chain_config("{not json") == ChainConfig()
    assert parse_chain_config({"mode": "chained"}) == ChainConfig()
    parsed = parse_chain_config(json.dumps({"mode": "chained", "max_runs": 4}))
    assert parsed.is_chained and parsed.max_runs == 4 and parsed.max_age_minutes is None and parsed.carry_over is True


def test_repository_round_trips_chain_config_and_defaults_to_independent(repository):
    import asyncio

    async def scenario():
        plain = await repository.create_scheduled_agent_task(
            title="Plain", agent_task_text="x", schedule_type="recurring",
            schedule_config={"mode": "interval", "minutes": 30}, timezone="UTC", next_run_at=None,
        )
        chained = await repository.create_scheduled_agent_task(
            title="Chained", agent_task_text="x", schedule_type="recurring",
            schedule_config={"mode": "interval", "minutes": 30}, timezone="UTC", next_run_at=None,
            chain_config={"mode": "chained", "carry_over": True, "max_runs": 6},
        )
        updated = await repository.update_scheduled_agent_task(plain["id"], chain_config={"mode": "chained", "carry_over": False, "max_age_minutes": 90})
        untouched = await repository.update_scheduled_agent_task(plain["id"], title="Renamed")
        return plain, chained, updated, untouched

    plain, chained, updated, untouched = asyncio.run(scenario())
    assert plain["chain_config"] == {"mode": "independent"}
    assert chained["chain_config"] == {"carry_over": True, "max_runs": 6, "mode": "chained"}
    assert updated["chain_config"] == {"carry_over": False, "max_age_minutes": 90, "mode": "chained"}
    assert untouched["chain_config"] == updated["chain_config"]


def test_latest_chain_anchor_skips_runs_without_a_task_and_reports_archive_state(repository):
    import asyncio

    async def scenario():
        schedule = await repository.create_scheduled_agent_task(
            title="S", agent_task_text="x", schedule_type="recurring",
            schedule_config={"mode": "interval", "minutes": 30}, timezone="UTC", next_run_at=None,
        )
        sid = schedule["id"]
        with repository._get_connection() as conn:
            for task_id, root in (("root-1", None), ("turn-2", "root-1")):
                conn.execute(
                    "INSERT INTO agent_tasks (id, timestamp, original_prompt, transcribed_prompt, root_task_id, archived_at) VALUES (?, '2026-10-27 10:00:00', 'p', 'p', ?, ?)",
                    (task_id, root, "2026-10-27 12:00:00" if root is None else None),
                )
            conn.commit()
        first = await repository.create_scheduled_run(sid, "2026-10-27T10:00:00+00:00")
        second = await repository.create_scheduled_run(sid, "2026-10-27T10:30:00+00:00")
        third = await repository.create_scheduled_run(sid, "2026-10-27T11:00:00+00:00")
        current = await repository.create_scheduled_run(sid, "2026-10-27T11:30:00+00:00")
        ids = [r["id"] if isinstance(r, dict) else r for r in (first, second, third, current)]
        await repository.update_scheduled_run(ids[0], agent_task_id="root-1")
        await repository.update_scheduled_run(ids[1], agent_task_id="turn-2")
        await repository.update_scheduled_run(ids[2], status="skipped")
        return sid, ids, await repository.latest_chain_anchor(sid, ids[3]), await repository.latest_chain_anchor(sid, ids[0])

    sid, ids, anchor, only_older = asyncio.run(scenario())
    assert anchor == {"agent_task_id": "turn-2", "root_task_id": "root-1", "root_archived_at": "2026-10-27 12:00:00"}
    assert only_older is not None and only_older["agent_task_id"] == "turn-2"


def test_lifecycle_rejects_chaining_a_one_time_schedule():
    with pytest.raises(ValueError, match="one-time"):
        scheduled_run_lifecycle._validated_chain_config("one_time", {"mode": "chained", "max_runs": 3})
    assert scheduled_run_lifecycle._validated_chain_config("one_time", None) == {"mode": "independent"}
    assert scheduled_run_lifecycle._validated_chain_config("recurring", {"mode": "chained", "max_runs": 3})["mode"] == "chained"
