"""Regression coverage for automatic work-session closeout on terminal agent-task status."""

from __future__ import annotations

import pytest

from api.core.knowledge.sqlite.sqlite_knowledge_service import SQLiteKnowledgeService


@pytest.mark.asyncio
async def test_terminal_completed_status_settles_a_still_active_work_session(tmp_path) -> None:
    service = SQLiteKnowledgeService(tmp_path / "db.sqlite3")
    await service.store_agent_task(
        agent_task_id="task-1",
        original_prompt="Prompt",
        transcribed_prompt="Prompt",
        status="processing",
    )
    session = await service.agent_work_session_repository.create_session(
        goal="Investigate the script",
        collection_type="investigation",
        agent_task_id="task-1",
        root_task_id="task-1",
    )

    await service.agent_task_service.update_agent_task_status(
        agent_task_id="task-1",
        status="completed",
        result_data={"message": "done"},
    )

    settled = await service.agent_work_session_repository.get_session(session["id"])
    assert settled["status"] == "completed"
    assert settled["finished_at"] is not None


@pytest.mark.asyncio
async def test_failed_status_settles_the_work_session_as_partial(tmp_path) -> None:
    service = SQLiteKnowledgeService(tmp_path / "db.sqlite3")
    await service.store_agent_task(
        agent_task_id="task-2",
        original_prompt="Prompt",
        transcribed_prompt="Prompt",
        status="processing",
    )
    session = await service.agent_work_session_repository.create_session(
        goal="Investigate the script",
        collection_type="investigation",
        agent_task_id="task-2",
        root_task_id="task-2",
    )

    await service.agent_task_service.update_agent_task_status(
        agent_task_id="task-2",
        status="failed",
        result_data={"message": "stopped"},
    )

    settled = await service.agent_work_session_repository.get_session(session["id"])
    assert settled["status"] == "partial"


@pytest.mark.asyncio
async def test_non_terminal_status_leaves_the_work_session_untouched(tmp_path) -> None:
    service = SQLiteKnowledgeService(tmp_path / "db.sqlite3")
    await service.store_agent_task(
        agent_task_id="task-3",
        original_prompt="Prompt",
        transcribed_prompt="Prompt",
        status="processing",
    )
    session = await service.agent_work_session_repository.create_session(
        goal="Investigate the script",
        collection_type="investigation",
        agent_task_id="task-3",
        root_task_id="task-3",
    )

    await service.agent_task_service.update_agent_task_status(
        agent_task_id="task-3",
        status="awaiting_user_input",
    )

    untouched = await service.agent_work_session_repository.get_session(session["id"])
    assert untouched["status"] == "active"
