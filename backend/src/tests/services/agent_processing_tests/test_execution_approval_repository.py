"""Execution approval repository lifecycle tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.agent_tasks.mutations.service import (
    AgentTaskMutations,
)
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.infrastructure.connection import (
    initialize_sqlite_database_mode,
    reset_sqlite_connection_state_for_tests,
)
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.execution_approvals.repository import (
    ExecutionApprovalConflictError,
    ExecutionApprovalRepository,
)
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.infrastructure.schema_manager import (
    SchemaManager,
)


@pytest.fixture
def temp_db_path(tmp_path: Path) -> str:
    reset_sqlite_connection_state_for_tests()
    db_path = str(tmp_path / "execution_approval.db")
    initialize_sqlite_database_mode(db_path)
    SchemaManager(db_path).initialize_db()
    return db_path


@pytest.fixture
def repository(temp_db_path: str) -> ExecutionApprovalRepository:
    return ExecutionApprovalRepository(temp_db_path)


@pytest.mark.asyncio
async def test_create_and_resolve_pending_execution_approval(
    repository: ExecutionApprovalRepository,
    temp_db_path: str,
) -> None:
    mutations = AgentTaskMutations(temp_db_path)
    task_id = "task-approval-1"
    await mutations.store_agent_task(
        agent_task_id=task_id,
        original_prompt="prompt",
        transcribed_prompt="prompt",
    )

    created = await repository.create_pending_approval(
        agent_task_id=task_id,
        root_task_id=task_id,
        execution_type="browser_foreground_control",
        command="ls",
        reason="Not whitelisted",
        risk_level="low",
        generalized_pattern="ls",
        render_context={"source": "shell_service"},
    )
    assert created["status"] == "pending"
    assert created["execution_type"] == "browser_foreground_control"

    pending = await repository.get_pending_approval_for_agent_task(task_id)
    assert pending is not None
    assert pending["id"] == created["id"]

    resolved = await repository.resolve_pending_approval(
        approval_id=str(created["id"]),
        agent_task_id=task_id,
        expected_revision=int(created["revision"]),
        approved=True,
    )
    assert resolved["status"] == "approved"
    assert await repository.get_pending_approval_for_agent_task(task_id) is None


@pytest.mark.asyncio
async def test_stale_revision_is_rejected(
    repository: ExecutionApprovalRepository,
    temp_db_path: str,
) -> None:
    mutations = AgentTaskMutations(temp_db_path)
    task_id = "task-approval-2"
    await mutations.store_agent_task(
        agent_task_id=task_id,
        original_prompt="prompt",
        transcribed_prompt="prompt",
    )
    created = await repository.create_pending_approval(
        agent_task_id=task_id,
        root_task_id=task_id,
        execution_type="shell",
        command="pwd",
        reason="Not whitelisted",
        risk_level="low",
        generalized_pattern="pwd",
        render_context={},
    )
    with pytest.raises(ExecutionApprovalConflictError):
        await repository.resolve_pending_approval(
            approval_id=str(created["id"]),
            agent_task_id=task_id,
            expected_revision=999,
            approved=True,
        )


@pytest.mark.asyncio
async def test_list_pending_approvals_preserves_order_and_resolves_by_id(
    repository: ExecutionApprovalRepository,
    temp_db_path: str,
) -> None:
    mutations = AgentTaskMutations(temp_db_path)
    task_id = "task-approval-set"
    await mutations.store_agent_task(
        agent_task_id=task_id,
        original_prompt="prompt",
        transcribed_prompt="prompt",
    )
    first = await repository.create_pending_approval(
        agent_task_id=task_id,
        root_task_id=task_id,
        execution_type="shell",
        command="pwd",
        reason="Not whitelisted",
        risk_level="low",
        generalized_pattern="pwd",
        render_context={},
    )
    second = await repository.create_pending_approval(
        agent_task_id=task_id,
        root_task_id=task_id,
        execution_type="shell",
        command="ls",
        reason="Not whitelisted",
        risk_level="low",
        generalized_pattern="ls",
        render_context={},
    )

    assert [
        approval["id"]
        for approval in await repository.list_pending_approvals_for_agent_task(task_id)
    ] == [first["id"], second["id"]]

    await repository.resolve_pending_approval(
        approval_id=str(first["id"]),
        agent_task_id=task_id,
        expected_revision=int(first["revision"]),
        approved=True,
    )

    assert [
        approval["id"]
        for approval in await repository.list_pending_approvals_for_agent_task(task_id)
    ] == [second["id"]]
    assert await repository.cancel_pending_approvals_for_tasks([task_id]) == 1
    assert await repository.list_pending_approvals_for_agent_task(task_id) == []
