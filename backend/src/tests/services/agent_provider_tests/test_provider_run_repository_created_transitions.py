"""Focused coverage for created-state provider-run transitions (Package 3A)."""

from __future__ import annotations

import pytest

from api.core.knowledge.sqlite.sqlite_knowledge_service import SQLiteKnowledgeService
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.providers.errors import (
    ProviderRunTransitionError,
)


async def _seed_profile_grant_task_and_run(
    service: SQLiteKnowledgeService,
    *,
    workspace_root: str,
    agent_task_id: str = "task-1",
) -> dict[str, object]:
    profile = await service.provider_profile_repository.create_profile(
        display_name="Fixture Provider",
        launch_argv=("fixture-acp", "--stdio"),
        environment_allowlist=("PATH",),
    )
    grant = await service.provider_profile_repository.grant_workspace(
        provider_profile_id=str(profile["id"]),
        canonical_workspace_root=workspace_root,
    )
    await service.store_agent_task(
        agent_task_id=agent_task_id,
        original_prompt="run provider",
        transcribed_prompt="run provider",
        status="routing",
        root_task_id=agent_task_id,
    )
    run = await service.provider_run_repository.create_run(
        agent_task_id=agent_task_id,
        root_task_id=agent_task_id,
        provider_profile_id=str(profile["id"]),
        workspace_grant_id=str(grant["id"]),
    )
    return run


@pytest.mark.asyncio
async def test_transition_run_allows_created_to_failed(tmp_path) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    service = SQLiteKnowledgeService(tmp_path / "provider_runs.db")
    run = await _seed_profile_grant_task_and_run(service, workspace_root=str(workspace_root))

    updated = await service.provider_run_repository.transition_run(
        provider_run_id=str(run["id"]),
        expected_revision=int(run["revision"]),
        next_status="failed",
        terminal_reason="boom",
    )

    assert updated["status"] == "failed"
    assert updated["terminal_reason"] == "boom"
    assert updated["terminal_at"] is not None


@pytest.mark.asyncio
async def test_transition_run_allows_created_to_canceled(tmp_path) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    service = SQLiteKnowledgeService(tmp_path / "provider_runs.db")
    run = await _seed_profile_grant_task_and_run(service, workspace_root=str(workspace_root))

    updated = await service.provider_run_repository.transition_run(
        provider_run_id=str(run["id"]),
        expected_revision=int(run["revision"]),
        next_status="canceled",
    )

    assert updated["status"] == "canceled"
    assert updated["terminal_at"] is not None


@pytest.mark.asyncio
async def test_transition_run_still_rejects_created_to_running_directly(tmp_path) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    service = SQLiteKnowledgeService(tmp_path / "provider_runs.db")
    run = await _seed_profile_grant_task_and_run(service, workspace_root=str(workspace_root))

    with pytest.raises(ProviderRunTransitionError):
        await service.provider_run_repository.transition_run(
            provider_run_id=str(run["id"]),
            expected_revision=int(run["revision"]),
            next_status="running",
        )
