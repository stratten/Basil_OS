"""Focused tests for Package 5C.1's read-only provider-profile inventory presentation."""

from __future__ import annotations

import sqlite3

import pytest

from api.core.knowledge.sqlite.sqlite_knowledge_service import SQLiteKnowledgeService
from api.services.agent_providers.profiles.launch_validation import (
    list_provider_profile_summaries,
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
async def test_returns_an_empty_list_when_no_profiles_exist(tmp_path) -> None:
    service = SQLiteKnowledgeService(tmp_path / "provider_runs.db")

    summaries = await list_provider_profile_summaries(service.provider_profile_repository, service.provider_run_repository)

    assert summaries == []


@pytest.mark.asyncio
async def test_a_well_formed_enabled_profile_with_no_grant_is_valid_with_no_active_grants(
    tmp_path,
) -> None:
    service = SQLiteKnowledgeService(tmp_path / "provider_runs.db")
    await service.provider_profile_repository.create_profile(
        display_name="Fixture Provider",
        launch_argv=("fixture-acp", "--stdio"),
        environment_allowlist=("PATH",),
    )

    summaries = await list_provider_profile_summaries(service.provider_profile_repository, service.provider_run_repository)

    assert len(summaries) == 1
    summary = summaries[0]
    assert summary.display_name == "Fixture Provider"
    assert summary.status == "enabled"
    assert summary.capability_state == "unverified"
    assert summary.observed_capabilities is None
    assert summary.active_workspace_grants == ()
    assert summary.is_structurally_valid is True
    assert summary.validation_error is None


@pytest.mark.asyncio
async def test_a_disabled_profile_is_presented_as_disabled_without_being_marked_invalid(
    tmp_path,
) -> None:
    service = SQLiteKnowledgeService(tmp_path / "provider_runs.db")
    profile = await service.provider_profile_repository.create_profile(
        display_name="Fixture Provider",
        launch_argv=("fixture-acp", "--stdio"),
    )
    await service.provider_profile_repository.set_profile_status(str(profile["id"]), "disabled")

    summaries = await list_provider_profile_summaries(service.provider_profile_repository, service.provider_run_repository)

    assert summaries[0].status == "disabled"
    assert summaries[0].is_structurally_valid is True


@pytest.mark.asyncio
async def test_a_removed_profile_is_preserved_in_storage_but_excluded_from_the_inventory(
    tmp_path,
) -> None:
    service = SQLiteKnowledgeService(tmp_path / "provider_runs.db")
    profile = await service.provider_profile_repository.create_profile(
        display_name="Fixture Provider",
        launch_argv=("fixture-acp", "--stdio"),
    )
    await service.provider_profile_repository.set_profile_status(str(profile["id"]), "removed")

    summaries = await list_provider_profile_summaries(service.provider_profile_repository, service.provider_run_repository)

    assert summaries == []
    preserved = await service.provider_profile_repository.get_profile(str(profile["id"]))
    assert preserved is not None
    assert preserved["status"] == "removed"


@pytest.mark.asyncio
async def test_an_active_grant_is_surfaced_and_a_revoked_grant_is_not(tmp_path) -> None:
    service = SQLiteKnowledgeService(tmp_path / "provider_runs.db")
    profile = await service.provider_profile_repository.create_profile(
        display_name="Fixture Provider",
        launch_argv=("fixture-acp", "--stdio"),
    )
    active_grant = await service.provider_profile_repository.grant_workspace(
        provider_profile_id=str(profile["id"]),
        canonical_workspace_root=str(tmp_path / "workspace-a"),
    )
    revoked_grant = await service.provider_profile_repository.grant_workspace(
        provider_profile_id=str(profile["id"]),
        canonical_workspace_root=str(tmp_path / "workspace-b"),
    )
    await service.provider_profile_repository.revoke_workspace_grant(str(revoked_grant["id"]))

    summaries = await list_provider_profile_summaries(service.provider_profile_repository, service.provider_run_repository)

    assert len(summaries[0].active_workspace_grants) == 1
    assert summaries[0].active_workspace_grants[0].id == active_grant["id"]


@pytest.mark.asyncio
async def test_a_profile_whose_launch_argv_degraded_to_empty_shows_a_sanitized_validation_error(
    tmp_path,
) -> None:
    service = SQLiteKnowledgeService(tmp_path / "provider_runs.db")
    profile = await service.provider_profile_repository.create_profile(
        display_name="Fixture Provider",
        launch_argv=("fixture-acp", "--stdio"),
    )
    # create_profile itself forbids an empty launch_argv, so this simulates a row that
    # became structurally invalid after creation by writing to the schema directly.
    with sqlite3.connect(service.provider_profile_repository.db_path) as conn:
        conn.execute(
            "UPDATE provider_profiles SET launch_argv_json = '[]' WHERE id = ?",
            (str(profile["id"]),),
        )
        conn.commit()

    summaries = await list_provider_profile_summaries(service.provider_profile_repository, service.provider_run_repository)

    assert summaries[0].is_structurally_valid is False
    assert summaries[0].validation_error is not None
    assert "launch_argv" in summaries[0].validation_error


@pytest.mark.asyncio
async def test_a_run_with_an_observed_capability_snapshot_marks_the_profile_observed(
    tmp_path,
) -> None:
    service = SQLiteKnowledgeService(tmp_path / "provider_runs.db")
    profile = await service.provider_profile_repository.create_profile(
        display_name="Fixture Provider",
        launch_argv=("fixture-acp", "--stdio"),
    )
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

    summaries = await list_provider_profile_summaries(service.provider_profile_repository, service.provider_run_repository)

    assert summaries[0].observed_capabilities == {"fs_read": True}
