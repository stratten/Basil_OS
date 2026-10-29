"""Coverage for the atomic claim that keeps a scheduled run from executing more than once.

On 2026-10-28 seven concurrent calls to ``execute_scheduled_run`` all read the run as 'scheduled' before any of them wrote 'running', so one run started seven agent tasks.
"""

from __future__ import annotations

import asyncio
import sqlite3
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from api.core.knowledge.sqlite.schema import get_schema_statements
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.scheduling.repository import (
    ScheduledAgentTaskRepository,
)
from api.services.scheduled_agent_tasks.scheduled_agent_task_service_components import (
    scheduled_run_execution as sre,
)


@pytest.fixture
def repository(tmp_path):
    path = str(tmp_path / "schedules.db")
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA foreign_keys = OFF")
    for statement in get_schema_statements():
        if "create table if not exists scheduled_agent_task" in statement.lower():
            connection.execute(statement)
    connection.commit()
    connection.close()
    return ScheduledAgentTaskRepository(path)


async def _make_run(repository) -> str:
    schedule = await repository.create_scheduled_agent_task(
        title="Check email",
        agent_task_text="Check my inbox",
        schedule_type="recurring",
        schedule_config={"mode": "interval", "minutes": 15},
        timezone="UTC",
        next_run_at=None,
    )
    run = await repository.create_scheduled_run(schedule["id"], "2026-10-28T20:22:00+00:00")
    return run["id"] if isinstance(run, dict) else run


def test_only_one_of_many_concurrent_claims_wins(repository):
    async def scenario():
        run_id = await _make_run(repository)
        results = await asyncio.gather(*[repository.claim_scheduled_run(run_id, "2026-10-28T20:22:00+00:00") for _ in range(7)])
        return run_id, results

    run_id, results = asyncio.run(scenario())

    assert results.count(True) == 1
    assert results.count(False) == 6
    stored = asyncio.run(repository.get_scheduled_run(run_id))
    assert stored["status"] == "running"
    assert stored["started_at"] == "2026-10-28T20:22:00+00:00"


@pytest.mark.parametrize("status", ["running", "canceled", "completed", "missed", "skipped"])
def test_a_run_that_is_no_longer_scheduled_cannot_be_claimed(repository, status):
    async def scenario():
        run_id = await _make_run(repository)
        await repository.update_scheduled_run(run_id, status=status)
        claimed = await repository.claim_scheduled_run(run_id, "2026-10-28T20:22:00+00:00")
        return run_id, claimed

    run_id, claimed = asyncio.run(scenario())

    assert claimed is False
    assert asyncio.run(repository.get_scheduled_run(run_id))["status"] == status


def test_claiming_an_unknown_run_returns_false(repository):
    assert asyncio.run(repository.claim_scheduled_run("no-such-run", "2026-10-28T20:22:00+00:00")) is False


@pytest.mark.asyncio
async def test_a_caller_that_loses_the_claim_starts_nothing(monkeypatch):
    submission_service = SimpleNamespace(process_agent_task_direct=AsyncMock(), broadcast=AsyncMock())
    monkeypatch.setattr("api.main.app", SimpleNamespace(state=SimpleNamespace(agent_task_submission_service=submission_service)))
    sleep_guard = AsyncMock()
    monkeypatch.setattr(sre, "_prevent_idle_system_sleep_for_scheduled_run", lambda **_kwargs: sleep_guard() or nullcontext())
    finalize = AsyncMock()
    monkeypatch.setattr(sre.scheduled_run_lifecycle, "finalize_run_after_execution", finalize)
    repo = SimpleNamespace(
        get_scheduled_run=AsyncMock(return_value={"status": "scheduled"}),
        get_scheduled_agent_task=AsyncMock(
            return_value={"is_active": True, "agent_task_text": "Check my inbox", "title": "Check email", "reference_paths": [], "model_id": None}
        ),
        update_scheduled_run=AsyncMock(),
        claim_scheduled_run=AsyncMock(return_value=False),
    )

    result = await sre.execute_scheduled_run(repo, SimpleNamespace(), "schedule-1", "run-1")

    assert result == {"success": False, "error": "Run already claimed"}
    submission_service.process_agent_task_direct.assert_not_awaited()
    sleep_guard.assert_not_called()
    finalize.assert_not_awaited()
    repo.update_scheduled_run.assert_not_awaited()
