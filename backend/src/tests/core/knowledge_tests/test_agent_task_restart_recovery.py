"""Regression coverage for backend-startup Agent Task interruption (unchanged by Package 4C.1)."""

from __future__ import annotations

import pytest

from api.core.knowledge.sqlite.sqlite_knowledge_service import SQLiteKnowledgeService

_ACTIVE_STATUSES = ("routing", "processing", "awaiting_user_input", "capturing")


@pytest.mark.asyncio
async def test_each_active_status_is_marked_failed_with_recorded_previous_status(tmp_path) -> None:
    service = SQLiteKnowledgeService(tmp_path / "db.sqlite3")
    for status in _ACTIVE_STATUSES:
        await service.store_agent_task(
            agent_task_id=f"task-{status}",
            original_prompt="Prompt",
            transcribed_prompt="Prompt",
            status=status,
        )

    interrupted_count = await service.agent_task_service.mark_interrupted_active_agent_tasks()

    assert interrupted_count == len(_ACTIVE_STATUSES)
    for status in _ACTIVE_STATUSES:
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
