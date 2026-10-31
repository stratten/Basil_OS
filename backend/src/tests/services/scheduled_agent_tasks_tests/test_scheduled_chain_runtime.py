"""A chained schedule continues, rolls over, or skips depending on the state of its conversation."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from api.services.scheduled_agent_tasks.scheduled_agent_task_service_components import scheduled_chain_runtime as runtime

NOW = datetime(2026, 10, 29, 18, 0, tzinfo=timezone.utc)
SCHEDULE = {"id": "s1", "model_id": None, "chain_config": {"mode": "chained", "carry_over": True, "max_runs": 3, "max_age_minutes": 360}}


def _utc_naive(minutes_ago: float) -> datetime:
    # Stored task timestamps are naive UTC, as written by utc_now_naive_iso.
    return (NOW - timedelta(minutes=minutes_ago)).replace(tzinfo=None)


def _turn(task_id, *, minutes_ago, status="completed", scheduled=True, summary=None):
    return SimpleNamespace(
        id=task_id,
        status=status,
        timestamp=_utc_naive(minutes_ago),
        origin_type=runtime.SCHEDULED_ORIGIN_TYPE if scheduled else None,
        origin_id="s1" if scheduled else None,
        result_data={"summary_text": summary} if summary else {},
    )


def _plan(chain, *, schedule=SCHEDULE, anchor=None, archived=None):
    repo = SimpleNamespace(
        latest_chain_anchor=AsyncMock(
            return_value=anchor if anchor is not None else {"agent_task_id": "t", "root_task_id": "root", "root_archived_at": archived}
        )
    )
    db = SimpleNamespace(get_agent_task_chain=AsyncMock(return_value=chain))
    plan = asyncio.run(runtime.plan_chain_run(repo, db, schedule, run_id="r-now", now=NOW))
    return plan, repo, db


def test_independent_schedule_never_touches_the_database():
    repo = SimpleNamespace(latest_chain_anchor=AsyncMock())
    db = SimpleNamespace(get_agent_task_chain=AsyncMock())
    plan = asyncio.run(runtime.plan_chain_run(repo, db, {"id": "s1", "chain_config": {"mode": "independent"}}, run_id="r", now=NOW))
    assert plan == runtime.ChainPlan()
    repo.latest_chain_anchor.assert_not_awaited()
    db.get_agent_task_chain.assert_not_awaited()


def test_first_ever_run_starts_a_chain_without_a_handoff():
    repo = SimpleNamespace(latest_chain_anchor=AsyncMock(return_value=None))
    plan = asyncio.run(runtime.plan_chain_run(repo, SimpleNamespace(), SCHEDULE, run_id="r", now=NOW))
    assert plan.action == runtime.ACTION_START and plan.root_task_id is None and plan.handoff_block is None


def test_a_healthy_finished_chain_is_continued_on_its_root():
    plan, repo, db = _plan([_turn("root", minutes_ago=90, summary="one"), _turn("t2", minutes_ago=30, summary="two")])
    assert plan.action == runtime.ACTION_CONTINUE and plan.root_task_id == "root"
    db.get_agent_task_chain.assert_awaited_once_with("root")


@pytest.mark.parametrize("status", ["processing", "awaiting_user_input", "needs_clarification", "awaiting_approval", "pending"])
def test_a_chain_whose_latest_turn_is_not_finished_is_skipped(status):
    plan, _, _ = _plan([_turn("root", minutes_ago=90, summary="one"), _turn("t2", minutes_ago=30, status=status)])
    assert plan.action == runtime.ACTION_SKIP and plan.skip_reason == runtime.SKIP_REASON


def test_a_user_typed_turn_that_is_still_running_also_blocks_the_next_run():
    plan, _, _ = _plan([_turn("root", minutes_ago=90, summary="one"), _turn("u2", minutes_ago=10, status="processing", scheduled=False)])
    assert plan.action == runtime.ACTION_SKIP


@pytest.mark.parametrize("status", ["completed", "failed", "canceled"])
def test_terminal_statuses_allow_the_chain_to_continue(status):
    plan, _, _ = _plan([_turn("root", minutes_ago=90, summary="one"), _turn("t2", minutes_ago=30, status=status)])
    assert plan.action == runtime.ACTION_CONTINUE


def test_reaching_the_run_limit_starts_a_new_chain_carrying_the_last_result_over():
    chain = [_turn("root", minutes_ago=100, summary="first"), _turn("t2", minutes_ago=70, summary="second"), _turn("t3", minutes_ago=40, summary="third and latest")]
    plan, _, _ = _plan(chain)
    assert plan.action == runtime.ACTION_START and plan.root_task_id is None
    assert "limit of 3 runs" in plan.notice
    assert "PREVIOUS SCHEDULED CONVERSATION" in plan.handoff_block and "third and latest" in plan.handoff_block


def test_turns_typed_by_the_user_do_not_count_toward_the_run_limit():
    chain = [_turn("root", minutes_ago=100, summary="a"), _turn("u1", minutes_ago=90, scheduled=False), _turn("u2", minutes_ago=80, scheduled=False), _turn("t2", minutes_ago=70, summary="b"), _turn("u3", minutes_ago=60, scheduled=False)]
    plan, _, _ = _plan(chain)
    assert plan.action == runtime.ACTION_CONTINUE


def test_reaching_the_time_limit_starts_a_new_chain_and_names_the_limit():
    plan, _, _ = _plan([_turn("root", minutes_ago=361, summary="old"), _turn("t2", minutes_ago=30, summary="newer")])
    assert plan.action == runtime.ACTION_START and "limit of 6 hours" in plan.notice and "newer" in plan.handoff_block


def test_just_under_the_time_limit_keeps_the_chain():
    plan, _, _ = _plan([_turn("root", minutes_ago=359, summary="old")])
    assert plan.action == runtime.ACTION_CONTINUE


def test_turning_carry_over_off_starts_blank():
    schedule = {**SCHEDULE, "chain_config": {"mode": "chained", "carry_over": False, "max_runs": 1}}
    plan, _, _ = _plan([_turn("root", minutes_ago=10, summary="done")], schedule=schedule)
    assert plan.action == runtime.ACTION_START and plan.handoff_block is None and "limit of 1 run." in plan.notice


def test_rollover_wins_over_a_waiting_turn_so_an_abandoned_chain_cannot_trap_the_schedule():
    plan, _, _ = _plan([_turn("root", minutes_ago=400, summary="old report"), _turn("t2", minutes_ago=380, status="awaiting_user_input")])
    assert plan.action == runtime.ACTION_START and "old report" in plan.handoff_block


def test_a_chain_with_no_result_to_carry_over_starts_with_no_handoff():
    plan, _, _ = _plan([_turn("root", minutes_ago=400, status="failed")])
    assert plan.action == runtime.ACTION_START and plan.handoff_block is None


def test_an_archived_chain_starts_a_new_one():
    plan, _, db = _plan([_turn("root", minutes_ago=10, summary="x")], archived="2026-10-29 12:00:00")
    assert plan.action == runtime.ACTION_START
    db.get_agent_task_chain.assert_not_awaited()


def test_a_chain_that_no_longer_exists_starts_a_new_one():
    plan, _, _ = _plan([])
    assert plan.action == runtime.ACTION_START and plan.handoff_block is None


def test_a_lookup_failure_runs_independently_with_a_notice():
    repo = SimpleNamespace(latest_chain_anchor=AsyncMock(side_effect=RuntimeError("database is locked")))
    plan = asyncio.run(runtime.plan_chain_run(repo, SimpleNamespace(), SCHEDULE, run_id="r", now=NOW))
    assert plan.action == runtime.ACTION_INDEPENDENT and plan.notice == runtime.LOOKUP_FAILED_NOTICE


def test_a_huge_last_result_is_trimmed_to_the_handoff_budget():
    schedule = {**SCHEDULE, "chain_config": {"mode": "chained", "max_runs": 1}}
    plan, _, _ = _plan([_turn("root", minutes_ago=10, summary="x" * 60_000)], schedule=schedule)
    assert len(plan.handoff_block) < runtime.HANDOFF_DEFAULT_CHARS + 600


@pytest.mark.parametrize(
    ("minutes", "expected"),
    [(30, "30 minutes"), (60, "1 hour"), (360, "6 hours"), (1440, "1 day"), (10080, "7 days"), (90, "90 minutes")],
)
def test_age_limits_are_described_in_plain_units(minutes, expected):
    assert runtime.describe_age_limit(minutes) == expected
