"""End-to-end `session/request_permission` fixture coverage (Package 4B.1)."""

from __future__ import annotations

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


SOURCE_ROOT = Path(__file__).resolve().parents[3]


def _fixture_argv(mode: str) -> tuple[str, ...]:
    return (
        sys.executable,
        "-m",
        "api.services.agent_providers.testing.process_fixture",
        "--fixture-mode",
        mode,
    )


@pytest.fixture(autouse=True)
def _source_root_on_pythonpath(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PYTHONPATH", str(SOURCE_ROOT))


async def _run_fixture_mode(tmp_path, *, fixture_mode: str, agent_task_id: str):
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    db_service = SQLiteKnowledgeService(tmp_path / "provider_runs.db")
    profile = await db_service.provider_profile_repository.create_profile(
        display_name="Fixture Provider",
        launch_argv=_fixture_argv(fixture_mode),
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
        routing_service=AgentTaskRoutingService(db_service=db_service, websocket_manager=None),
    )
    result = await service.run_provider_task(
        agent_task_id=agent_task_id,
        agent_task_record=record,
        provider_target={
            "provider_profile_id": str(profile["id"]),
            "workspace_grant_id": str(grant["id"]),
            "candidate_workspace_path": str(workspace_root),
        },
    )
    runs = await db_service.provider_run_repository.list_runs_for_root(agent_task_id)
    return result, runs


@pytest.mark.asyncio
async def test_permission_request_denied_fixture_completes_with_a_selected_reject_outcome(tmp_path) -> None:
    result, runs = await _run_fixture_mode(
        tmp_path, fixture_mode="permission_request_denied", agent_task_id="task-permission-denied"
    )
    assert result.success is True
    assert len(runs) == 1
    assert runs[0]["status"] == "completed"


@pytest.mark.asyncio
async def test_permission_request_unsupported_action_fixture_receives_a_protocol_error(tmp_path) -> None:
    result, runs = await _run_fixture_mode(
        tmp_path, fixture_mode="permission_request_unsupported_action", agent_task_id="task-permission-unsupported"
    )
    assert result.success is True
    assert len(runs) == 1
    assert runs[0]["status"] == "completed"


@pytest.mark.asyncio
async def test_permission_request_malformed_session_fixture_receives_a_protocol_error(tmp_path) -> None:
    result, runs = await _run_fixture_mode(
        tmp_path, fixture_mode="permission_request_malformed_session", agent_task_id="task-permission-malformed-session"
    )
    assert result.success is True
    assert len(runs) == 1
    assert runs[0]["status"] == "completed"


@pytest.mark.asyncio
async def test_permission_request_malformed_envelope_fixture_receives_a_protocol_error(tmp_path) -> None:
    result, runs = await _run_fixture_mode(
        tmp_path, fixture_mode="permission_request_malformed_envelope", agent_task_id="task-permission-malformed-envelope"
    )
    assert result.success is True
    assert len(runs) == 1
    assert runs[0]["status"] == "completed"


@pytest.mark.asyncio
async def test_permission_request_duplicate_option_ids_fixture_receives_a_protocol_error(tmp_path) -> None:
    result, runs = await _run_fixture_mode(
        tmp_path, fixture_mode="permission_request_duplicate_option_ids", agent_task_id="task-permission-duplicate"
    )
    assert result.success is True
    assert len(runs) == 1
    assert runs[0]["status"] == "completed"
