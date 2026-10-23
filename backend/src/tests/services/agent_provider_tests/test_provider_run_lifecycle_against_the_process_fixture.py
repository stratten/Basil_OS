"""End-to-end provider-run lifecycle coverage against the process fixture (Package 3A)."""

from __future__ import annotations

import asyncio
import sqlite3
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


class _FakeWebSocketManager:
    async def broadcast(self, message) -> None:
        return None


class _PendingInteractionRoutingService(AgentTaskRoutingService):
    async def publish_provider_interaction_request(self, **kwargs) -> bool:
        return True


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


async def _seed_and_run(
    tmp_path,
    *,
    fixture_mode: str,
    agent_task_id: str = "task-e2e",
) -> tuple[dict[str, object], list[dict[str, object]]]:
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
        routing_service=_PendingInteractionRoutingService(
            db_service=db_service,
            websocket_manager=None,
        ),
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
    refreshed_record = await db_service.get_agent_task(agent_task_id)
    return {"result": result, "record": refreshed_record}, runs


@pytest.mark.asyncio
async def test_run_provider_task_completes_end_to_end_against_the_clean_exit_fixture(tmp_path) -> None:
    payload, runs = await _seed_and_run(tmp_path, fixture_mode="clean_exit")

    assert payload["result"].success is True
    assert payload["result"].operation == "provider_run"
    assert len(runs) == 1
    assert runs[0]["status"] == "completed"
    assert payload["result"].data["outcome_status"] == "completed"


@pytest.mark.asyncio
async def test_run_provider_task_fails_end_to_end_against_the_crash_after_session_fixture(
    tmp_path,
) -> None:
    payload, runs = await _seed_and_run(
        tmp_path,
        fixture_mode="crash_after_session",
        agent_task_id="task-crash",
    )

    assert payload["result"].success is False
    assert len(runs) == 1
    assert runs[0]["status"] == "failed"


@pytest.mark.asyncio
async def test_activity_stream_fixture_persists_ordered_sanitized_provider_timeline(tmp_path) -> None:
    payload, runs = await _seed_and_run(
        tmp_path, fixture_mode="activity_stream", agent_task_id="task-activity"
    )

    assert payload["result"].success is True
    assert len(runs) == 1
    assert runs[0]["status"] == "completed"

    timeline = payload["record"].execution_timeline or []

    message_chunk_entries = [
        entry for entry in timeline if str(entry.get("id", "")).startswith("provider-message-chunk-")
    ]
    assert len(message_chunk_entries) == 1

    tool_entries = [entry for entry in timeline if str(entry.get("id", "")).startswith("provider-tool-")]
    assert len(tool_entries) == 1
    assert tool_entries[0]["type"] == "tool_complete"
    assert tool_entries[0]["metadata"]["tool_status"] == "completed"

    thought_entries = [entry for entry in timeline if str(entry.get("id", "")).startswith("provider-thought-")]
    assert len(thought_entries) == 1
    assert thought_entries[0]["type"] == "thinking"
    assert thought_entries[0]["metadata"].get("raw_detail") is True
    assert "\x00" not in thought_entries[0]["body"]
    assert "\r" not in thought_entries[0]["body"]
    assert thought_entries[0]["body"].endswith("…[truncated]")

    terminal_entries = [
        entry for entry in timeline if str(entry.get("id", "")).startswith("provider-terminal-output-")
    ]
    state_entries = [entry for entry in timeline if str(entry.get("id", "")).startswith("provider-state-")]
    assert len(terminal_entries) == 1
    assert len(state_entries) == 1
    tool_index = timeline.index(tool_entries[0])
    assert timeline.index(terminal_entries[0]) > tool_index
    assert timeline.index(state_entries[0]) > timeline.index(terminal_entries[0])

    # AgentTaskProviderRunService alone (no AgentTaskProcessingService in this harness) never
    # completes the Agent Task; this proves the state_update activity note did not do so either.
    assert payload["record"].status == "processing"


@pytest.mark.asyncio
async def test_elicitation_unsupported_schema_fixture_declines_without_persisting_an_interaction(
    tmp_path,
) -> None:
    payload, runs = await _seed_and_run(
        tmp_path, fixture_mode="elicitation_unsupported_schema", agent_task_id="task-elicit-unsupported"
    )

    assert payload["result"].success is True
    assert len(runs) == 1

    with sqlite3.connect(str(tmp_path / "provider_runs.db")) as conn:
        conn.row_factory = sqlite3.Row
        count = conn.execute(
            "SELECT COUNT(*) AS n FROM provider_interactions WHERE provider_run_id = ?",
            (str(runs[0]["id"]),),
        ).fetchone()["n"]
    assert count == 0


@pytest.mark.asyncio
async def test_elicitation_single_field_fixture_persists_and_delivers_the_answered_interaction(
    tmp_path,
) -> None:
    from api.services.agent_providers.interaction_delivery import (
        ProviderInteractionDeliveryRegistry,
    )

    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    db_service = SQLiteKnowledgeService(tmp_path / "provider_runs.db")
    profile = await db_service.provider_profile_repository.create_profile(
        display_name="Fixture Provider",
        launch_argv=_fixture_argv("elicitation_before_prompt_response"),
        environment_allowlist=("PYTHONPATH",),
    )
    grant = await db_service.provider_profile_repository.grant_workspace(
        provider_profile_id=str(profile["id"]),
        canonical_workspace_root=str(workspace_root),
    )
    agent_task_id = "task-elicitation"
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
        routing_service=_PendingInteractionRoutingService(
            db_service=db_service,
            websocket_manager=None,
        ),
    )
    run_task = asyncio.create_task(
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

    run_row = None
    for _ in range(100):
        runs = await db_service.provider_run_repository.list_runs_for_root(agent_task_id)
        if runs:
            run_row = runs[0]
            break
        await asyncio.sleep(0.05)
    assert run_row is not None

    interaction = None
    for _ in range(100):
        with sqlite3.connect(db_service.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT id FROM provider_interactions WHERE provider_run_id = ? AND status = 'pending'",
                (str(run_row["id"]),),
            ).fetchone()
        if row is not None:
            interaction = await db_service.provider_interaction_repository.get_interaction(row["id"])
            break
        await asyncio.sleep(0.05)
    assert interaction is not None
    assert interaction["fields"][0]["name"] == "strategy"
    assert interaction["fields"][0]["kind"] == "choice"

    delivered = ProviderInteractionDeliveryRegistry.resolve(
        interaction["id"], "accept", {"strategy": "balanced"}
    )
    assert delivered is True

    result = await asyncio.wait_for(run_task, timeout=5.0)
    assert result.success is True

    resolved = await db_service.provider_interaction_repository.get_interaction(interaction["id"])
    assert resolved["status"] == "answered"
    assert resolved["outcome"] == "accept"
    assert resolved["submitted_values"] == {"strategy": "balanced"}
    assert ProviderInteractionDeliveryRegistry.resolve(
        interaction["id"], "accept", {"strategy": "balanced"}
    ) is False


@pytest.mark.asyncio
async def test_elicitation_cancellation_terminalizes_the_pending_interaction_and_prevents_delivery(
    tmp_path,
) -> None:
    from api.services.agent_providers.interaction_delivery import (
        ProviderInteractionDeliveryRegistry,
    )

    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    db_service = SQLiteKnowledgeService(tmp_path / "provider_runs.db")
    profile = await db_service.provider_profile_repository.create_profile(
        display_name="Fixture Provider",
        launch_argv=_fixture_argv("elicitation_before_prompt_response"),
        environment_allowlist=("PYTHONPATH",),
    )
    grant = await db_service.provider_profile_repository.grant_workspace(
        provider_profile_id=str(profile["id"]),
        canonical_workspace_root=str(workspace_root),
    )
    agent_task_id = "task-elicitation-cancel"
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
        routing_service=_PendingInteractionRoutingService(
            db_service=db_service,
            websocket_manager=None,
        ),
    )
    run_task = asyncio.create_task(
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

    interaction = None
    async with asyncio.timeout(5.0):
        while interaction is None:
            interaction = await db_service.provider_interaction_repository.get_pending_interaction_for_agent_task(
                agent_task_id
            )
            if interaction is None:
                await asyncio.sleep(0)

    assert not run_task.done()
    run_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await run_task

    refreshed = await db_service.provider_interaction_repository.get_interaction(str(interaction["id"]))
    assert refreshed is not None
    assert refreshed["status"] in {"canceled", "superseded"}
    assert ProviderInteractionDeliveryRegistry.resolve(
        str(interaction["id"]), "accept", {"strategy": "balanced"}
    ) is False
