"""Focused persistence tests for Package 5C.1's read-only profile-inventory accessors."""

from __future__ import annotations

import pytest

from api.core.knowledge.sqlite.sqlite_knowledge_service import SQLiteKnowledgeService


async def _seed_profile(
    service: SQLiteKnowledgeService, *, display_name: str = "Fixture Provider"
) -> dict[str, object]:
    return await service.provider_profile_repository.create_profile(
        display_name=display_name,
        launch_argv=("fixture-acp", "--stdio"),
        environment_allowlist=("PATH",),
    )


async def _seed_agent_tasks(
    service: SQLiteKnowledgeService,
    *,
    root_task_id: str = "root-task",
    agent_task_id: str = "agent-task",
) -> None:
    await service.store_agent_task(
        agent_task_id=root_task_id,
        original_prompt="Root prompt",
        transcribed_prompt="Root prompt",
        status="processing",
    )
    await service.store_agent_task(
        agent_task_id=agent_task_id,
        original_prompt="Child prompt",
        transcribed_prompt="Child prompt",
        status="processing",
        root_task_id=root_task_id,
        chain_sequence_number=1,
    )


@pytest.mark.asyncio
async def test_list_workspace_grants_for_profile_returns_only_active_grants_by_default(
    tmp_path,
) -> None:
    service = SQLiteKnowledgeService(tmp_path / "provider_runs.db")
    profile = await _seed_profile(service)
    active_grant = await service.provider_profile_repository.grant_workspace(
        provider_profile_id=str(profile["id"]),
        canonical_workspace_root=str(tmp_path / "workspace-a"),
    )
    revoked_grant = await service.provider_profile_repository.grant_workspace(
        provider_profile_id=str(profile["id"]),
        canonical_workspace_root=str(tmp_path / "workspace-b"),
    )
    await service.provider_profile_repository.revoke_workspace_grant(str(revoked_grant["id"]))

    grants = await service.provider_profile_repository.list_workspace_grants_for_profile(
        str(profile["id"])
    )

    assert [grant["id"] for grant in grants] == [active_grant["id"]]


@pytest.mark.asyncio
async def test_list_workspace_grants_for_profile_can_include_revoked_grants(tmp_path) -> None:
    service = SQLiteKnowledgeService(tmp_path / "provider_runs.db")
    profile = await _seed_profile(service)
    grant = await service.provider_profile_repository.grant_workspace(
        provider_profile_id=str(profile["id"]),
        canonical_workspace_root=str(tmp_path / "workspace"),
    )
    await service.provider_profile_repository.revoke_workspace_grant(str(grant["id"]))

    grants = await service.provider_profile_repository.list_workspace_grants_for_profile(
        str(profile["id"]), include_revoked=True
    )

    assert [g["id"] for g in grants] == [grant["id"]]


@pytest.mark.asyncio
async def test_list_workspace_grants_for_profile_returns_empty_for_a_profile_with_no_grants(
    tmp_path,
) -> None:
    service = SQLiteKnowledgeService(tmp_path / "provider_runs.db")
    profile = await _seed_profile(service)

    grants = await service.provider_profile_repository.list_workspace_grants_for_profile(
        str(profile["id"])
    )

    assert grants == []


@pytest.mark.asyncio
async def test_get_latest_run_for_profile_returns_none_when_no_run_exists(tmp_path) -> None:
    service = SQLiteKnowledgeService(tmp_path / "provider_runs.db")
    profile = await _seed_profile(service)

    run = await service.provider_run_repository.get_latest_run_for_profile(str(profile["id"]))

    assert run is None


@pytest.mark.asyncio
async def test_get_latest_run_for_profile_returns_the_most_recently_created_run(tmp_path) -> None:
    service = SQLiteKnowledgeService(tmp_path / "provider_runs.db")
    profile = await _seed_profile(service)
    grant = await service.provider_profile_repository.grant_workspace(
        provider_profile_id=str(profile["id"]),
        canonical_workspace_root=str(tmp_path / "workspace"),
    )
    await _seed_agent_tasks(service)
    run = await service.provider_run_repository.create_run(
        agent_task_id="agent-task",
        root_task_id="root-task",
        provider_profile_id=str(profile["id"]),
        workspace_grant_id=str(grant["id"]),
    )

    latest = await service.provider_run_repository.get_latest_run_for_profile(
        str(profile["id"])
    )

    assert latest is not None
    assert latest["id"] == run["id"]
    assert latest["capabilities"] is None


@pytest.mark.asyncio
async def test_get_latest_run_for_profile_surfaces_an_observed_capability_snapshot(
    tmp_path,
) -> None:
    service = SQLiteKnowledgeService(tmp_path / "provider_runs.db")
    profile = await _seed_profile(service)
    grant = await service.provider_profile_repository.grant_workspace(
        provider_profile_id=str(profile["id"]),
        canonical_workspace_root=str(tmp_path / "workspace"),
    )
    await _seed_agent_tasks(service)
    run = await service.provider_run_repository.create_run(
        agent_task_id="agent-task",
        root_task_id="root-task",
        provider_profile_id=str(profile["id"]),
        workspace_grant_id=str(grant["id"]),
    )
    await service.provider_run_repository.mark_run_initialized(
        provider_run_id=str(run["id"]),
        expected_revision=int(run["revision"]),
        capabilities={"fs_read": True},
        runtime_version="1.0.0",
    )

    latest = await service.provider_run_repository.get_latest_run_for_profile(
        str(profile["id"])
    )

    assert latest is not None
    assert latest["capabilities"] == {"fs_read": True}
