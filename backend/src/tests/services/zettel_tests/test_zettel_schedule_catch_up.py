"""Catch-up of missed scheduled runs: the durable ledger, the loop's wake-aware waiting, and the narrative scheduler's missed-slot rule."""

import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

from api.services.zettel import schedule_ledger
from api.services.zettel.daily_loop import DailyLoopScheduler, previous_daily_run
from api.services.zettel.narrative_scheduler import LEDGER_NAME, ZettelNarrativeScheduler


def test_previous_daily_run_picks_the_latest_slot_not_in_the_future():
    now = datetime(2026, 11, 5, 12, 0, 0)
    assert previous_daily_run("02:00", now) == datetime(2026, 11, 5, 2, 0)
    assert previous_daily_run("15:00", now) == datetime(2026, 11, 4, 15, 0)
    assert previous_daily_run("12:00", now) == datetime(2026, 11, 5, 12, 0)
    assert previous_daily_run("not-a-time", now) == datetime(2026, 11, 5, 3, 0)


def test_ledger_round_trips_and_keeps_other_entries():
    assert schedule_ledger.read_last_completed("a") is None
    first = datetime(2026, 11, 5, 4, 11, 0)
    schedule_ledger.record_completed("a", first)
    schedule_ledger.record_completed("b", first + timedelta(hours=1))
    assert schedule_ledger.read_last_completed("a") == first
    assert schedule_ledger.read_last_completed("b") == first + timedelta(hours=1)


def test_corrupt_or_malformed_ledger_reads_as_never_completed(tmp_path):
    path = schedule_ledger.ledger_path()
    path.write_text("{not json", encoding="utf-8")
    assert schedule_ledger.read_last_completed("a") is None
    path.write_text("[1, 2]", encoding="utf-8")
    assert schedule_ledger.read_last_completed("a") is None
    path.write_text('{"a": "yesterday-ish"}', encoding="utf-8")
    assert schedule_ledger.read_last_completed("a") is None
    schedule_ledger.record_completed("a", datetime(2026, 11, 5, 4, 0, 0))
    assert schedule_ledger.read_last_completed("a") == datetime(2026, 11, 5, 4, 0, 0)


def test_unwritable_ledger_does_not_raise(tmp_path, monkeypatch):
    blocker = tmp_path / "blocker"
    blocker.write_text("a file where a directory is needed", encoding="utf-8")
    monkeypatch.setattr(schedule_ledger, "ledger_path", lambda: blocker / "scheduler_ledger.json")
    schedule_ledger.record_completed("a", datetime(2026, 11, 5, 4, 0, 0))
    assert schedule_ledger.read_last_completed("a") is None


def _far_future():
    return datetime.now() + timedelta(hours=1)


def _run_loop(loop: DailyLoopScheduler, seconds: float, during=None):
    async def scenario():
        await loop.start()
        if during is not None:
            await during(loop)
        await asyncio.sleep(seconds)
        await loop.stop()

    asyncio.run(scenario())


def test_a_missed_run_is_caught_up_immediately_on_start_and_only_once():
    runs = []
    pending = [True]

    async def run_once():
        runs.append(datetime.now())
        pending[0] = False
        return None

    loop = DailyLoopScheduler(
        name="catch-up", run_once=run_once, next_run_at=_far_future,
        catch_up_due=lambda: pending[0], wake_poll_seconds=0.01, catch_up_retry_seconds=0.0,
    )
    _run_loop(loop, 0.2)
    assert len(runs) == 1


def test_nothing_runs_when_no_run_was_missed():
    runs = []

    async def run_once():
        runs.append(1)
        return None

    loop = DailyLoopScheduler(
        name="no-catch-up", run_once=run_once, next_run_at=_far_future,
        catch_up_due=lambda: False, wake_poll_seconds=0.01,
    )
    _run_loop(loop, 0.1)
    assert runs == []


def test_an_incomplete_catch_up_is_throttled_instead_of_hot_looping():
    runs = []

    async def run_once():
        runs.append(1)
        return None

    loop = DailyLoopScheduler(
        name="throttled", run_once=run_once, next_run_at=_far_future,
        catch_up_due=lambda: True, wake_poll_seconds=0.01, catch_up_retry_seconds=1000.0,
    )
    _run_loop(loop, 0.2)
    assert len(runs) == 1


def test_an_incomplete_catch_up_is_retried_after_the_retry_interval():
    runs = []

    async def run_once():
        runs.append(1)
        return None

    loop = DailyLoopScheduler(
        name="retried", run_once=run_once, next_run_at=_far_future,
        catch_up_due=lambda: True, wake_poll_seconds=0.01, catch_up_retry_seconds=0.05,
    )
    _run_loop(loop, 0.4)
    assert len(runs) >= 3


def test_a_failing_catch_up_check_does_not_break_the_loop():
    runs = []

    async def run_once():
        runs.append(1)
        return None

    def explode():
        raise RuntimeError("ledger exploded")

    loop = DailyLoopScheduler(
        name="explodes", run_once=run_once, next_run_at=_far_future,
        catch_up_due=explode, wake_poll_seconds=0.01,
    )

    async def during(running):
        await asyncio.sleep(0.05)
        running.kick()

    _run_loop(loop, 0.1, during=during)
    assert len(runs) >= 1


def test_the_loop_notices_a_wall_clock_jump_past_the_slot_without_waiting_it_out():
    """A sleeping Mac stops monotonic timers but not the wall clock; short polls re-read the clock, so the slot is honored on wake."""
    runs = []
    offset = [timedelta(0)]

    async def run_once():
        runs.append(1)
        return None

    def clock():
        return datetime.now() + offset[0]

    slot = datetime.now() + timedelta(hours=1)
    loop = DailyLoopScheduler(
        name="wake", run_once=run_once,
        # Like the real schedule, the next slot after a served one is in the future.
        next_run_at=lambda: slot if not runs else clock() + timedelta(hours=1),
        wake_poll_seconds=0.01, clock=clock,
    )

    async def during(running):
        await asyncio.sleep(0.05)
        assert runs == []
        offset[0] = timedelta(hours=2)

    _run_loop(loop, 0.2, during=during)
    assert len(runs) >= 1


def test_kick_still_runs_a_pass():
    runs = []

    async def run_once():
        runs.append(1)
        return None

    loop = DailyLoopScheduler(
        name="kick", run_once=run_once, next_run_at=_far_future, wake_poll_seconds=0.01,
    )

    async def during(running):
        await asyncio.sleep(0.03)
        running.kick()

    _run_loop(loop, 0.1, during=during)
    assert len(runs) >= 1


def _scheduler_with(settings: SimpleNamespace) -> ZettelNarrativeScheduler:
    scheduler = ZettelNarrativeScheduler()
    scheduler._settings = lambda: settings
    return scheduler


def _scheduled_an_hour_ago():
    return (datetime.now() - timedelta(hours=1)).strftime("%H:%M")


def test_narrative_catch_up_is_due_when_no_pass_ever_completed():
    scheduler = _scheduler_with(SimpleNamespace(narrative_enabled=True, narrative_mode="scheduled", narrative_scheduled_time=_scheduled_an_hour_ago()))
    assert scheduler._missed_scheduled_run() is True


def test_narrative_catch_up_is_due_when_the_last_pass_predates_the_latest_slot():
    time_text = _scheduled_an_hour_ago()
    scheduler = _scheduler_with(SimpleNamespace(narrative_enabled=True, narrative_mode="scheduled", narrative_scheduled_time=time_text))
    slot = previous_daily_run(time_text)
    schedule_ledger.record_completed(LEDGER_NAME, slot - timedelta(minutes=30))
    assert scheduler._missed_scheduled_run() is True


def test_narrative_catch_up_is_not_due_once_the_slot_was_served():
    time_text = _scheduled_an_hour_ago()
    scheduler = _scheduler_with(SimpleNamespace(narrative_enabled=True, narrative_mode="scheduled", narrative_scheduled_time=time_text))
    schedule_ledger.record_completed(LEDGER_NAME, previous_daily_run(time_text) + timedelta(minutes=1))
    assert scheduler._missed_scheduled_run() is False


def test_narrative_catch_up_is_off_when_disabled_or_continuous():
    time_text = _scheduled_an_hour_ago()
    disabled = _scheduler_with(SimpleNamespace(narrative_enabled=False, narrative_mode="scheduled", narrative_scheduled_time=time_text))
    continuous = _scheduler_with(SimpleNamespace(narrative_enabled=True, narrative_mode="continuous", narrative_scheduled_time=time_text))
    assert disabled._missed_scheduled_run() is False
    assert continuous._missed_scheduled_run() is False


def _run_scheduler_once_with(monkeypatch, completed: bool):
    fake_enricher = SimpleNamespace(
        run_pass=AsyncMock(
            return_value=SimpleNamespace(finalized=0, still_open=3, failed=0, discarded=0, completed=completed, errors=[])
        )
    )
    monkeypatch.setattr("api.services.zettel.narrative.enricher.get_zettel_enricher", lambda: fake_enricher)
    scheduler = _scheduler_with(SimpleNamespace(narrative_enabled=True, narrative_mode="scheduled", narrative_scheduled_time="02:00", narrative_model=""))
    asyncio.run(scheduler._run_once())


def test_a_completed_pass_is_recorded_in_the_ledger(monkeypatch):
    assert schedule_ledger.read_last_completed(LEDGER_NAME) is None
    _run_scheduler_once_with(monkeypatch, completed=True)
    assert schedule_ledger.read_last_completed(LEDGER_NAME) is not None


def test_an_incomplete_pass_is_not_recorded_so_catch_up_stays_due(monkeypatch):
    _run_scheduler_once_with(monkeypatch, completed=False)
    assert schedule_ledger.read_last_completed(LEDGER_NAME) is None
