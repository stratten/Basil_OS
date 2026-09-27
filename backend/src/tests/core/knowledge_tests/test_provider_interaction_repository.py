"""Behavioral coverage for ProviderInteractionRepository (Package 4A)."""

from __future__ import annotations

import pytest

from api.core.knowledge.sqlite.sqlite_knowledge_service import SQLiteKnowledgeService
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.providers.interaction_repository import (
    ProviderInteractionConflictError,
    ProviderInteractionPersistenceError,
)


async def _seed_run(db_service: SQLiteKnowledgeService, *, agent_task_id: str = "task-1"):
    profile = await db_service.provider_profile_repository.create_profile(
        display_name="Test Provider",
        launch_argv=("echo", "hi"),
        environment_allowlist=(),
    )
    grant = await db_service.provider_profile_repository.grant_workspace(
        provider_profile_id=str(profile["id"]),
        canonical_workspace_root="/tmp/workspace",
    )
    await db_service.store_agent_task(
        agent_task_id=agent_task_id,
        original_prompt="run provider",
        transcribed_prompt="run provider",
        status="processing",
        root_task_id=agent_task_id,
    )
    run = await db_service.provider_run_repository.create_run(
        agent_task_id=agent_task_id,
        root_task_id=agent_task_id,
        provider_profile_id=str(profile["id"]),
        workspace_grant_id=str(grant["id"]),
    )
    return run


def _fields():
    return [
        {"name": "strategy", "label": "Strategy", "kind": "choice", "required": True, "default_value": None,
         "options": [{"id": "strategy-option-0", "label": "balanced", "value": "balanced"}]},
    ]


def _permission_options():
    return [
        {"optionId": "allow-once", "name": "Allow once", "kind": "allow_once"},
        {"optionId": "reject-once", "name": "Reject once", "kind": "reject_once"},
    ]


def _permission_summary():
    return {
        "title": "Run this command?",
        "description": "The provider wants to run a shell command.",
        "options": _permission_options(),
        "subject": {"type": "command", "command": "ls", "cwd": "/tmp"},
    }


@pytest.mark.asyncio
async def test_create_interaction_persists_a_pending_row(tmp_path) -> None:
    db_service = SQLiteKnowledgeService(tmp_path / "kb.db")
    run = await _seed_run(db_service)

    interaction = await db_service.provider_interaction_repository.create_interaction(
        provider_run_id=str(run["id"]),
        agent_task_id="task-1",
        root_task_id="task-1",
        message="Pick a strategy",
        requested_schema={"type": "object", "properties": {"strategy": {"type": "string"}}},
        fields=_fields(),
    )

    assert interaction["status"] == "pending"
    assert interaction["revision"] == 0
    assert interaction["outcome"] is None
    assert interaction["fields"][0]["name"] == "strategy"

    fetched = await db_service.provider_interaction_repository.get_interaction(interaction["id"])
    assert fetched == interaction


@pytest.mark.asyncio
async def test_get_pending_interaction_for_agent_task_returns_only_the_live_pending_record(tmp_path) -> None:
    db_service = SQLiteKnowledgeService(tmp_path / "kb.db")
    run = await _seed_run(db_service)
    first = await db_service.provider_interaction_repository.create_interaction(
        provider_run_id=str(run["id"]),
        agent_task_id="task-1",
        root_task_id="task-1",
        message="First question",
        requested_schema={"type": "object", "properties": {"strategy": {"type": "string"}}},
        fields=_fields(),
    )
    second = await db_service.provider_interaction_repository.create_interaction(
        provider_run_id=str(run["id"]),
        agent_task_id="task-1",
        root_task_id="task-1",
        message="Second question",
        requested_schema={"type": "object", "properties": {"strategy": {"type": "string"}}},
        fields=_fields(),
    )

    await db_service.provider_interaction_repository.mark_cancelled(
        interaction_id=second["id"], expected_revision=0
    )

    pending = await db_service.provider_interaction_repository.get_pending_interaction_for_agent_task(
        "task-1"
    )
    assert pending is not None
    assert pending["id"] == first["id"]


@pytest.mark.asyncio
async def test_create_interaction_rejects_an_unknown_provider_run(tmp_path) -> None:
    db_service = SQLiteKnowledgeService(tmp_path / "kb.db")
    await db_service.store_agent_task(
        agent_task_id="task-2",
        original_prompt="run provider",
        transcribed_prompt="run provider",
        status="processing",
        root_task_id="task-2",
    )

    with pytest.raises(ProviderInteractionConflictError):
        await db_service.provider_interaction_repository.create_interaction(
            provider_run_id="does-not-exist",
            agent_task_id="task-2",
            root_task_id="task-2",
            message="Pick a strategy",
            requested_schema={"type": "object", "properties": {"strategy": {"type": "string"}}},
            fields=_fields(),
        )


@pytest.mark.asyncio
async def test_mark_answered_transitions_pending_to_answered_and_stores_values(tmp_path) -> None:
    db_service = SQLiteKnowledgeService(tmp_path / "kb.db")
    run = await _seed_run(db_service)
    interaction = await db_service.provider_interaction_repository.create_interaction(
        provider_run_id=str(run["id"]),
        agent_task_id="task-1",
        root_task_id="task-1",
        message="Pick a strategy",
        requested_schema={"type": "object", "properties": {"strategy": {"type": "string"}}},
        fields=_fields(),
    )

    resolved = await db_service.provider_interaction_repository.mark_answered(
        interaction_id=interaction["id"],
        expected_revision=0,
        submitted_values={"strategy": "balanced"},
    )

    assert resolved["status"] == "answered"
    assert resolved["outcome"] == "accept"
    assert resolved["submitted_values"] == {"strategy": "balanced"}
    assert resolved["revision"] == 1


@pytest.mark.asyncio
async def test_mark_declined_and_mark_cancelled_transition_pending_correctly(tmp_path) -> None:
    db_service = SQLiteKnowledgeService(tmp_path / "kb.db")
    run = await _seed_run(db_service)

    declined_source = await db_service.provider_interaction_repository.create_interaction(
        provider_run_id=str(run["id"]),
        agent_task_id="task-1",
        root_task_id="task-1",
        message="Pick a strategy",
        requested_schema={"type": "object", "properties": {"strategy": {"type": "string"}}},
        fields=_fields(),
    )
    declined = await db_service.provider_interaction_repository.mark_declined(
        interaction_id=declined_source["id"], expected_revision=0
    )
    assert declined["status"] == "declined"
    assert declined["outcome"] == "decline"
    assert declined["submitted_values"] is None

    cancelled_source = await db_service.provider_interaction_repository.create_interaction(
        provider_run_id=str(run["id"]),
        agent_task_id="task-1",
        root_task_id="task-1",
        message="Pick a strategy",
        requested_schema={"type": "object", "properties": {"strategy": {"type": "string"}}},
        fields=_fields(),
    )
    cancelled = await db_service.provider_interaction_repository.mark_cancelled(
        interaction_id=cancelled_source["id"], expected_revision=0
    )
    assert cancelled["status"] == "cancelled"
    assert cancelled["outcome"] == "cancel"


@pytest.mark.asyncio
async def test_mark_answered_rejects_a_stale_revision(tmp_path) -> None:
    db_service = SQLiteKnowledgeService(tmp_path / "kb.db")
    run = await _seed_run(db_service)
    interaction = await db_service.provider_interaction_repository.create_interaction(
        provider_run_id=str(run["id"]),
        agent_task_id="task-1",
        root_task_id="task-1",
        message="Pick a strategy",
        requested_schema={"type": "object", "properties": {"strategy": {"type": "string"}}},
        fields=_fields(),
    )
    await db_service.provider_interaction_repository.mark_answered(
        interaction_id=interaction["id"], expected_revision=0, submitted_values={"strategy": "balanced"}
    )

    with pytest.raises(ProviderInteractionConflictError):
        await db_service.provider_interaction_repository.mark_declined(
            interaction_id=interaction["id"], expected_revision=0
        )


@pytest.mark.asyncio
async def test_mark_answered_rejects_an_already_resolved_interaction(tmp_path) -> None:
    db_service = SQLiteKnowledgeService(tmp_path / "kb.db")
    run = await _seed_run(db_service)
    interaction = await db_service.provider_interaction_repository.create_interaction(
        provider_run_id=str(run["id"]),
        agent_task_id="task-1",
        root_task_id="task-1",
        message="Pick a strategy",
        requested_schema={"type": "object", "properties": {"strategy": {"type": "string"}}},
        fields=_fields(),
    )
    await db_service.provider_interaction_repository.mark_answered(
        interaction_id=interaction["id"], expected_revision=0, submitted_values={"strategy": "balanced"}
    )

    with pytest.raises(ProviderInteractionConflictError):
        await db_service.provider_interaction_repository.mark_answered(
            interaction_id=interaction["id"], expected_revision=1, submitted_values={"strategy": "aggressive"}
        )


@pytest.mark.asyncio
async def test_supersede_pending_for_run_marks_only_pending_rows_for_that_run(tmp_path) -> None:
    db_service = SQLiteKnowledgeService(tmp_path / "kb.db")
    run_a = await _seed_run(db_service, agent_task_id="task-a")
    run_b = await _seed_run(db_service, agent_task_id="task-b")

    pending_a = await db_service.provider_interaction_repository.create_interaction(
        provider_run_id=str(run_a["id"]),
        agent_task_id="task-a",
        root_task_id="task-a",
        message="Pick a strategy",
        requested_schema={"type": "object", "properties": {"strategy": {"type": "string"}}},
        fields=_fields(),
    )
    pending_b = await db_service.provider_interaction_repository.create_interaction(
        provider_run_id=str(run_b["id"]),
        agent_task_id="task-b",
        root_task_id="task-b",
        message="Pick a strategy",
        requested_schema={"type": "object", "properties": {"strategy": {"type": "string"}}},
        fields=_fields(),
    )

    superseded_count = await db_service.provider_interaction_repository.supersede_pending_for_run(
        str(run_a["id"])
    )
    assert superseded_count == 1

    refreshed_a = await db_service.provider_interaction_repository.get_interaction(pending_a["id"])
    refreshed_b = await db_service.provider_interaction_repository.get_interaction(pending_b["id"])
    assert refreshed_a["status"] == "superseded"
    assert refreshed_a["outcome"] == "cancel"
    assert refreshed_b["status"] == "pending"


@pytest.mark.asyncio
async def test_create_permission_interaction_persists_a_pending_row(tmp_path) -> None:
    db_service = SQLiteKnowledgeService(tmp_path / "kb.db")
    run = await _seed_run(db_service)

    interaction = await db_service.provider_interaction_repository.create_permission_interaction(
        provider_run_id=str(run["id"]),
        agent_task_id="task-1",
        root_task_id="task-1",
        action_summary=_permission_summary(),
    )

    assert interaction["interaction_kind"] == "provider_permission"
    assert interaction["status"] == "pending"
    assert interaction["revision"] == 0
    assert interaction["message"] == "Run this command?"
    assert interaction["requested_schema"] == {
        "description": "The provider wants to run a shell command.",
        "subject": {"type": "command", "command": "ls", "cwd": "/tmp"},
    }
    assert interaction["fields"] == _permission_options()
    assert interaction["submitted_values"] is None


@pytest.mark.asyncio
async def test_create_permission_interaction_rejects_an_unnormalized_summary(tmp_path) -> None:
    db_service = SQLiteKnowledgeService(tmp_path / "kb.db")
    run = await _seed_run(db_service)
    summary = _permission_summary()
    summary["title"] = "x" * 600

    with pytest.raises(ProviderInteractionPersistenceError, match="invalid permission action summary"):
        await db_service.provider_interaction_repository.create_permission_interaction(
            provider_run_id=str(run["id"]),
            agent_task_id="task-1",
            root_task_id="task-1",
            action_summary=summary,
        )


@pytest.mark.asyncio
async def test_create_permission_interaction_rejects_a_run_task_or_root_mismatch(tmp_path) -> None:
    db_service = SQLiteKnowledgeService(tmp_path / "kb.db")
    run_a = await _seed_run(db_service, agent_task_id="task-a")
    await _seed_run(db_service, agent_task_id="task-b")

    with pytest.raises(ProviderInteractionConflictError):
        await db_service.provider_interaction_repository.create_permission_interaction(
            provider_run_id=str(run_a["id"]),
            agent_task_id="task-b",
            root_task_id="task-b",
            action_summary=_permission_summary(),
        )
    with pytest.raises(ProviderInteractionConflictError):
        await db_service.provider_interaction_repository.create_permission_interaction(
            provider_run_id=str(run_a["id"]),
            agent_task_id="task-a",
            root_task_id="task-b",
            action_summary=_permission_summary(),
        )


@pytest.mark.asyncio
async def test_resolve_permission_interaction_transitions_to_answered_and_records_selected_option(
    tmp_path,
) -> None:
    db_service = SQLiteKnowledgeService(tmp_path / "kb.db")
    run = await _seed_run(db_service)
    interaction = await db_service.provider_interaction_repository.create_permission_interaction(
        provider_run_id=str(run["id"]),
        agent_task_id="task-1",
        root_task_id="task-1",
        action_summary=_permission_summary(),
    )

    resolved = await db_service.provider_interaction_repository.resolve_permission_interaction(
        interaction_id=interaction["id"],
        provider_run_id=str(run["id"]),
        agent_task_id="task-1",
        expected_revision=0,
        selected_option_id="reject-once",
    )

    assert resolved["status"] == "answered"
    assert resolved["outcome"] == "accept"
    assert resolved["submitted_values"] == {"selected_option_id": "reject-once"}
    assert resolved["revision"] == 1


@pytest.mark.asyncio
async def test_resolve_permission_interaction_preserves_an_offered_option_id_verbatim(tmp_path) -> None:
    db_service = SQLiteKnowledgeService(tmp_path / "kb.db")
    run = await _seed_run(db_service)
    summary = _permission_summary()
    summary["options"][0]["optionId"] = " allow-once "
    interaction = await db_service.provider_interaction_repository.create_permission_interaction(
        provider_run_id=str(run["id"]),
        agent_task_id="task-1",
        root_task_id="task-1",
        action_summary=summary,
    )

    resolved = await db_service.provider_interaction_repository.resolve_permission_interaction(
        interaction_id=interaction["id"],
        provider_run_id=str(run["id"]),
        agent_task_id="task-1",
        expected_revision=0,
        selected_option_id=" allow-once ",
    )

    assert resolved["submitted_values"] == {"selected_option_id": " allow-once "}


@pytest.mark.asyncio
async def test_resolve_permission_interaction_rejects_an_option_not_offered_by_the_provider(tmp_path) -> None:
    db_service = SQLiteKnowledgeService(tmp_path / "kb.db")
    run = await _seed_run(db_service)
    interaction = await db_service.provider_interaction_repository.create_permission_interaction(
        provider_run_id=str(run["id"]),
        agent_task_id="task-1",
        root_task_id="task-1",
        action_summary=_permission_summary(),
    )

    with pytest.raises(ProviderInteractionConflictError):
        await db_service.provider_interaction_repository.resolve_permission_interaction(
            interaction_id=interaction["id"],
            provider_run_id=str(run["id"]),
            agent_task_id="task-1",
            expected_revision=0,
            selected_option_id="invented-option",
        )
    refreshed = await db_service.provider_interaction_repository.get_interaction(interaction["id"])
    assert refreshed["status"] == "pending"
    assert refreshed["revision"] == 0


@pytest.mark.asyncio
async def test_resolve_permission_interaction_rejects_a_stale_revision(tmp_path) -> None:
    db_service = SQLiteKnowledgeService(tmp_path / "kb.db")
    run = await _seed_run(db_service)
    interaction = await db_service.provider_interaction_repository.create_permission_interaction(
        provider_run_id=str(run["id"]),
        agent_task_id="task-1",
        root_task_id="task-1",
        action_summary=_permission_summary(),
    )
    await db_service.provider_interaction_repository.resolve_permission_interaction(
        interaction_id=interaction["id"],
        provider_run_id=str(run["id"]),
        agent_task_id="task-1",
        expected_revision=0,
        selected_option_id="reject-once",
    )

    with pytest.raises(ProviderInteractionConflictError):
        await db_service.provider_interaction_repository.resolve_permission_interaction(
            interaction_id=interaction["id"],
            provider_run_id=str(run["id"]),
            agent_task_id="task-1",
            expected_revision=0,
            selected_option_id="allow-once",
        )


@pytest.mark.asyncio
async def test_resolve_permission_interaction_rejects_an_already_resolved_interaction(tmp_path) -> None:
    db_service = SQLiteKnowledgeService(tmp_path / "kb.db")
    run = await _seed_run(db_service)
    interaction = await db_service.provider_interaction_repository.create_permission_interaction(
        provider_run_id=str(run["id"]),
        agent_task_id="task-1",
        root_task_id="task-1",
        action_summary=_permission_summary(),
    )
    await db_service.provider_interaction_repository.resolve_permission_interaction(
        interaction_id=interaction["id"],
        provider_run_id=str(run["id"]),
        agent_task_id="task-1",
        expected_revision=0,
        selected_option_id="reject-once",
    )

    with pytest.raises(ProviderInteractionConflictError):
        await db_service.provider_interaction_repository.resolve_permission_interaction(
            interaction_id=interaction["id"],
            provider_run_id=str(run["id"]),
            agent_task_id="task-1",
            expected_revision=1,
            selected_option_id="allow-once",
        )


@pytest.mark.asyncio
async def test_resolve_permission_interaction_rejects_a_mismatched_provider_run(tmp_path) -> None:
    db_service = SQLiteKnowledgeService(tmp_path / "kb.db")
    run_a = await _seed_run(db_service, agent_task_id="task-a")
    run_b = await _seed_run(db_service, agent_task_id="task-b")
    interaction = await db_service.provider_interaction_repository.create_permission_interaction(
        provider_run_id=str(run_a["id"]),
        agent_task_id="task-a",
        root_task_id="task-a",
        action_summary=_permission_summary(),
    )

    with pytest.raises(ProviderInteractionConflictError):
        await db_service.provider_interaction_repository.resolve_permission_interaction(
            interaction_id=interaction["id"],
            provider_run_id=str(run_b["id"]),
            agent_task_id="task-a",
            expected_revision=0,
            selected_option_id="reject-once",
        )


@pytest.mark.asyncio
async def test_resolve_permission_interaction_rejects_a_mismatched_agent_task(tmp_path) -> None:
    db_service = SQLiteKnowledgeService(tmp_path / "kb.db")
    run_a = await _seed_run(db_service, agent_task_id="task-a")
    await _seed_run(db_service, agent_task_id="task-b")
    interaction = await db_service.provider_interaction_repository.create_permission_interaction(
        provider_run_id=str(run_a["id"]),
        agent_task_id="task-a",
        root_task_id="task-a",
        action_summary=_permission_summary(),
    )

    with pytest.raises(ProviderInteractionConflictError):
        await db_service.provider_interaction_repository.resolve_permission_interaction(
            interaction_id=interaction["id"],
            provider_run_id=str(run_a["id"]),
            agent_task_id="task-b",
            expected_revision=0,
            selected_option_id="reject-once",
        )


@pytest.mark.asyncio
async def test_resolve_permission_interaction_rejects_a_provider_user_input_interaction(tmp_path) -> None:
    db_service = SQLiteKnowledgeService(tmp_path / "kb.db")
    run = await _seed_run(db_service)
    elicitation = await db_service.provider_interaction_repository.create_interaction(
        provider_run_id=str(run["id"]),
        agent_task_id="task-1",
        root_task_id="task-1",
        message="Pick a strategy",
        requested_schema={"type": "object", "properties": {"strategy": {"type": "string"}}},
        fields=_fields(),
    )

    with pytest.raises(ProviderInteractionConflictError):
        await db_service.provider_interaction_repository.resolve_permission_interaction(
            interaction_id=elicitation["id"],
            provider_run_id=str(run["id"]),
            agent_task_id="task-1",
            expected_revision=0,
            selected_option_id="reject-once",
        )


@pytest.mark.asyncio
async def test_cancel_permission_interaction_transitions_to_cancelled(tmp_path) -> None:
    db_service = SQLiteKnowledgeService(tmp_path / "kb.db")
    run = await _seed_run(db_service)
    interaction = await db_service.provider_interaction_repository.create_permission_interaction(
        provider_run_id=str(run["id"]),
        agent_task_id="task-1",
        root_task_id="task-1",
        action_summary=_permission_summary(),
    )

    cancelled = await db_service.provider_interaction_repository.cancel_permission_interaction(
        interaction_id=interaction["id"],
        provider_run_id=str(run["id"]),
        agent_task_id="task-1",
        expected_revision=0,
    )

    assert cancelled["status"] == "cancelled"
    assert cancelled["outcome"] == "cancel"
    assert cancelled["submitted_values"] is None


@pytest.mark.asyncio
async def test_supersede_pending_for_run_also_supersedes_a_pending_permission_interaction(tmp_path) -> None:
    db_service = SQLiteKnowledgeService(tmp_path / "kb.db")
    run = await _seed_run(db_service)
    interaction = await db_service.provider_interaction_repository.create_permission_interaction(
        provider_run_id=str(run["id"]),
        agent_task_id="task-1",
        root_task_id="task-1",
        action_summary=_permission_summary(),
    )

    superseded_count = await db_service.provider_interaction_repository.supersede_pending_for_run(
        str(run["id"])
    )
    assert superseded_count == 1

    refreshed = await db_service.provider_interaction_repository.get_interaction(interaction["id"])
    assert refreshed["status"] == "superseded"
    assert refreshed["outcome"] == "cancel"
