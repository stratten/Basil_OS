"""Regression cover for the scheduler extraction."""

import asyncio
from datetime import datetime, timedelta

from api.services.memory.intelligence_scheduler import MemoryIntelligenceScheduler
from api.services.zettel.daily_loop import DailyLoopScheduler, next_daily_run


def test_next_daily_run_rolls_over_to_tomorrow():
    now = datetime.now()
    target = (now - timedelta(hours=1)).strftime("%H:%M")
    assert next_daily_run(target) > now


def test_invalid_time_falls_back_to_three_am():
    assert next_daily_run("not-a-time").hour == 3
    assert next_daily_run("99:99").hour == 3


def test_concurrent_runs_are_rejected():
    started = asyncio.Event()
    release = asyncio.Event()

    async def slow_run():
        started.set()
        await release.wait()
        return None

    loop = DailyLoopScheduler(
        name="test-loop", run_once=slow_run, next_run_at=lambda: datetime.now() + timedelta(hours=1)
    )

    async def scenario():
        first = asyncio.create_task(loop.run_now())
        await started.wait()
        second = await loop.run_now()
        release.set()
        await first
        return second

    assert "already running" in asyncio.run(scenario())


def test_memory_scheduler_skips_when_reconciliation_is_open(monkeypatch):
    scheduler = MemoryIntelligenceScheduler()
    monkeypatch.setattr(scheduler, "_is_reconciliation_active", lambda: True)
    result = asyncio.run(scheduler.run_now())
    assert result.errors and "reconciliation workspace is open" in result.errors[0]


def test_reconciliation_skip_is_not_reported_as_a_scheduler_error():
    """A routine skip must not make /health read 'error: Skipped...'."""
    scheduler = MemoryIntelligenceScheduler()
    scheduler._is_reconciliation_active = lambda: True
    asyncio.run(scheduler.run_now())
    assert scheduler.get_status().last_error is None


def test_rejected_run_now_does_not_return_the_previous_result(monkeypatch):
    """A second concurrent click must report a refusal, not stale counts."""
    from api.services.memory.post_task_evaluator_orchestrator import PostTaskEvaluatorResult

    scheduler = MemoryIntelligenceScheduler()
    scheduler._is_reconciliation_active = lambda: False
    started = asyncio.Event()
    release = asyncio.Event()

    async def slow_sweep():
        started.set()
        await release.wait()
        return PostTaskEvaluatorResult(memory_proposals_added=7)

    monkeypatch.setattr(
        "api.services.memory.intelligence_scheduler.get_post_task_evaluator_orchestrator",
        lambda: type("Stub", (), {"run_daily_sweep": staticmethod(slow_sweep)})(),
    )

    async def scenario():
        first = asyncio.create_task(scheduler.run_now())
        await started.wait()
        second = await scheduler.run_now()
        release.set()
        return await first, second

    first_result, second_result = asyncio.run(scenario())
    assert first_result.memory_proposals_added == 7
    assert second_result.memory_proposals_added == 0
    assert second_result.errors and "already running" in second_result.errors[0]


def test_failed_sweep_does_not_return_the_previous_result(monkeypatch):
    """A crashed sweep must surface the error, not the last good counts."""
    scheduler = MemoryIntelligenceScheduler()
    scheduler._is_reconciliation_active = lambda: False

    async def exploding_sweep():
        raise RuntimeError("evaluator exploded")

    monkeypatch.setattr(
        "api.services.memory.intelligence_scheduler.get_post_task_evaluator_orchestrator",
        lambda: type("Stub", (), {"run_daily_sweep": staticmethod(exploding_sweep)})(),
    )

    result = asyncio.run(scheduler.run_now())
    assert result.memory_proposals_added == 0
    assert result.errors and "evaluator exploded" in result.errors[0]


def test_memory_scheduler_status_surface_is_preserved():
    scheduler = MemoryIntelligenceScheduler()
    status = scheduler.get_status()
    for field in ("is_running", "is_running_now", "last_run_at", "last_error", "next_run_at"):
        assert hasattr(status, field)
