"""End-to-end `session/request_permission` activation coverage (Package 4B.3)."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

from api.core.knowledge.sqlite.sqlite_knowledge_service import SQLiteKnowledgeService
from api.services.agent_processing.lifecycle.submission.agent_task_processing.agent_task_provider_run_service import (
    AgentTaskProviderRunService,
)
from api.services.agent_processing.lifecycle.submission.agent_task_processing.agent_task_routing_service import (
    AgentTaskRoutingService,
)
from api.services.agent_providers.interaction_delivery import (
    ProviderInteractionDeliveryRegistry,
)


SOURCE_ROOT = Path(__file__).resolve().parents[3]


def _fixture_argv(mode: str) -> tuple[str, ...]:
    return (
        sys.executable,
        "-m",
        "api.services.agent_providers.testing.process_fixture",
        "--fixture-mode",
        mode,
    )


class _FakeWebSocketManager:
    async def broadcast(self, message):
        return None


@pytest.fixture(autouse=True)
def _source_root_on_pythonpath(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PYTHONPATH", str(SOURCE_ROOT))


@pytest.fixture(autouse=True)
def _clear_registry():
    yield
    ProviderInteractionDeliveryRegistry._pending.clear()
    ProviderInteractionDeliveryRegistry._resolving.clear()


async def _get_pending_permission_interaction(db_service: SQLiteKnowledgeService, agent_task_id: str):
    with db_service.provider_interaction_repository._get_connection() as conn:
        row = conn.execute(
            """
            SELECT * FROM provider_interactions
            WHERE agent_task_id = ?
              AND interaction_kind = 'provider_permission'
              AND status = 'pending'
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (agent_task_id,),
        ).fetchone()
    if row is None:
        return None
    return db_service.provider_interaction_repository._row_to_interaction(row)


async def _wait_for_pending_permission(db_service: SQLiteKnowledgeService, agent_task_id: str):
    for _ in range(50):
        interaction = await _get_pending_permission_interaction(db_service, agent_task_id)
        if interaction is not None:
            return interaction
        await asyncio.sleep(0.02)
    return None


async def _run_activation_fixture(
    tmp_path,
    *,
    agent_task_id: str,
    selected_option_id: str,
):
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    db_service = SQLiteKnowledgeService(tmp_path / "provider_runs.db")
    profile = await db_service.provider_profile_repository.create_profile(
        display_name="Fixture Provider",
        launch_argv=_fixture_argv("permission_request_before_prompt_response"),
        environment_allowlist=("PYTHONPATH",),
    )
    grant = await db_service.provider_profile_repository.grant_workspace(
        provider_profile_id=str(profile["id"]),
        canonical_workspace_root=str(workspace_root),
    )
    await db_service.store_agent_task(
        agent_task_id=agent_task_id,
        original_prompt="run provider",
        transcribed_prompt="run provider",
        status="processing",
        root_task_id=agent_task_id,
    )
    record = await db_service.get_agent_task(agent_task_id)
    assert record is not None

    service = AgentTaskProviderRunService(
        provider_profile_repository=db_service.provider_profile_repository,
        provider_run_repository=db_service.provider_run_repository,
        provider_interaction_repository=db_service.provider_interaction_repository,
        routing_service=AgentTaskRoutingService(
            db_service=db_service,
            websocket_manager=_FakeWebSocketManager(),
        ),
    )

    task = asyncio.create_task(
        service.run_provider_task(
            agent_task_id=agent_task_id,
            agent_task_record=record,
            provider_target={
                "provider_profile_id": str(profile["id"]),
                "workspace_grant_id": str(grant["id"]),
                "candidate_workspace_path": str(workspace_root),
            },
        )
    )

    interaction = await _wait_for_pending_permission(db_service, agent_task_id)
    assert interaction is not None
    interaction_id = str(interaction["id"])

    assert ProviderInteractionDeliveryRegistry.claim(interaction_id)
    await db_service.provider_interaction_repository.resolve_permission_interaction(
        interaction_id=interaction_id,
        provider_run_id=str(interaction["provider_run_id"]),
        agent_task_id=agent_task_id,
        expected_revision=int(interaction["revision"]),
        selected_option_id=selected_option_id,
    )
    ProviderInteractionDeliveryRegistry.deliver_claimed(
        interaction_id, "selected", {"optionId": selected_option_id}
    )

    result = await task
    refreshed = await db_service.provider_interaction_repository.get_interaction(interaction_id)
    runs = await db_service.provider_run_repository.list_runs_for_root(agent_task_id)
    return result, refreshed, runs


@pytest.mark.asyncio
async def test_permission_activation_fixture_completes_when_user_approves(tmp_path) -> None:
    result, interaction, runs = await _run_activation_fixture(
        tmp_path,
        agent_task_id="task-permission-approve",
        selected_option_id="allow-once",
    )

    assert result.success is True
    assert interaction is not None
    assert interaction["status"] == "answered"
    assert interaction["submitted_values"] == {"selected_option_id": "allow-once"}
    assert len(runs) == 1
    assert runs[0]["status"] == "completed"


@pytest.mark.asyncio
async def test_permission_activation_fixture_completes_when_user_denies(tmp_path) -> None:
    result, interaction, runs = await _run_activation_fixture(
        tmp_path,
        agent_task_id="task-permission-deny",
        selected_option_id="reject-once",
    )

    assert result.success is True
    assert interaction is not None
    assert interaction["status"] == "answered"
    assert interaction["submitted_values"] == {"selected_option_id": "reject-once"}
    assert len(runs) == 1
    assert runs[0]["status"] == "completed"


@pytest.mark.asyncio
async def test_permission_activation_cancellation_supersedes_pending_row(tmp_path) -> None:
    workspace_root = tmp_path / "workspace-cancel"
    workspace_root.mkdir()
    db_service = SQLiteKnowledgeService(tmp_path / "provider_runs_cancel.db")
    profile = await db_service.provider_profile_repository.create_profile(
        display_name="Fixture Provider",
        launch_argv=_fixture_argv("permission_request_before_prompt_response"),
        environment_allowlist=("PYTHONPATH",),
    )
    grant = await db_service.provider_profile_repository.grant_workspace(
        provider_profile_id=str(profile["id"]),
        canonical_workspace_root=str(workspace_root),
    )
    agent_task_id = "task-permission-cancel"
    await db_service.store_agent_task(
        agent_task_id=agent_task_id,
        original_prompt="run provider",
        transcribed_prompt="run provider",
        status="processing",
        root_task_id=agent_task_id,
    )
    record = await db_service.get_agent_task(agent_task_id)
    assert record is not None

    service = AgentTaskProviderRunService(
        provider_profile_repository=db_service.provider_profile_repository,
        provider_run_repository=db_service.provider_run_repository,
        provider_interaction_repository=db_service.provider_interaction_repository,
        routing_service=AgentTaskRoutingService(
            db_service=db_service,
            websocket_manager=_FakeWebSocketManager(),
        ),
    )

    task = asyncio.create_task(
        service.run_provider_task(
            agent_task_id=agent_task_id,
            agent_task_record=record,
            provider_target={
                "provider_profile_id": str(profile["id"]),
                "workspace_grant_id": str(grant["id"]),
                "candidate_workspace_path": str(workspace_root),
            },
        )
    )

    interaction = await _wait_for_pending_permission(db_service, agent_task_id)
    assert interaction is not None
    interaction_id = str(interaction["id"])

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    refreshed = await db_service.provider_interaction_repository.get_interaction(interaction_id)
    assert refreshed is not None
    assert refreshed["status"] in {"cancelled", "superseded"}
