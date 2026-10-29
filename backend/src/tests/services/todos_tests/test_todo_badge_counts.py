"""Repository coverage for the Board rail badge counts: open-work statuses only, date-only due-day comparison, and
resilience to missing or malformed due dates."""

from pathlib import Path

import pytest

from api.services.todos.repository import TodoRepository


@pytest.fixture
def repo(tmp_path: Path) -> TodoRepository:
    return TodoRepository(str(tmp_path / "badge_counts.db"))


async def _create(repo: TodoRepository, *, status: str = "open", due_at=None, title: str = "Item"):
    detail, _created = await repo.create_todo_item_with_source(
        title=title, description="", notes="", responsibility="unspecified", priority="normal", due_at=due_at,
        status=status, created_by_kind="user", created_by_id=None, idempotency_key=None,
        idempotency_payload_hash=None, source_kind=None, source_id=None, source_locator=None, source_excerpt="",
    )
    return detail


@pytest.mark.asyncio
async def test_counts_are_zero_for_an_empty_database(repo: TodoRepository) -> None:
    counts = await repo.get_todo_badge_counts("2026-03-10")
    assert (counts.total, counts.due_today, counts.overdue) == (0, 0, 0)


@pytest.mark.asyncio
async def test_only_open_work_statuses_are_counted(repo: TodoRepository) -> None:
    for status in ("candidate", "open", "in_progress", "ready_for_review", "completed", "dismissed", "canceled"):
        await _create(repo, status=status, due_at="2026-03-01T00:00:00Z", title=status)

    counts = await repo.get_todo_badge_counts("2026-03-10")

    assert counts.total == 3
    assert counts.overdue == 3
    assert counts.due_today == 0


@pytest.mark.asyncio
async def test_due_today_and_overdue_use_the_calendar_day_not_the_instant(repo: TodoRepository) -> None:
    await _create(repo, due_at="2026-03-09T23:59:59Z", title="yesterday")
    await _create(repo, due_at="2026-03-10T00:00:00Z", title="today midnight")
    await _create(repo, due_at="2026-03-10T23:59:59Z", title="today late")
    await _create(repo, due_at="2026-03-11T00:00:00Z", title="tomorrow")
    await _create(repo, due_at=None, title="undated")

    counts = await repo.get_todo_badge_counts("2026-03-10")

    assert (counts.total, counts.due_today, counts.overdue) == (5, 2, 1)


@pytest.mark.asyncio
async def test_blank_or_truncated_due_dates_are_never_overdue(repo: TodoRepository) -> None:
    await _create(repo, due_at="", title="blank")
    await _create(repo, due_at="2026", title="truncated")

    counts = await repo.get_todo_badge_counts("2026-03-10")

    assert (counts.total, counts.due_today, counts.overdue) == (2, 0, 0)


@pytest.mark.asyncio
async def test_the_counts_follow_the_supplied_day(repo: TodoRepository) -> None:
    await _create(repo, due_at="2026-03-10T00:00:00Z")

    assert (await repo.get_todo_badge_counts("2026-03-10")).due_today == 1
    assert (await repo.get_todo_badge_counts("2026-03-11")).overdue == 1
    assert (await repo.get_todo_badge_counts("2026-03-09")).overdue == 0
