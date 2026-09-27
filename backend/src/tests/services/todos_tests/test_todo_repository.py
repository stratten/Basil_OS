"""Direct TodoRepository coverage: creation/dedupe, read/list/cursor paging,
optimistic-concurrency updates, notes replace vs. workspace-note append, and
idempotency/source-uniqueness conflicts."""

import sqlite3
from pathlib import Path

import pytest

from api.services.todos.repository import (
    TodoIdempotencyConflict,
    TodoReferenceNotFound,
    TodoRepository,
    TodoRevisionConflict,
    TodoWorkspaceCursorError,
)


@pytest.fixture
def repo(tmp_path: Path) -> TodoRepository:
    return TodoRepository(str(tmp_path / "todos_repo.db"))


async def _create(repo: TodoRepository, **overrides):
    defaults = dict(
        title="Follow up with Alex", description="", notes="", responsibility="unspecified",
        priority="normal", due_at=None, status="open", created_by_kind="user", created_by_id=None,
        idempotency_key=None, idempotency_payload_hash=None, source_kind=None, source_id=None,
        source_locator=None, source_excerpt="",
    )
    defaults.update(overrides)
    return await repo.create_todo_item_with_source(**defaults)


@pytest.mark.asyncio
async def test_create_and_get_item_detail_round_trips(repo: TodoRepository) -> None:
    detail, created = await _create(repo, title="Draft the follow-up email")
    assert created is True
    assert detail.title == "Draft the follow-up email"
    assert detail.status == "open"
    assert detail.revision == 1
    assert detail.sources == []

    fetched = await repo.get_todo_item_detail(detail.id)
    assert fetched is not None
    assert fetched.id == detail.id
    assert fetched.title == detail.title


@pytest.mark.asyncio
async def test_get_item_detail_returns_none_for_missing_id(repo: TodoRepository) -> None:
    assert await repo.get_todo_item_detail("does-not-exist") is None


@pytest.mark.asyncio
async def test_create_with_source_records_provenance(repo: TodoRepository) -> None:
    detail, created = await _create(
        repo, source_kind="meeting_analysis_proposal", source_id="m1:f1:p1",
        source_locator={"meeting_id": "m1"}, source_excerpt="Follow up with Alex about launch",
    )
    assert created is True
    assert len(detail.sources) == 1
    assert detail.sources[0].source_kind == "meeting_analysis_proposal"
    assert detail.sources[0].source_id == "m1:f1:p1"
    assert detail.sources[0].source_locator == {"meeting_id": "m1"}


@pytest.mark.asyncio
async def test_create_with_duplicate_source_identity_returns_existing_without_creating_a_second_row(
    repo: TodoRepository,
) -> None:
    first, first_created = await _create(
        repo, source_kind="meeting_analysis_proposal", source_id="m1:f1:p1", source_excerpt="first",
    )
    second, second_created = await _create(
        repo, title="Different title, same source", source_kind="meeting_analysis_proposal",
        source_id="m1:f1:p1", source_excerpt="second",
    )
    assert first_created is True
    assert second_created is False
    assert second.id == first.id
    assert second.title == first.title  # the original row, not a new one


@pytest.mark.asyncio
async def test_find_todo_by_source_returns_the_linked_item(repo: TodoRepository) -> None:
    detail, _ = await _create(repo, source_kind="meeting_analysis_proposal", source_id="m2:f2:p2")
    found = await repo.find_todo_by_source(source_kind="meeting_analysis_proposal", source_id="m2:f2:p2")
    assert found is not None
    assert found.id == detail.id


@pytest.mark.asyncio
async def test_find_todo_by_source_returns_none_when_unmatched(repo: TodoRepository) -> None:
    assert await repo.find_todo_by_source(source_kind="meeting_analysis_proposal", source_id="nope") is None


@pytest.mark.asyncio
async def test_create_with_idempotency_key_returns_existing_row_on_matching_payload_hash(
    repo: TodoRepository,
) -> None:
    first, first_created = await _create(repo, idempotency_key="key-1", idempotency_payload_hash="hash-a")
    second, second_created = await _create(
        repo, title="Different title", idempotency_key="key-1", idempotency_payload_hash="hash-a",
    )
    assert first_created is True
    assert second_created is False
    assert second.id == first.id


@pytest.mark.asyncio
async def test_create_with_idempotency_key_conflict_on_mismatched_payload_hash_raises(
    repo: TodoRepository,
) -> None:
    await _create(repo, idempotency_key="key-2", idempotency_payload_hash="hash-a")
    with pytest.raises(TodoIdempotencyConflict):
        await _create(repo, idempotency_key="key-2", idempotency_payload_hash="hash-b")


@pytest.mark.asyncio
async def test_list_todo_item_summaries_filters_by_status_and_paginates(repo: TodoRepository) -> None:
    for i in range(3):
        await _create(repo, title=f"Open {i}", status="open")
    for i in range(2):
        await _create(repo, title=f"Done {i}", status="completed")

    open_items, cursor = await repo.list_todo_item_summaries(status="open", limit=50, cursor=None)
    assert len(open_items) == 3
    assert cursor is None

    page_one, next_cursor = await repo.list_todo_item_summaries(status=None, limit=2, cursor=None)
    assert len(page_one) == 2
    assert next_cursor is not None
    page_two, final_cursor = await repo.list_todo_item_summaries(status=None, limit=2, cursor=next_cursor)
    assert len(page_two) >= 1
    seen_ids = {item.id for item in page_one} | {item.id for item in page_two}
    assert len(seen_ids) == len(page_one) + len(page_two)  # no duplicate rows across pages


@pytest.mark.asyncio
async def test_list_todo_item_summaries_empty_result(repo: TodoRepository) -> None:
    items, cursor = await repo.list_todo_item_summaries(status="cancelled", limit=50, cursor=None)
    assert items == []
    assert cursor is None


@pytest.mark.asyncio
async def test_get_todo_workspace_hydration_reports_counts_by_status(repo: TodoRepository) -> None:
    await _create(repo, title="A", status="open")
    await _create(repo, title="B", status="open")
    await _create(repo, title="C", status="candidate")

    hydration = await repo.get_todo_workspace_hydration()
    assert hydration.counts_by_status.get("open") == 2
    assert hydration.counts_by_status.get("candidate") == 1
    assert len(hydration.items) == 3


@pytest.mark.asyncio
async def test_workspace_page_searches_titles_case_insensitively_and_treats_like_characters_literally(
    repo: TodoRepository,
) -> None:
    matching, _ = await _create(repo, title="Review 100%_\\ budget")
    await _create(repo, title="Review 100aa budget")
    await _create(repo, title="Unrelated task")

    page = await repo.get_todo_workspace_hydration(query="rEvIeW 100%_\\", limit=50)

    assert [item.id for item in page.items] == [matching.id]
    assert page.has_more is False
    assert page.next_cursor is None


@pytest.mark.asyncio
async def test_workspace_page_cursor_is_stable_for_each_sort_and_direction(repo: TodoRepository) -> None:
    first, _ = await _create(repo, title="Alpha", priority="low", due_at="2026-01-01T00:00:00Z")
    second, _ = await _create(repo, title="bravo", priority="normal", due_at="2026-01-02T00:00:00Z")
    third, _ = await _create(repo, title="Charlie", priority="high", due_at=None, status="completed")
    fourth, _ = await _create(repo, title="delta", priority="normal", due_at="2026-01-03T00:00:00Z")
    expected_ids = {first.id, second.id, third.id, fourth.id}

    for sort_by in ("created_at", "updated_at", "due_at", "title", "status", "priority"):
        for sort_direction in ("asc", "desc"):
            first_page = await repo.get_todo_workspace_hydration(
                limit=2,
                sort_by=sort_by,
                sort_direction=sort_direction,
            )
            assert first_page.has_more is True
            assert first_page.next_cursor is not None

            second_page = await repo.get_todo_workspace_hydration(
                limit=2,
                cursor=first_page.next_cursor,
                sort_by=sort_by,
                sort_direction=sort_direction,
            )
            assert second_page.has_more is False
            assert second_page.next_cursor is None
            listed_ids = [item.id for item in first_page.items + second_page.items]
            assert set(listed_ids) == expected_ids
            assert len(listed_ids) == len(set(listed_ids))


@pytest.mark.asyncio
async def test_workspace_page_places_undated_items_last_in_both_sort_directions(repo: TodoRepository) -> None:
    early, _ = await _create(repo, title="Early", due_at="2026-01-01T00:00:00Z")
    late, _ = await _create(repo, title="Late", due_at="2026-01-02T00:00:00Z")
    undated, _ = await _create(repo, title="Undated", due_at=None)

    ascending = await repo.get_todo_workspace_hydration(sort_by="due_at", sort_direction="asc", limit=50)
    descending = await repo.get_todo_workspace_hydration(sort_by="due_at", sort_direction="desc", limit=50)

    assert [item.id for item in ascending.items] == [early.id, late.id, undated.id]
    assert [item.id for item in descending.items] == [late.id, early.id, undated.id]


@pytest.mark.asyncio
async def test_workspace_page_rejects_malformed_or_mismatched_cursors(repo: TodoRepository) -> None:
    await _create(repo, title="One")
    await _create(repo, title="Two")
    first_page = await repo.get_todo_workspace_hydration(limit=1)

    with pytest.raises(TodoWorkspaceCursorError, match="Invalid To-Do workspace cursor"):
        await repo.get_todo_workspace_hydration(cursor="not-a-cursor")
    with pytest.raises(TodoWorkspaceCursorError, match="Invalid To-Do workspace cursor"):
        await repo.get_todo_workspace_hydration(
            query="Two",
            cursor=first_page.next_cursor,
            limit=1,
        )


@pytest.mark.asyncio
async def test_update_with_expected_revision_succeeds_and_increments_revision(repo: TodoRepository) -> None:
    detail, _ = await _create(repo)
    updated = await repo.update_todo_item_with_expected_revision(
        todo_id=detail.id, expected_revision=1, fields={"status": "in_progress"},
        event_kind="worker_active", actor_kind="system", actor_id=None,
    )
    assert updated.status == "in_progress"
    assert updated.revision == 2


@pytest.mark.asyncio
async def test_update_with_stale_expected_revision_raises_conflict(repo: TodoRepository) -> None:
    detail, _ = await _create(repo)
    await repo.update_todo_item_with_expected_revision(
        todo_id=detail.id, expected_revision=1, fields={"status": "in_progress"},
        event_kind="worker_active", actor_kind="system", actor_id=None,
    )
    with pytest.raises(TodoRevisionConflict):
        await repo.update_todo_item_with_expected_revision(
            todo_id=detail.id, expected_revision=1,  # stale: already bumped to 2
            fields={"status": "completed"}, event_kind="completed", actor_kind="user", actor_id=None,
        )


@pytest.mark.asyncio
async def test_concurrent_revision_conflict_when_two_updates_race_on_the_same_expected_revision(
    repo: TodoRepository,
) -> None:
    """Both callers read revision=1 concurrently (e.g. a user edit and a
    worker-reconciliation write racing on the same To-Do); only one may win."""
    detail, _ = await _create(repo)

    async def attempt(status: str):
        try:
            return await repo.update_todo_item_with_expected_revision(
                todo_id=detail.id, expected_revision=1, fields={"status": status},
                event_kind="updated", actor_kind="user", actor_id=None,
            )
        except TodoRevisionConflict as exc:
            return exc

    import asyncio

    results = await asyncio.gather(attempt("in_progress"), attempt("cancelled"))
    successes = [r for r in results if not isinstance(r, TodoRevisionConflict)]
    conflicts = [r for r in results if isinstance(r, TodoRevisionConflict)]
    assert len(successes) == 1
    assert len(conflicts) == 1


@pytest.mark.asyncio
async def test_replace_notes_with_expected_revision_overwrites_existing_notes(repo: TodoRepository) -> None:
    detail, _ = await _create(repo, notes="original notes")
    updated = await repo.replace_todo_item_notes_with_expected_revision(
        todo_id=detail.id, notes="replaced notes", expected_revision=1, actor_kind="user", actor_id=None,
    )
    assert updated.notes == "replaced notes"
    assert updated.revision == 2


@pytest.mark.asyncio
async def test_replace_notes_with_stale_revision_raises_conflict(repo: TodoRepository) -> None:
    detail, _ = await _create(repo, notes="v1")
    await repo.replace_todo_item_notes_with_expected_revision(
        todo_id=detail.id, notes="v2", expected_revision=1, actor_kind="user", actor_id=None,
    )
    with pytest.raises(TodoRevisionConflict):
        await repo.replace_todo_item_notes_with_expected_revision(
            todo_id=detail.id, notes="v3", expected_revision=1, actor_kind="user", actor_id=None,
        )


@pytest.mark.asyncio
async def test_append_workspace_manager_note_appends_without_expected_revision(repo: TodoRepository) -> None:
    detail, _ = await _create(repo, notes="user's original note")
    updated = await repo.append_todo_item_note(
        todo_id=detail.id, note_markdown="Agent found the invoice attached to thread #42.",
        actor_kind="agent", actor_id="agent-task-1",
    )
    assert "user's original note" in updated.notes
    assert "Agent found the invoice attached to thread #42." in updated.notes
    assert updated.revision == 2


@pytest.mark.asyncio
async def test_append_workspace_manager_note_on_empty_notes_does_not_prefix_blank_lines(
    repo: TodoRepository,
) -> None:
    detail, _ = await _create(repo, notes="")
    updated = await repo.append_todo_item_note(
        todo_id=detail.id, note_markdown="First agent note.", actor_kind="agent", actor_id="agent-task-1",
    )
    assert updated.notes == "First agent note."


@pytest.mark.asyncio
async def test_append_workspace_manager_note_truncates_oversized_accumulated_notes(repo: TodoRepository) -> None:
    detail, _ = await _create(repo, notes="x" * 11990)
    updated = await repo.append_todo_item_note(
        todo_id=detail.id, note_markdown="y" * 100, actor_kind="agent", actor_id="agent-task-1",
    )
    assert len(updated.notes) == 12000
    assert updated.notes.endswith("y" * 100)


@pytest.mark.asyncio
async def test_append_workspace_manager_note_on_missing_todo_raises_value_error(repo: TodoRepository) -> None:
    with pytest.raises(ValueError):
        await repo.append_todo_item_note(
            todo_id="does-not-exist", note_markdown="note", actor_kind="agent", actor_id="agent-task-1",
        )


@pytest.mark.asyncio
async def test_append_todo_event_persists_a_standalone_audit_row(repo: TodoRepository) -> None:
    detail, _ = await _create(repo)
    await repo.append_todo_event(
        todo_id=detail.id, event_kind="worker_submission_failed", actor_kind="system", actor_id=None,
        payload={"error": "boom"},
    )
    # No public read API for todo_events; assert indirectly via a raw connection
    # scoped to this repository's own db_path (still fully isolated per-test).
    import sqlite3

    conn = sqlite3.connect(repo.db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT event_kind, payload_json FROM todo_events WHERE todo_id = ? AND event_kind = 'worker_submission_failed'",
        (detail.id,),
    ).fetchone()
    conn.close()
    assert row is not None
    assert "boom" in row["payload_json"]


@pytest.mark.asyncio
async def test_add_reference_persists_and_hydrates_the_path_with_a_revisioned_event(repo: TodoRepository) -> None:
    detail, _ = await _create(repo)

    updated = await repo.add_todo_reference_with_expected_revision(
        todo_id=detail.id,
        path="/tmp/project/brief.pdf",
        expected_revision=detail.revision,
        actor_kind="user",
        actor_id=None,
    )

    assert updated.revision == 2
    assert [reference.path for reference in updated.references] == ["/tmp/project/brief.pdf"]
    conn = sqlite3.connect(repo.db_path)
    row = conn.execute(
        "SELECT event_kind, payload_json FROM todo_events WHERE todo_id = ? ORDER BY created_at DESC LIMIT 1",
        (detail.id,),
    ).fetchone()
    conn.close()
    assert row == ("reference_added", '{"path": "/tmp/project/brief.pdf"}')


@pytest.mark.asyncio
async def test_add_reference_is_idempotent_per_todo_but_path_is_not_globally_unique(repo: TodoRepository) -> None:
    first, _ = await _create(repo, title="First")
    second, _ = await _create(repo, title="Second")
    first_updated = await repo.add_todo_reference_with_expected_revision(
        todo_id=first.id, path="/tmp/project/brief.pdf", expected_revision=first.revision, actor_kind="user", actor_id=None,
    )
    duplicate = await repo.add_todo_reference_with_expected_revision(
        todo_id=first.id, path="/tmp/project/brief.pdf", expected_revision=first_updated.revision, actor_kind="user", actor_id=None,
    )
    second_updated = await repo.add_todo_reference_with_expected_revision(
        todo_id=second.id, path="/tmp/project/brief.pdf", expected_revision=second.revision, actor_kind="user", actor_id=None,
    )

    assert duplicate.revision == first_updated.revision
    assert len(duplicate.references) == 1
    assert len(second_updated.references) == 1


@pytest.mark.asyncio
async def test_remove_reference_requires_current_revision_and_existing_reference(repo: TodoRepository) -> None:
    detail, _ = await _create(repo)
    added = await repo.add_todo_reference_with_expected_revision(
        todo_id=detail.id, path="/tmp/project/brief.pdf", expected_revision=detail.revision, actor_kind="user", actor_id=None,
    )

    with pytest.raises(TodoRevisionConflict):
        await repo.remove_todo_reference_with_expected_revision(
            todo_id=detail.id, reference_id=added.references[0].id, expected_revision=detail.revision,
            actor_kind="user", actor_id=None,
        )
    with pytest.raises(TodoReferenceNotFound):
        await repo.remove_todo_reference_with_expected_revision(
            todo_id=detail.id, reference_id="missing-reference", expected_revision=added.revision,
            actor_kind="user", actor_id=None,
        )

    removed = await repo.remove_todo_reference_with_expected_revision(
        todo_id=detail.id, reference_id=added.references[0].id, expected_revision=added.revision,
        actor_kind="user", actor_id=None,
    )
    assert removed.references == []
    assert removed.revision == 3
