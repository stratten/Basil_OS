"""Focused coverage for Package 4C.1 backend-startup provider-run finalization."""

from __future__ import annotations

import sqlite3

import pytest

from api.core.knowledge.sqlite.sqlite_knowledge_service import SQLiteKnowledgeService
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.providers.errors import (
    ProviderRunConflictError,
)
from api.services.agent_providers.runtime.process_supervisor import (
    finalize_interrupted_provider_runs,
)


async def _seed_profile_and_grant(service: SQLiteKnowledgeService):
    profile = await service.provider_profile_repository.create_profile(
        display_name="Fixture Provider",
        launch_argv=("fixture-acp", "--stdio"),
        environment_allowlist=("PATH", "HOME"),
    )
    grant = await service.provider_profile_repository.grant_workspace(
        provider_profile_id=str(profile["id"]),
        canonical_workspace_root="/tmp/BasilACP-workspace",
    )
    return profile, grant


async def _seed_run(service: SQLiteKnowledgeService, *, agent_task_id: str, profile, grant):
    await service.store_agent_task(
        agent_task_id=agent_task_id,
        original_prompt="Prompt",
        transcribed_prompt="Prompt",
        status="processing",
        root_task_id=agent_task_id,
    )
    return await service.provider_run_repository.create_run(
        agent_task_id=agent_task_id,
        root_task_id=agent_task_id,
        provider_profile_id=str(profile["id"]),
        workspace_grant_id=str(grant["id"]),
    )


async def _advance_run_to(service: SQLiteKnowledgeService, run: dict, target_status: str) -> dict:
    """Drive a freshly created run to the requested pre-restart status."""
    if target_status == "created":
        return run
    initialized = await service.provider_run_repository.mark_run_initialized(
        provider_run_id=str(run["id"]),
        expected_revision=int(run["revision"]),
        capabilities={"loadSession": False},
        runtime_version="1.0.0",
        provider_session_id="session-1",
    )
    if target_status == "running":
        return initialized
    return await service.provider_run_repository.transition_run(
        provider_run_id=str(initialized["id"]),
        expected_revision=int(initialized["revision"]),
        next_status=target_status,
    )


@pytest.mark.asyncio
async def test_no_active_runs_returns_zero_and_makes_no_writes(tmp_path) -> None:
    service = SQLiteKnowledgeService(tmp_path / "db.sqlite3")

    finalized = await finalize_interrupted_provider_runs(
        provider_run_repository=service.provider_run_repository,
        provider_interaction_repository=service.provider_interaction_repository,
    )

    assert finalized == 0


@pytest.mark.asyncio
async def test_a_created_run_that_never_initialized_finalizes_to_failed(tmp_path) -> None:
    service = SQLiteKnowledgeService(tmp_path / "db.sqlite3")
    profile, grant = await _seed_profile_and_grant(service)
    run = await _seed_run(service, agent_task_id="task-created", profile=profile, grant=grant)

    finalized = await finalize_interrupted_provider_runs(
        provider_run_repository=service.provider_run_repository,
        provider_interaction_repository=service.provider_interaction_repository,
    )

    assert finalized == 1
    refreshed = await service.provider_run_repository.get_run(str(run["id"]))
    assert refreshed["status"] == "failed"
    assert refreshed["terminal_at"] is not None
    assert "created" in refreshed["terminal_reason"]


@pytest.mark.asyncio
async def test_a_running_run_finalizes_to_interrupted_without_a_terminal_timestamp(tmp_path) -> None:
    service = SQLiteKnowledgeService(tmp_path / "db.sqlite3")
    profile, grant = await _seed_profile_and_grant(service)
    run = await _seed_run(service, agent_task_id="task-running", profile=profile, grant=grant)
    running = await _advance_run_to(service, run, "running")

    finalized = await finalize_interrupted_provider_runs(
        provider_run_repository=service.provider_run_repository,
        provider_interaction_repository=service.provider_interaction_repository,
    )

    assert finalized == 1
    refreshed = await service.provider_run_repository.get_run(str(running["id"]))
    assert refreshed["status"] == "interrupted"
    assert refreshed["terminal_at"] is None
    assert "running" in refreshed["terminal_reason"]


@pytest.mark.asyncio
async def test_a_run_waiting_on_a_pending_permission_interaction_supersedes_it_and_interrupts_the_run(
    tmp_path,
) -> None:
    service = SQLiteKnowledgeService(tmp_path / "db.sqlite3")
    profile, grant = await _seed_profile_and_grant(service)
    run = await _seed_run(service, agent_task_id="task-permission", profile=profile, grant=grant)
    running = await _advance_run_to(service, run, "running")
    waiting = await service.provider_run_repository.transition_run(
        provider_run_id=str(running["id"]),
        expected_revision=int(running["revision"]),
        next_status="waiting_permission",
    )
    interaction = await service.provider_interaction_repository.create_permission_interaction(
        provider_run_id=str(waiting["id"]),
        agent_task_id="task-permission",
        root_task_id="task-permission",
        action_summary={
            "title": "Run a shell command",
            "description": None,
            "options": [
                {"optionId": "allow-once", "name": "Allow", "kind": "allow_once"},
                {"optionId": "reject-once", "name": "Deny", "kind": "reject_once"},
            ],
            "subject": {"type": "command", "command": "rm -rf /tmp/example", "cwd": "/tmp"},
        },
    )

    finalized = await finalize_interrupted_provider_runs(
        provider_run_repository=service.provider_run_repository,
        provider_interaction_repository=service.provider_interaction_repository,
    )

    assert finalized == 1
    refreshed_run = await service.provider_run_repository.get_run(str(waiting["id"]))
    assert refreshed_run["status"] == "interrupted"
    refreshed_interaction = await service.provider_interaction_repository.get_interaction(
        str(interaction["id"])
    )
    assert refreshed_interaction["status"] == "superseded"
    assert refreshed_interaction["outcome"] == "cancel"


@pytest.mark.asyncio
async def test_a_run_waiting_on_provider_input_supersedes_it_and_interrupts_the_run(
    tmp_path,
) -> None:
    service = SQLiteKnowledgeService(tmp_path / "db.sqlite3")
    profile, grant = await _seed_profile_and_grant(service)
    run = await _seed_run(service, agent_task_id="task-input", profile=profile, grant=grant)
    waiting = await _advance_run_to(service, run, "waiting_user_input")
    interaction = await service.provider_interaction_repository.create_interaction(
        provider_run_id=str(waiting["id"]),
        agent_task_id="task-input",
        root_task_id="task-input",
        message="What should the provider do next?",
        requested_schema={"type": "object", "properties": {"response": {"type": "string"}}},
        fields=[{"id": "response", "label": "Response", "type": "string", "required": True}],
    )

    finalized = await finalize_interrupted_provider_runs(
        provider_run_repository=service.provider_run_repository,
        provider_interaction_repository=service.provider_interaction_repository,
    )

    assert finalized == 1
    refreshed_run = await service.provider_run_repository.get_run(str(waiting["id"]))
    assert refreshed_run["status"] == "interrupted"
    refreshed_interaction = await service.provider_interaction_repository.get_interaction(
        str(interaction["id"])
    )
    assert refreshed_interaction["status"] == "superseded"
    assert refreshed_interaction["outcome"] == "cancel"


@pytest.mark.asyncio
async def test_a_cancelling_run_finalizes_to_interrupted(tmp_path) -> None:
    service = SQLiteKnowledgeService(tmp_path / "db.sqlite3")
    profile, grant = await _seed_profile_and_grant(service)
    run = await _seed_run(service, agent_task_id="task-cancelling", profile=profile, grant=grant)
    running = await _advance_run_to(service, run, "running")
    cancelling = await service.provider_run_repository.transition_run(
        provider_run_id=str(running["id"]),
        expected_revision=int(running["revision"]),
        next_status="cancelling",
    )

    finalized = await finalize_interrupted_provider_runs(
        provider_run_repository=service.provider_run_repository,
        provider_interaction_repository=service.provider_interaction_repository,
    )

    assert finalized == 1
    refreshed = await service.provider_run_repository.get_run(str(cancelling["id"]))
    assert refreshed["status"] == "interrupted"


@pytest.mark.asyncio
async def test_an_already_terminal_run_is_left_untouched(tmp_path) -> None:
    service = SQLiteKnowledgeService(tmp_path / "db.sqlite3")
    profile, grant = await _seed_profile_and_grant(service)
    run = await _seed_run(service, agent_task_id="task-completed", profile=profile, grant=grant)
    initialized = await service.provider_run_repository.mark_run_initialized(
        provider_run_id=str(run["id"]),
        expected_revision=int(run["revision"]),
        capabilities={"loadSession": False},
        runtime_version="1.0.0",
        provider_session_id="session-1",
    )
    completed = await service.provider_run_repository.transition_run(
        provider_run_id=str(initialized["id"]),
        expected_revision=int(initialized["revision"]),
        next_status="completed",
    )

    finalized = await finalize_interrupted_provider_runs(
        provider_run_repository=service.provider_run_repository,
        provider_interaction_repository=service.provider_interaction_repository,
    )

    assert finalized == 0
    refreshed = await service.provider_run_repository.get_run(str(completed["id"]))
    assert refreshed["status"] == "completed"
    assert refreshed["revision"] == completed["revision"]


@pytest.mark.asyncio
async def test_a_recoverable_run_is_left_for_package_4c2_to_decide(tmp_path) -> None:
    service = SQLiteKnowledgeService(tmp_path / "db.sqlite3")
    profile, grant = await _seed_profile_and_grant(service)
    run = await _seed_run(service, agent_task_id="task-recoverable", profile=profile, grant=grant)
    running = await _advance_run_to(service, run, "running")
    recoverable = await service.provider_run_repository.transition_run(
        provider_run_id=str(running["id"]),
        expected_revision=int(running["revision"]),
        next_status="recoverable",
    )

    finalized = await finalize_interrupted_provider_runs(
        provider_run_repository=service.provider_run_repository,
        provider_interaction_repository=service.provider_interaction_repository,
    )

    assert finalized == 0
    refreshed = await service.provider_run_repository.get_run(str(recoverable["id"]))
    assert refreshed["status"] == "recoverable"
    assert refreshed["revision"] == recoverable["revision"]


@pytest.mark.asyncio
async def test_startup_reconciliation_is_idempotent(tmp_path) -> None:
    service = SQLiteKnowledgeService(tmp_path / "db.sqlite3")
    profile, grant = await _seed_profile_and_grant(service)
    run = await _seed_run(service, agent_task_id="task-idempotent", profile=profile, grant=grant)
    running = await _advance_run_to(service, run, "running")

    first_pass = await finalize_interrupted_provider_runs(
        provider_run_repository=service.provider_run_repository,
        provider_interaction_repository=service.provider_interaction_repository,
    )
    after_first = await service.provider_run_repository.get_run(str(running["id"]))

    second_pass = await finalize_interrupted_provider_runs(
        provider_run_repository=service.provider_run_repository,
        provider_interaction_repository=service.provider_interaction_repository,
    )
    after_second = await service.provider_run_repository.get_run(str(running["id"]))

    assert first_pass == 1
    assert second_pass == 0
    assert after_first == after_second


@pytest.mark.asyncio
async def test_a_late_stale_revision_transition_after_finalization_is_rejected(tmp_path) -> None:
    service = SQLiteKnowledgeService(tmp_path / "db.sqlite3")
    profile, grant = await _seed_profile_and_grant(service)
    run = await _seed_run(service, agent_task_id="task-stale", profile=profile, grant=grant)
    running = await _advance_run_to(service, run, "running")
    pre_finalization_revision = int(running["revision"])

    await finalize_interrupted_provider_runs(
        provider_run_repository=service.provider_run_repository,
        provider_interaction_repository=service.provider_interaction_repository,
    )

    with pytest.raises(ProviderRunConflictError):
        await service.provider_run_repository.transition_run(
            provider_run_id=str(running["id"]),
            expected_revision=pre_finalization_revision,
            next_status="completed",
        )


@pytest.mark.asyncio
async def test_one_row_failure_does_not_block_finalizing_the_rest(tmp_path) -> None:
    service = SQLiteKnowledgeService(tmp_path / "db.sqlite3")
    profile, grant = await _seed_profile_and_grant(service)
    run_a = await _seed_run(service, agent_task_id="task-a", profile=profile, grant=grant)
    run_b = await _seed_run(service, agent_task_id="task-b", profile=profile, grant=grant)
    interaction_a = await service.provider_interaction_repository.create_interaction(
        provider_run_id=str(run_a["id"]),
        agent_task_id="task-a",
        root_task_id="task-a",
        message="Choose a response",
        requested_schema={"type": "object", "properties": {"response": {"type": "string"}}},
        fields=[{"id": "response", "label": "Response", "type": "string", "required": True}],
    )
    with sqlite3.connect(service.db_path) as conn:
        conn.execute(
            f"""
            CREATE TRIGGER abort_run_a_finalization
            BEFORE UPDATE OF status ON provider_runs
            WHEN NEW.id = '{run_a["id"]}'
            BEGIN
                SELECT RAISE(ABORT, 'simulated persistence failure');
            END;
            """
        )

    finalized = await finalize_interrupted_provider_runs(
        provider_run_repository=service.provider_run_repository,
        provider_interaction_repository=service.provider_interaction_repository,
    )

    assert finalized == 1
    refreshed_a = await service.provider_run_repository.get_run(str(run_a["id"]))
    refreshed_b = await service.provider_run_repository.get_run(str(run_b["id"]))
    assert refreshed_a["status"] == "created"
    assert refreshed_b["status"] == "failed"
    refreshed_interaction_a = await service.provider_interaction_repository.get_interaction(
        str(interaction_a["id"])
    )
    assert refreshed_interaction_a["status"] == "pending"
