"""Regression coverage for backend-startup Agent Task interruption (unchanged by Package 4C.1)."""

from __future__ import annotations

import sqlite3
from contextlib import closing

import pytest

from api.core.knowledge.sqlite.sqlite_knowledge_service import SQLiteKnowledgeService

_INTERRUPTED_STATUSES = ("routing", "processing", "capturing")


def _set_days_since_update(service: SQLiteKnowledgeService, task_id: str, days: int) -> None:
    with closing(sqlite3.connect(service.db_path)) as conn:
        conn.execute(
            "UPDATE agent_tasks SET updated_at = datetime('now', ?) WHERE id = ?",
            (f"-{days} days", task_id),
        )
        conn.commit()


@pytest.mark.asyncio
async def test_each_active_status_is_marked_failed_with_recorded_previous_status(tmp_path) -> None:
    service = SQLiteKnowledgeService(tmp_path / "db.sqlite3")
    for status in _INTERRUPTED_STATUSES:
        await service.store_agent_task(
            agent_task_id=f"task-{status}",
            original_prompt="Prompt",
            transcribed_prompt="Prompt",
            status=status,
        )

    interrupted_count = await service.agent_task_service.mark_interrupted_active_agent_tasks()

    assert interrupted_count == len(_INTERRUPTED_STATUSES)
    for status in _INTERRUPTED_STATUSES:
        refreshed = await service.get_agent_task(f"task-{status}")
        assert refreshed.status == "failed"
        failure_info = (refreshed.result_data or {}).get("failure_info")
        assert failure_info is not None
        assert failure_info["success"] is False
        assert failure_info["previous_status"] == status


@pytest.mark.asyncio
async def test_a_terminal_agent_task_is_left_untouched(tmp_path) -> None:
    service = SQLiteKnowledgeService(tmp_path / "db.sqlite3")
    await service.store_agent_task(
        agent_task_id="task-completed",
        original_prompt="Prompt",
        transcribed_prompt="Prompt",
        status="completed",
    )

    interrupted_count = await service.agent_task_service.mark_interrupted_active_agent_tasks()

    assert interrupted_count == 0
    refreshed = await service.get_agent_task("task-completed")
    assert refreshed.status == "completed"


@pytest.mark.asyncio
async def test_a_provider_targeted_agent_task_still_stuck_in_processing_is_marked_failed(
    tmp_path,
) -> None:
    """A provider-run coroutine that never reached its own except block still leaves
    the Agent Task in `processing`; this proves Package 4C.1 did not need to change
    this existing generic Agent Task reconciliation to cover provider-targeted tasks."""
    service = SQLiteKnowledgeService(tmp_path / "db.sqlite3")
    await service.store_agent_task(
        agent_task_id="task-provider",
        original_prompt="Prompt",
        transcribed_prompt="Prompt",
        status="processing",
    )

    interrupted_count = await service.agent_task_service.mark_interrupted_active_agent_tasks()

    assert interrupted_count == 1
    refreshed = await service.get_agent_task("task-provider")
    assert refreshed.status == "failed"


@pytest.mark.asyncio
async def test_waiting_provider_delegation_parent_is_preserved_for_bridge_reconciliation(
    tmp_path,
) -> None:
    service = SQLiteKnowledgeService(tmp_path / "waiting-delegation.db")
    await service.store_agent_task(
        agent_task_id="waiting-parent",
        original_prompt="Prompt",
        transcribed_prompt="Prompt",
        status="awaiting_provider_delegation",
    )

    interrupted_count = await service.agent_task_service.mark_interrupted_active_agent_tasks()

    assert interrupted_count == 0
    refreshed = await service.get_agent_task("waiting-parent")
    assert refreshed is not None
    assert refreshed.status == "awaiting_provider_delegation"


@pytest.mark.asyncio
async def test_restart_cancels_pending_approvals_owned_by_terminal_tasks(tmp_path) -> None:
    service = SQLiteKnowledgeService(tmp_path / "orphan-approvals.db")
    for task_id in ("task-done", "task-waiting"):
        await service.store_agent_task(
            agent_task_id=task_id,
            original_prompt="Prompt",
            transcribed_prompt="Prompt",
            status="processing",
        )
    approvals = {}
    for task_id in ("task-done", "task-waiting"):
        approvals[task_id] = await service.execution_approval_repository.create_pending_approval(
            agent_task_id=task_id,
            root_task_id=task_id,
            execution_type="shell",
            command="pwd",
            reason="Not whitelisted",
            risk_level="low",
            generalized_pattern="pwd",
            render_context={},
        )
    await service.update_agent_task_status(agent_task_id="task-done", status="completed")
    await service.update_agent_task_status(agent_task_id="task-waiting", status="awaiting_provider_delegation")

    await service.agent_task_service.mark_interrupted_active_agent_tasks()

    done_record = await service.execution_approval_repository.get_approval(str(approvals["task-done"]["id"]))
    waiting_record = await service.execution_approval_repository.get_approval(str(approvals["task-waiting"]["id"]))
    assert done_record["status"] == "canceled"
    assert waiting_record["status"] == "pending"


@pytest.mark.asyncio
async def test_recent_task_waiting_for_the_user_survives_restart(tmp_path) -> None:
    service = SQLiteKnowledgeService(tmp_path / "waiting-user.db")
    await service.store_agent_task(
        agent_task_id="waiting-user",
        original_prompt="Prompt",
        transcribed_prompt="Prompt",
        status="awaiting_user_input",
    )
    _set_days_since_update(service, "waiting-user", 6)

    interrupted_count = await service.agent_task_service.mark_interrupted_active_agent_tasks()

    assert interrupted_count == 0
    refreshed = await service.get_agent_task("waiting-user")
    assert refreshed.status == "awaiting_user_input"


@pytest.mark.asyncio
async def test_task_waiting_for_the_user_past_retention_expires_on_restart(tmp_path) -> None:
    service = SQLiteKnowledgeService(tmp_path / "stale-user.db")
    await service.store_agent_task(
        agent_task_id="stale-user",
        original_prompt="Prompt",
        transcribed_prompt="Prompt",
        status="awaiting_user_input",
    )
    _set_days_since_update(service, "stale-user", 8)

    interrupted_count = await service.agent_task_service.mark_interrupted_active_agent_tasks()

    assert interrupted_count == 1
    refreshed = await service.get_agent_task("stale-user")
    assert refreshed.status == "failed"
    failure_info = (refreshed.result_data or {}).get("failure_info")
    assert failure_info["previous_status"] == "awaiting_user_input"
    assert failure_info["error"].startswith("Task expired: Basil restarted")


@pytest.mark.asyncio
async def test_recent_paused_task_survives_restart(tmp_path) -> None:
    service = SQLiteKnowledgeService(tmp_path / "paused.db")
    await service.store_agent_task(
        agent_task_id="paused-task",
        original_prompt="Prompt",
        transcribed_prompt="Prompt",
        status="paused",
    )
    _set_days_since_update(service, "paused-task", 6)

    interrupted_count = await service.agent_task_service.mark_interrupted_active_agent_tasks()

    assert interrupted_count == 0
    refreshed = await service.get_agent_task("paused-task")
    assert refreshed.status == "paused"


@pytest.mark.asyncio
async def test_paused_task_past_retention_expires_on_restart(tmp_path) -> None:
    service = SQLiteKnowledgeService(tmp_path / "stale-paused.db")
    await service.store_agent_task(
        agent_task_id="stale-paused",
        original_prompt="Prompt",
        transcribed_prompt="Prompt",
        status="paused",
    )
    _set_days_since_update(service, "stale-paused", 8)

    interrupted_count = await service.agent_task_service.mark_interrupted_active_agent_tasks()

    assert interrupted_count == 1
    refreshed = await service.get_agent_task("stale-paused")
    assert refreshed.status == "failed"
    failure_info = (refreshed.result_data or {}).get("failure_info")
    assert failure_info["previous_status"] == "paused"
    assert "paused for more than" in failure_info["error"]


@pytest.mark.asyncio
async def test_restart_cancels_pending_approvals_of_a_preserved_waiting_task(tmp_path) -> None:
    service = SQLiteKnowledgeService(tmp_path / "waiting-approval.db")
    await service.store_agent_task(
        agent_task_id="waiting-approval",
        original_prompt="Prompt",
        transcribed_prompt="Prompt",
        status="processing",
    )
    approval = await service.execution_approval_repository.create_pending_approval(
        agent_task_id="waiting-approval",
        root_task_id="waiting-approval",
        execution_type="shell",
        command="pwd",
        reason="Not whitelisted",
        risk_level="low",
        generalized_pattern="pwd",
        render_context={},
    )
    await service.update_agent_task_status(agent_task_id="waiting-approval", status="awaiting_user_input")

    await service.agent_task_service.mark_interrupted_active_agent_tasks()

    refreshed = await service.get_agent_task("waiting-approval")
    approval_record = await service.execution_approval_repository.get_approval(str(approval["id"]))
    assert refreshed.status == "awaiting_user_input"
    assert approval_record["status"] == "canceled"


def _waiting_interaction_timeline(interaction_id: str = "approval-1") -> list:
    from api.services.agent_processing.lifecycle.runtime.user_interaction_timeline import (
        build_user_interaction_entry,
    )

    return [
        {"id": "step-1", "type": "step", "title": "Ran a command", "content": "Ran a command"},
        build_user_interaction_entry(
            interaction_id=interaction_id,
            kind="approval",
            prompt="Run sed -n 2p notes.txt?",
        ),
    ]


def _interaction_status(refreshed, interaction_id: str = "approval-1") -> str:
    entry = next(item for item in refreshed.execution_timeline if item["id"] == f"user_interaction_{interaction_id}")
    return entry["metadata"]["user_interaction"]["status"]


@pytest.mark.asyncio
async def test_startup_closes_waiting_interactions_on_finished_tasks(tmp_path) -> None:
    service = SQLiteKnowledgeService(tmp_path / "stale-waiting.db")
    for status in ("canceled", "failed", "completed"):
        await service.store_agent_task(
            agent_task_id=f"task-{status}",
            original_prompt="Prompt",
            transcribed_prompt="Prompt",
            status=status,
        )
        await service.agent_task_service.update_execution_timeline(
            f"task-{status}", _waiting_interaction_timeline()
        )

    await service.agent_task_service.mark_interrupted_active_agent_tasks()

    for status in ("canceled", "failed", "completed"):
        refreshed = await service.get_agent_task(f"task-{status}")
        assert refreshed.status == status
        assert _interaction_status(refreshed) == "canceled"
        assert refreshed.execution_timeline[0]["id"] == "step-1"
        assert [item["id"] for item in refreshed.execution_timeline][1] == "user_interaction_approval-1"


@pytest.mark.asyncio
async def test_startup_closes_the_waiting_interaction_of_a_task_it_interrupts(tmp_path) -> None:
    service = SQLiteKnowledgeService(tmp_path / "interrupted-waiting.db")
    await service.store_agent_task(
        agent_task_id="task-processing",
        original_prompt="Prompt",
        transcribed_prompt="Prompt",
        status="processing",
    )
    await service.agent_task_service.update_execution_timeline("task-processing", _waiting_interaction_timeline())

    await service.agent_task_service.mark_interrupted_active_agent_tasks()

    refreshed = await service.get_agent_task("task-processing")
    assert refreshed.status == "failed"
    assert _interaction_status(refreshed) == "canceled"


@pytest.mark.asyncio
async def test_startup_keeps_the_waiting_interaction_of_a_task_that_can_still_resume(tmp_path) -> None:
    service = SQLiteKnowledgeService(tmp_path / "resumable-waiting.db")
    await service.store_agent_task(
        agent_task_id="task-awaiting",
        original_prompt="Prompt",
        transcribed_prompt="Prompt",
        status="awaiting_user_input",
    )
    await service.agent_task_service.update_execution_timeline("task-awaiting", _waiting_interaction_timeline())

    await service.agent_task_service.mark_interrupted_active_agent_tasks()

    refreshed = await service.get_agent_task("task-awaiting")
    assert refreshed.status == "awaiting_user_input"
    assert _interaction_status(refreshed) == "waiting"


@pytest.mark.asyncio
async def test_startup_reconciliation_is_idempotent_and_ignores_malformed_timelines(tmp_path) -> None:
    service = SQLiteKnowledgeService(tmp_path / "idempotent-waiting.db")
    await service.store_agent_task(
        agent_task_id="task-canceled",
        original_prompt="Prompt",
        transcribed_prompt="Prompt",
        status="canceled",
    )
    await service.store_agent_task(
        agent_task_id="task-garbled",
        original_prompt="Prompt",
        transcribed_prompt="Prompt",
        status="canceled",
    )
    await service.agent_task_service.update_execution_timeline("task-canceled", _waiting_interaction_timeline())
    with closing(sqlite3.connect(service.db_path)) as conn:
        conn.execute("UPDATE agent_tasks SET execution_timeline = ? WHERE id = ?", ("not json user_interaction", "task-garbled"))
        conn.commit()

    await service.agent_task_service.mark_interrupted_active_agent_tasks()
    await service.agent_task_service.mark_interrupted_active_agent_tasks()

    refreshed = await service.get_agent_task("task-canceled")
    assert _interaction_status(refreshed) == "canceled"
    assert len([item for item in refreshed.execution_timeline if item["id"] == "user_interaction_approval-1"]) == 1
