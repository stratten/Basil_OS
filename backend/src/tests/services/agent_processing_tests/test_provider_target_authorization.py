"""Focused coverage for Package 5D.3 provider target authorization."""

from __future__ import annotations

from datetime import datetime, timedelta
import json
import os
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from api.core.knowledge.sqlite.sqlite_knowledge_service import SQLiteKnowledgeService
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.infrastructure.schema_manager import (
    SchemaManager,
)
from api.services.agent_providers.targeting.authorization_support import (
    CANCEL_TOKEN_PREFIX,
    CHOICE_TOKEN_PREFIX,
    ProviderTargetAuthorizationError,
    ProviderTargetAuthorizationUnavailableError,
)
from api.services.agent_providers.targeting.authorization_service import (
    ProviderTargetAuthorizationService,
)
from api.services.agent_providers.targeting.delegation_service import (
    ProviderTargetDelegationService,
    ProviderTargetDelegationUnavailableError,
    ProviderDelegationWaitRequest,
)


async def _seed_tasks(knowledge: SQLiteKnowledgeService) -> None:
    await knowledge.store_agent_task(
        agent_task_id="root-task",
        original_prompt="Root",
        transcribed_prompt="Root",
    )
    await knowledge.store_agent_task(
        agent_task_id="task-1",
        original_prompt="Child",
        transcribed_prompt="Child",
        root_task_id="root-task",
        previous_task_id="root-task",
        chain_sequence_number=1,
    )
    await knowledge.store_agent_task(
        agent_task_id="foreign-task",
        original_prompt="Foreign",
        transcribed_prompt="Foreign",
    )


async def _seed_profile_and_grant(
    knowledge: SQLiteKnowledgeService,
    tmp_path,
    *,
    status: str = "enabled",
    grant_status: str = "active",
) -> tuple[dict[str, object], dict[str, object], str]:
    workspace_root = Path(tmp_path) / "workspace"
    workspace_root.mkdir(parents=True, exist_ok=True)
    attached = workspace_root / "attached.py"
    attached.write_text("print('ok')\n")
    profile = await knowledge.provider_profile_repository.create_profile(
        display_name="Fixture Provider",
        launch_argv=("fixture-acp", "--stdio"),
    )
    if status != "enabled":
        await knowledge.provider_profile_repository.set_profile_status(
            str(profile["id"]),
            status,
        )
        profile = await knowledge.provider_profile_repository.get_profile(str(profile["id"]))
        assert profile is not None
    grant = await knowledge.provider_profile_repository.grant_workspace(
        provider_profile_id=str(profile["id"]),
        canonical_workspace_root=str(workspace_root),
    )
    if grant_status != "active":
        with sqlite3.connect(knowledge.db_path) as conn:
            conn.execute(
                "UPDATE provider_workspace_grants SET status = ? WHERE id = ?",
                (grant_status, str(grant["id"])),
            )
            conn.commit()
        grant = await knowledge.provider_profile_repository.get_workspace_grant(str(grant["id"]))
        assert grant is not None
    return profile, grant, str(attached)


def _authorization_service(knowledge: SQLiteKnowledgeService) -> ProviderTargetAuthorizationService:
    return ProviderTargetAuthorizationService(
        proposal_repository=knowledge.provider_discovery_proposal_repository,
        authorization_repository=knowledge.provider_target_authorization_repository,
        provider_profile_repository=knowledge.provider_profile_repository,
        agent_task_service=knowledge.agent_task_service,
    )


async def _store_proposal(
    knowledge: SQLiteKnowledgeService,
    *,
    status: str = "proposed",
    confidence: str = "high",
    grounding_tier: str = "explicit_reference_or_chain_context",
    provider_candidates: list[dict[str, str]] | None = None,
    service_candidates: list[dict[str, str | None]] | None = None,
    evidence: list[dict[str, str | None]] | None = None,
    exact_user_constraints: dict[str, str | None] | None = None,
    agent_task_id: str = "task-1",
    root_task_id: str = "root-task",
    expires_at: str = "2099-01-01T00:00:00",
) -> dict[str, object]:
    return await knowledge.provider_discovery_proposal_repository.create_or_get_proposal(
        agent_task_id=agent_task_id,
        root_task_id=root_task_id,
        status=status,
        grounding_tier=grounding_tier,
        confidence=confidence,
        provider_candidates=provider_candidates or [],
        service_candidates=service_candidates or [],
        evidence=evidence or [
            {
                "source": "user_request",
                "summary": "The user asked for delegation.",
                "reference": None,
            }
        ],
        exact_user_constraints=exact_user_constraints or {
            "provider": None,
            "workspace": None,
            "service": None,
            "tool": None,
        },
        rationale="Grounded delegation candidate.",
        resolution_note=None if status == "proposed" else "Needs user input.",
        expires_at=expires_at,
    )


@pytest.mark.asyncio
async def test_fresh_schema_contains_authorization_table_and_indexes(tmp_path) -> None:
    db_path = tmp_path / "authorization-schema.db"
    SQLiteKnowledgeService(db_path)

    with sqlite3.connect(db_path) as conn:
        table = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
            ("provider_target_authorizations",),
        ).fetchone()
        indexes = {
            row[0]
            for row in conn.execute(
                """
                SELECT name FROM sqlite_master
                WHERE type = 'index'
                  AND name IN (?, ?, ?)
                """,
                (
                    "idx_provider_target_authorization_initial",
                    "idx_provider_target_authorization_response",
                    "idx_provider_target_authorization_task_created",
                ),
            ).fetchall()
        }

    assert table == ("provider_target_authorizations",)
    assert indexes == {
        "idx_provider_target_authorization_initial",
        "idx_provider_target_authorization_response",
        "idx_provider_target_authorization_task_created",
    }


@pytest.mark.asyncio
async def test_existing_database_receives_authorization_table_without_altering_proposal(
    tmp_path,
) -> None:
    db_path = tmp_path / "migration.db"
    knowledge = SQLiteKnowledgeService(db_path)
    await _seed_tasks(knowledge)
    proposal = await _store_proposal(
        knowledge,
        status="unavailable",
        grounding_tier="insufficient",
        confidence="low",
        provider_candidates=[],
    )
    with sqlite3.connect(db_path) as conn:
        conn.execute("DROP TABLE IF EXISTS provider_target_authorizations")
        conn.commit()

    SchemaManager(str(db_path)).initialize_db()

    with sqlite3.connect(db_path) as conn:
        table = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
            ("provider_target_authorizations",),
        ).fetchone()
        row = conn.execute(
            "SELECT status FROM provider_discovery_proposals WHERE id = ?",
            (str(proposal["id"]),),
        ).fetchone()
    assert table == ("provider_target_authorizations",)
    assert row == ("unavailable",)


@pytest.mark.asyncio
async def test_proposed_high_confidence_proposal_authorizes_with_contained_file(
    tmp_path,
    monkeypatch,
) -> None:
    knowledge = SQLiteKnowledgeService(tmp_path / "authorized.db")
    await _seed_tasks(knowledge)
    profile, grant, attached = await _seed_profile_and_grant(knowledge, tmp_path)
    with sqlite3.connect(knowledge.db_path) as conn:
        conn.execute(
            "UPDATE agent_tasks SET accumulated_artifacts = ? WHERE id = ?",
            (json.dumps({"reference_paths": [attached]}), "task-1"),
        )
        conn.commit()
    proposal = await _store_proposal(
        knowledge,
        provider_candidates=[
            {
                "provider_profile_id": str(profile["id"]),
                "workspace_grant_id": str(grant["id"]),
            }
        ],
        evidence=[
            {
                "source": "reference_path",
                "summary": "Attached repository file.",
                "reference": attached,
            },
            {
                "source": "provider_catalog",
                "summary": "Catalog returned the provider.",
                "reference": str(profile["id"]),
            },
        ],
    )
    monkeypatch.setattr(
        "api.services.agent_providers.targeting.authorization_support.load_external_catalog_preferences",
        lambda: SimpleNamespace(connections=SimpleNamespace(mcp_connections=[])),
    )
    service = _authorization_service(knowledge)
    result = await service.authorize_proposal(
        agent_task_id="task-1",
        root_task_id="root-task",
        proposal_id=str(proposal["id"]),
    )

    assert result["status"] == "authorized"
    assert result["reason_code"] == "verified_current_authority"
    encoded = json.dumps(result)
    assert "resolved_workspace_path" not in encoded
    assert attached not in encoded
    assert "reference_paths" not in encoded
    stored = await knowledge.provider_target_authorization_repository.get_authorization(
        str(result["id"])
    )
    assert stored is not None
    assert stored["resolved_workspace_path"]
    assert await knowledge.provider_run_repository.get_latest_run_for_profile(
        str(profile["id"])
    ) is None
    current_grant = await knowledge.provider_profile_repository.get_workspace_grant(
        str(grant["id"])
    )
    assert current_grant is not None
    assert current_grant["revision"] == grant["revision"]
    assert [
        task.id
        for task in await knowledge.agent_task_service.get_agent_task_chain("root-task")
    ] == ["root-task", "task-1"]
    with sqlite3.connect(knowledge.db_path) as conn:
        mcp_call_count = conn.execute("SELECT COUNT(*) FROM mcp_call_log").fetchone()
    assert mcp_call_count == (0,)


@pytest.mark.asyncio
async def test_high_confidence_inferred_context_proposal_authorizes_after_live_revalidation(
    tmp_path,
    monkeypatch,
) -> None:
    knowledge = SQLiteKnowledgeService(tmp_path / "inferred-context-authorized.db")
    await _seed_tasks(knowledge)
    profile, grant, _ = await _seed_profile_and_grant(knowledge, tmp_path)
    proposal = await _store_proposal(
        knowledge,
        grounding_tier="inferred_native_context",
        confidence="high",
        provider_candidates=[
            {
                "provider_profile_id": str(profile["id"]),
                "workspace_grant_id": str(grant["id"]),
            }
        ],
        evidence=[
            {
                "source": "screen_context",
                "summary": "Cursor is visibly editing the authorized project.",
                "reference": None,
            },
            {
                "source": "provider_catalog",
                "summary": "Catalog returned the provider.",
                "reference": str(profile["id"]),
            },
        ],
    )
    monkeypatch.setattr(
        "api.services.agent_providers.targeting.authorization_support.load_external_catalog_preferences",
        lambda: SimpleNamespace(connections=SimpleNamespace(mcp_connections=[])),
    )

    result = await _authorization_service(knowledge).authorize_proposal(
        agent_task_id="task-1",
        root_task_id="root-task",
        proposal_id=str(proposal["id"]),
    )

    assert result["status"] == "authorized"
    stored = await knowledge.provider_target_authorization_repository.get_authorization(
        str(result["id"])
    )
    assert stored is not None
    assert stored["selected_provider_profile_id"] == profile["id"]
    assert stored["selected_workspace_grant_id"] == grant["id"]


@pytest.mark.asyncio
async def test_invalid_inventory_never_selects_another_candidate(tmp_path, monkeypatch) -> None:
    knowledge = SQLiteKnowledgeService(tmp_path / "invalid.db")
    await _seed_tasks(knowledge)
    profile, grant, attached = await _seed_profile_and_grant(knowledge, tmp_path)
    outside = tmp_path / "outside.py"
    outside.write_text("outside\n")
    symlink = (tmp_path / "workspace" / "escape")
    if not symlink.exists():
        os.symlink(outside, symlink)
    proposal = await _store_proposal(
        knowledge,
        provider_candidates=[
            {
                "provider_profile_id": str(profile["id"]),
                "workspace_grant_id": str(grant["id"]),
            }
        ],
        evidence=[
            {
                "source": "reference_path",
                "summary": "Attached file.",
                "reference": attached,
            },
            {
                "source": "provider_catalog",
                "summary": "Catalog returned the provider.",
                "reference": str(profile["id"]),
            },
        ],
    )
    monkeypatch.setattr(
        "api.services.agent_providers.targeting.authorization_support.load_external_catalog_preferences",
        lambda: SimpleNamespace(connections=SimpleNamespace(mcp_connections=[])),
    )
    service = _authorization_service(knowledge)

    await knowledge.provider_profile_repository.set_profile_status(
        str(profile["id"]),
        "disabled",
    )
    disabled = await service.authorize_proposal(
        agent_task_id="task-1",
        root_task_id="root-task",
        proposal_id=str(proposal["id"]),
    )
    assert disabled["status"] == "rejected"

    profile2, grant2, _ = await _seed_profile_and_grant(knowledge, tmp_path / "second")
    proposal2 = await _store_proposal(
        knowledge,
        provider_candidates=[
            {
                "provider_profile_id": str(profile2["id"]),
                "workspace_grant_id": str(grant2["id"]),
            }
        ],
        evidence=[
            {
                "source": "reference_path",
                "summary": "Attached escape symlink.",
                "reference": str(symlink),
            },
            {
                "source": "provider_catalog",
                "summary": "Catalog returned the provider.",
                "reference": str(profile2["id"]),
            },
        ],
    )
    with sqlite3.connect(knowledge.db_path) as conn:
        conn.execute(
            "UPDATE agent_tasks SET accumulated_artifacts = ? WHERE id = ?",
            (json.dumps({"reference_paths": [str(symlink)]}), "task-1"),
        )
        conn.commit()
    escaped = await service.authorize_proposal(
        agent_task_id="task-1",
        root_task_id="root-task",
        proposal_id=str(proposal2["id"]),
    )
    assert escaped["status"] == "rejected"


@pytest.mark.asyncio
async def test_missing_foreign_and_expired_proposals_fail_closed(tmp_path) -> None:
    knowledge = SQLiteKnowledgeService(tmp_path / "proposal-guards.db")
    await _seed_tasks(knowledge)
    service = _authorization_service(knowledge)
    with pytest.raises(ProviderTargetAuthorizationUnavailableError):
        await service.authorize_proposal(
            agent_task_id="task-1",
            root_task_id="root-task",
            proposal_id="missing-proposal",
        )
    proposal = await _store_proposal(
        knowledge,
        status="unavailable",
        grounding_tier="insufficient",
        confidence="low",
        provider_candidates=[],
        agent_task_id="foreign-task",
        root_task_id="foreign-task",
    )
    with pytest.raises(ProviderTargetAuthorizationError):
        await service.authorize_proposal(
            agent_task_id="task-1",
            root_task_id="root-task",
            proposal_id=str(proposal["id"]),
        )
    expired = await _store_proposal(
        knowledge,
        status="unavailable",
        grounding_tier="insufficient",
        confidence="low",
        provider_candidates=[],
        expires_at=(datetime.utcnow() - timedelta(seconds=60)).isoformat(),
    )
    expired_result = await service.authorize_proposal(
        agent_task_id="task-1",
        root_task_id="root-task",
        proposal_id=str(expired["id"]),
    )
    assert expired_result["status"] == "rejected"
    assert expired_result["reason_code"] == "proposal_expired"


@pytest.mark.asyncio
async def test_ambiguous_and_conflict_proposals_need_user_with_opaque_tokens(
    tmp_path,
    monkeypatch,
) -> None:
    knowledge = SQLiteKnowledgeService(tmp_path / "needs-user.db")
    await _seed_tasks(knowledge)
    profile, grant, _ = await _seed_profile_and_grant(knowledge, tmp_path)
    monkeypatch.setattr(
        "api.services.agent_providers.targeting.authorization_support.load_external_catalog_preferences",
        lambda: SimpleNamespace(connections=SimpleNamespace(mcp_connections=[])),
    )
    service = _authorization_service(knowledge)
    for status, note in (
        ("ambiguous", "Confirm the target."),
        ("conflicts_with_user_target", "Named target unavailable."),
        ("unavailable", "No inventory."),
    ):
        kwargs = {
            "status": status,
            "grounding_tier": (
                "insufficient"
                if status == "unavailable"
                else "exact_user_target" if status == "conflicts_with_user_target"
                else "inferred_native_context"
            ),
            "confidence": "low" if status != "conflicts_with_user_target" else "high",
            "provider_candidates": (
                []
                if status == "unavailable"
                else [
                    {
                        "provider_profile_id": str(profile["id"]),
                        "workspace_grant_id": str(grant["id"]),
                    }
                ]
            ),
            "evidence": [
                {
                    "source": "user_request",
                    "summary": "User asked for delegation.",
                    "reference": None,
                }
            ],
        }
        if status == "conflicts_with_user_target":
            kwargs["exact_user_constraints"] = {
                "provider": "Unavailable Provider",
                "workspace": None,
                "service": None,
                "tool": None,
            }
        proposal = await _store_proposal(knowledge, **kwargs)
        result = await service.authorize_proposal(
            agent_task_id="task-1",
            root_task_id="root-task",
            proposal_id=str(proposal["id"]),
        )
        assert result["status"] == "needs_user"
        checkpoint = result["checkpoint"]
        assert checkpoint["input_type"] == "choice"
        assert len(checkpoint["options"]) <= 4
        encoded = json.dumps(result)
        assert "/workspace" not in encoded
        assert all(
            option["value"].startswith(CHOICE_TOKEN_PREFIX)
            for option in checkpoint["options"]
        )


@pytest.mark.asyncio
async def test_multiple_service_candidates_require_clarification_not_target_selection(
    tmp_path,
    monkeypatch,
) -> None:
    knowledge = SQLiteKnowledgeService(tmp_path / "multiple-services.db")
    await _seed_tasks(knowledge)
    profile, grant, _ = await _seed_profile_and_grant(knowledge, tmp_path)
    monkeypatch.setattr(
        "api.services.agent_providers.targeting.authorization_support.load_external_catalog_preferences",
        lambda: SimpleNamespace(connections=SimpleNamespace(mcp_connections=[])),
    )
    proposal = await _store_proposal(
        knowledge,
        provider_candidates=[
            {
                "provider_profile_id": str(profile["id"]),
                "workspace_grant_id": str(grant["id"]),
            }
        ],
        service_candidates=[
            {"connection_id": "service-a", "tool_name": "read_a"},
            {"connection_id": "service-b", "tool_name": "read_b"},
        ],
        evidence=[
            {
                "source": "provider_catalog",
                "summary": "Catalog returned the provider.",
                "reference": str(profile["id"]),
            },
            {
                "source": "external_catalog",
                "summary": "Two service candidates remain.",
                "reference": "service-a",
            },
        ],
    )

    result = await _authorization_service(knowledge).authorize_proposal(
        agent_task_id="task-1",
        root_task_id="root-task",
        proposal_id=str(proposal["id"]),
    )

    assert result["status"] == "needs_user"
    assert result["reason_code"] == "multiple_service_candidates"
    assert result["checkpoint"]["options"] == []


@pytest.mark.asyncio
async def test_nonpath_exact_target_requires_user_confirmation(
    tmp_path,
    monkeypatch,
) -> None:
    knowledge = SQLiteKnowledgeService(tmp_path / "exact-nonpath.db")
    await _seed_tasks(knowledge)
    profile, grant, _ = await _seed_profile_and_grant(knowledge, tmp_path)
    monkeypatch.setattr(
        "api.services.agent_providers.targeting.authorization_support.load_external_catalog_preferences",
        lambda: SimpleNamespace(connections=SimpleNamespace(mcp_connections=[])),
    )
    proposal = await _store_proposal(
        knowledge,
        grounding_tier="exact_user_target",
        provider_candidates=[
            {
                "provider_profile_id": str(profile["id"]),
                "workspace_grant_id": str(grant["id"]),
            }
        ],
        evidence=[
            {
                "source": "provider_catalog",
                "summary": "Catalog returned the provider.",
                "reference": str(profile["id"]),
            }
        ],
        exact_user_constraints={
            "provider": "Fixture Provider",
            "workspace": None,
            "service": None,
            "tool": None,
        },
    )

    result = await _authorization_service(knowledge).authorize_proposal(
        agent_task_id="task-1",
        root_task_id="root-task",
        proposal_id=str(proposal["id"]),
    )

    assert result["status"] == "needs_user"
    assert result["reason_code"] == "proposal_requires_user_choice"


@pytest.mark.asyncio
async def test_never_allow_rejects_without_external_call(tmp_path, monkeypatch) -> None:
    knowledge = SQLiteKnowledgeService(tmp_path / "service-policy.db")
    await _seed_tasks(knowledge)
    profile, grant, _ = await _seed_profile_and_grant(knowledge, tmp_path)
    connection = SimpleNamespace(
        id="github-a",
        enabled=True,
        cached_tools=[SimpleNamespace(name="run_tests", is_read_only_hint=False)],
        tool_policies={"run_tests": "never_allow"},
    )
    monkeypatch.setattr(
        "api.services.agent_providers.targeting.authorization_support.load_external_catalog_preferences",
        lambda: SimpleNamespace(connections=SimpleNamespace(mcp_connections=[connection])),
    )
    monkeypatch.setattr(
        "api.services.agent_providers.targeting.authorization_support.find_external_catalog_connection",
        lambda _prefs, connection_id: connection if connection_id == "github-a" else None,
    )
    proposal = await _store_proposal(
        knowledge,
        provider_candidates=[
            {
                "provider_profile_id": str(profile["id"]),
                "workspace_grant_id": str(grant["id"]),
            }
        ],
        service_candidates=[{"connection_id": "github-a", "tool_name": "run_tests"}],
        evidence=[
            {
                "source": "provider_catalog",
                "summary": "Catalog returned the provider.",
                "reference": str(profile["id"]),
            },
            {
                "source": "external_catalog",
                "summary": "GitHub tool selected.",
                "reference": "github-a",
            },
        ],
    )
    result = await _authorization_service(knowledge).authorize_proposal(
        agent_task_id="task-1",
        root_task_id="root-task",
        proposal_id=str(proposal["id"]),
    )
    assert result["status"] == "rejected"
    assert result["reason_code"] == "service_never_allow"


@pytest.mark.asyncio
async def test_always_ask_is_retained_without_approval_request(tmp_path, monkeypatch) -> None:
    knowledge = SQLiteKnowledgeService(tmp_path / "always-ask.db")
    await _seed_tasks(knowledge)
    profile, grant, _ = await _seed_profile_and_grant(knowledge, tmp_path)
    connection = SimpleNamespace(
        id="github-a",
        enabled=True,
        cached_tools=[SimpleNamespace(name="run_tests", is_read_only_hint=False)],
        tool_policies={},
    )
    monkeypatch.setattr(
        "api.services.agent_providers.targeting.authorization_support.load_external_catalog_preferences",
        lambda: SimpleNamespace(connections=SimpleNamespace(mcp_connections=[connection])),
    )
    monkeypatch.setattr(
        "api.services.agent_providers.targeting.authorization_support.find_external_catalog_connection",
        lambda _prefs, connection_id: connection if connection_id == "github-a" else None,
    )
    monkeypatch.setattr(
        "api.services.agent_providers.targeting.authorization_support.default_external_catalog_policy_for_tool",
        lambda _record, _tool: "always_ask",
    )
    proposal = await _store_proposal(
        knowledge,
        provider_candidates=[
            {
                "provider_profile_id": str(profile["id"]),
                "workspace_grant_id": str(grant["id"]),
            }
        ],
        service_candidates=[{"connection_id": "github-a", "tool_name": "run_tests"}],
        evidence=[
            {
                "source": "provider_catalog",
                "summary": "Catalog returned the provider.",
                "reference": str(profile["id"]),
            },
            {
                "source": "external_catalog",
                "summary": "GitHub tool selected.",
                "reference": "github-a",
            },
        ],
    )
    result = await _authorization_service(knowledge).authorize_proposal(
        agent_task_id="task-1",
        root_task_id="root-task",
        proposal_id=str(proposal["id"]),
    )
    assert result["status"] == "authorized"
    stored = await knowledge.provider_target_authorization_repository.get_authorization(
        str(result["id"])
    )
    assert stored is not None
    assert stored["selected_service_policy"] == "always_ask"


@pytest.mark.asyncio
async def test_checkpoint_response_paths_are_immutable_and_idempotent(
    tmp_path,
    monkeypatch,
) -> None:
    knowledge = SQLiteKnowledgeService(tmp_path / "responses.db")
    await _seed_tasks(knowledge)
    profile, grant, _ = await _seed_profile_and_grant(knowledge, tmp_path)
    monkeypatch.setattr(
        "api.services.agent_providers.targeting.authorization_support.load_external_catalog_preferences",
        lambda: SimpleNamespace(connections=SimpleNamespace(mcp_connections=[])),
    )
    proposal = await _store_proposal(
        knowledge,
        status="ambiguous",
        grounding_tier="inferred_native_context",
        confidence="medium",
        provider_candidates=[
            {
                "provider_profile_id": str(profile["id"]),
                "workspace_grant_id": str(grant["id"]),
            }
        ],
        evidence=[
            {
                "source": "screen_context",
                "summary": "Visible project context.",
                "reference": None,
            },
            {
                "source": "provider_catalog",
                "summary": "Catalog returned the provider.",
                "reference": str(profile["id"]),
            },
        ],
    )
    service = _authorization_service(knowledge)
    needs_user = await service.authorize_proposal(
        agent_task_id="task-1",
        root_task_id="root-task",
        proposal_id=str(proposal["id"]),
    )
    replayed_needs_user = await service.authorize_proposal(
        agent_task_id="task-1",
        root_task_id="root-task",
        proposal_id=str(proposal["id"]),
    )
    token = needs_user["checkpoint"]["options"][0]["value"]
    cancel = needs_user["checkpoint"]["metadata"]["cancel_value"]
    assert token.startswith(CHOICE_TOKEN_PREFIX)
    assert cancel.startswith(CANCEL_TOKEN_PREFIX)
    assert replayed_needs_user["idempotent_replay"] is True
    assert replayed_needs_user["checkpoint"]["options"][0]["value"] == token
    assert replayed_needs_user["checkpoint"]["metadata"]["cancel_value"] == cancel

    authorized = await service.resolve_checkpoint_response(
        agent_task_id="task-1",
        root_task_id="root-task",
        authorization_id=str(needs_user["id"]),
        response=token,
    )
    assert authorized["status"] == "authorized"
    assert authorized["reason_code"] == "user_selected_verified_target"
    replay = await service.resolve_checkpoint_response(
        agent_task_id="task-1",
        root_task_id="root-task",
        authorization_id=str(needs_user["id"]),
        response=token,
    )
    assert replay["idempotent_replay"] is True

    with pytest.raises(ProviderTargetAuthorizationUnavailableError):
        await service.resolve_checkpoint_response(
            agent_task_id="task-1",
            root_task_id="root-task",
            authorization_id=str(needs_user["id"]),
            response=f"{CHOICE_TOKEN_PREFIX}different",
        )

    proposal2 = await _store_proposal(
        knowledge,
        status="ambiguous",
        grounding_tier="inferred_native_context",
        confidence="medium",
        provider_candidates=[
            {
                "provider_profile_id": str(profile["id"]),
                "workspace_grant_id": str(grant["id"]),
            }
        ],
        evidence=[
            {
                "source": "screen_context",
                "summary": "Different visible project context.",
                "reference": None,
            },
            {
                "source": "provider_catalog",
                "summary": "Catalog returned the provider.",
                "reference": str(profile["id"]),
            },
        ],
    )
    pending = await service.authorize_proposal(
        agent_task_id="task-1",
        root_task_id="root-task",
        proposal_id=str(proposal2["id"]),
    )
    canceled = await service.resolve_checkpoint_response(
        agent_task_id="task-1",
        root_task_id="root-task",
        authorization_id=str(pending["id"]),
        response=str(pending["checkpoint"]["metadata"]["cancel_value"]),
    )
    assert canceled["status"] == "canceled"
    assert canceled["reason_code"] == "user_canceled_delegation"

    proposal3 = await _store_proposal(
        knowledge,
        status="ambiguous",
        grounding_tier="inferred_native_context",
        confidence="medium",
        provider_candidates=[
            {
                "provider_profile_id": str(profile["id"]),
                "workspace_grant_id": str(grant["id"]),
            }
        ],
        evidence=[
            {
                "source": "screen_context",
                "summary": "Another visible project context.",
                "reference": None,
            },
            {
                "source": "provider_catalog",
                "summary": "Catalog returned the provider.",
                "reference": str(profile["id"]),
            },
        ],
    )
    pending3 = await service.authorize_proposal(
        agent_task_id="task-1",
        root_task_id="root-task",
        proposal_id=str(proposal3["id"]),
    )
    clarified = await service.resolve_checkpoint_response(
        agent_task_id="task-1",
        root_task_id="root-task",
        authorization_id=str(pending3["id"]),
        response="Use the other repository instead",
    )
    assert clarified["status"] == "clarification_received"
    assert clarified["reason_code"] == "user_clarification_required"
    assert clarified.get("selected_provider_profile_id") is None


@pytest.mark.asyncio
async def test_selected_target_revalidation_rejects_stale_authority(
    tmp_path,
    monkeypatch,
) -> None:
    knowledge = SQLiteKnowledgeService(tmp_path / "stale.db")
    await _seed_tasks(knowledge)
    profile, grant, _ = await _seed_profile_and_grant(knowledge, tmp_path)
    monkeypatch.setattr(
        "api.services.agent_providers.targeting.authorization_support.load_external_catalog_preferences",
        lambda: SimpleNamespace(connections=SimpleNamespace(mcp_connections=[])),
    )
    proposal = await _store_proposal(
        knowledge,
        status="ambiguous",
        grounding_tier="inferred_native_context",
        confidence="medium",
        provider_candidates=[
            {
                "provider_profile_id": str(profile["id"]),
                "workspace_grant_id": str(grant["id"]),
            }
        ],
        evidence=[
            {
                "source": "screen_context",
                "summary": "Visible project context.",
                "reference": None,
            },
            {
                "source": "provider_catalog",
                "summary": "Catalog returned the provider.",
                "reference": str(profile["id"]),
            },
        ],
    )
    service = _authorization_service(knowledge)
    pending = await service.authorize_proposal(
        agent_task_id="task-1",
        root_task_id="root-task",
        proposal_id=str(proposal["id"]),
    )
    token = pending["checkpoint"]["options"][0]["value"]
    await knowledge.provider_profile_repository.set_profile_status(
        str(profile["id"]),
        "disabled",
    )
    rejected = await service.resolve_checkpoint_response(
        agent_task_id="task-1",
        root_task_id="root-task",
        authorization_id=str(pending["id"]),
        response=token,
    )
    assert rejected["status"] == "rejected"
    assert rejected["reason_code"] == "selected_target_no_longer_authorized"


@pytest.mark.asyncio
async def test_authorization_rejects_a_proposal_when_the_current_task_root_changed(
    tmp_path,
) -> None:
    knowledge = SQLiteKnowledgeService(tmp_path / "root-mismatch.db")
    await _seed_tasks(knowledge)
    proposal = await _store_proposal(
        knowledge,
        status="unavailable",
        grounding_tier="insufficient",
        confidence="low",
        provider_candidates=[],
    )
    with sqlite3.connect(knowledge.db_path) as conn:
        conn.execute(
            "UPDATE provider_discovery_proposals SET root_task_id = ? WHERE id = ?",
            ("foreign-task", str(proposal["id"])),
        )
        conn.commit()

    with pytest.raises(
        ProviderTargetAuthorizationUnavailableError,
        match="current Agent Task is unavailable",
    ):
        await _authorization_service(knowledge).authorize_proposal(
            agent_task_id="task-1",
            root_task_id="foreign-task",
            proposal_id=str(proposal["id"]),
        )


@pytest.mark.asyncio
async def test_authorizations_cascade_when_task_chain_is_deleted(tmp_path, monkeypatch) -> None:
    knowledge = SQLiteKnowledgeService(tmp_path / "cascade.db")
    await _seed_tasks(knowledge)
    profile, grant, attached = await _seed_profile_and_grant(knowledge, tmp_path)
    with sqlite3.connect(knowledge.db_path) as conn:
        conn.execute(
            "UPDATE agent_tasks SET accumulated_artifacts = ? WHERE id = ?",
            (json.dumps({"reference_paths": [attached]}), "task-1"),
        )
        conn.commit()
    monkeypatch.setattr(
        "api.services.agent_providers.targeting.authorization_support.load_external_catalog_preferences",
        lambda: SimpleNamespace(connections=SimpleNamespace(mcp_connections=[])),
    )
    proposal = await _store_proposal(
        knowledge,
        provider_candidates=[
            {
                "provider_profile_id": str(profile["id"]),
                "workspace_grant_id": str(grant["id"]),
            }
        ],
        evidence=[
            {
                "source": "reference_path",
                "summary": "Attached repository file.",
                "reference": attached,
            },
            {
                "source": "provider_catalog",
                "summary": "Catalog returned the provider.",
                "reference": str(profile["id"]),
            },
        ],
    )
    authorization = await _authorization_service(knowledge).authorize_proposal(
        agent_task_id="task-1",
        root_task_id="root-task",
        proposal_id=str(proposal["id"]),
    )
    assert await knowledge.agent_task_service.delete_agent_task("root-task")
    assert await knowledge.provider_discovery_proposal_repository.get_proposal(
        str(proposal["id"])
    ) is None
    assert await knowledge.provider_target_authorization_repository.get_authorization(
        str(authorization["id"])
    ) is None


class _DelegationSubmissionService:
    def __init__(
        self,
        *,
        knowledge: SQLiteKnowledgeService | None = None,
        result: dict[str, object] | None = None,
    ) -> None:
        self.knowledge = knowledge
        self.calls: list[dict[str, object]] = []
        self.result = result or {
            "success": True,
            "agent_task_id": "unused",
            "status": "routing",
        }

    async def reserve_authorized_provider_delegation(self, **kwargs) -> dict[str, object]:
        self.calls.append(kwargs)
        if self.knowledge is None:
            raise RuntimeError("test delegation submission requires SQLite knowledge")
        await self.knowledge.store_agent_task(
            agent_task_id=kwargs["child_agent_task_id"],
            original_prompt=kwargs["agent_task"],
            transcribed_prompt=kwargs["agent_task"],
            root_task_id=kwargs["root_task_id"],
            previous_task_id=kwargs["parent_agent_task_id"],
            chain_sequence_number=kwargs["chain_sequence_number"],
            session_type="provider_delegation",
            accumulated_artifacts=kwargs["delegation_context"],
        )
        await self.knowledge.update_agent_task_status(
            agent_task_id=kwargs["child_agent_task_id"],
            status="routing",
        )
        return self.result

    async def dispatch_reserved_authorized_provider_delegation(self, **kwargs) -> dict[str, object]:
        self.calls.append({"dispatch": kwargs})
        return self.result

    @property
    def reserve_calls(self) -> list[dict[str, object]]:
        return [call for call in self.calls if "dispatch" not in call]


def _delegation_service(
    knowledge: SQLiteKnowledgeService,
    submission_service: _DelegationSubmissionService,
) -> ProviderTargetDelegationService:
    submission_service.knowledge = knowledge
    return ProviderTargetDelegationService(
        proposal_repository=knowledge.provider_discovery_proposal_repository,
        authorization_repository=knowledge.provider_target_authorization_repository,
        delegation_repository=knowledge.provider_target_delegation_repository,
        provider_profile_repository=knowledge.provider_profile_repository,
        agent_task_service=knowledge.agent_task_service,
        submission_service=submission_service,
        delegated_agent_repository=knowledge.delegated_agent_repository,
    )


async def _create_authorized_delegation_fixture(
    knowledge: SQLiteKnowledgeService,
    tmp_path,
    monkeypatch,
) -> dict[str, object]:
    await _seed_tasks(knowledge)
    profile, grant, attached_path = await _seed_profile_and_grant(knowledge, tmp_path)
    with sqlite3.connect(knowledge.db_path) as conn:
        conn.execute(
            "UPDATE agent_tasks SET accumulated_artifacts = ? WHERE id = ?",
            (json.dumps({"reference_paths": [attached_path]}), "task-1"),
        )
        conn.commit()
    proposal = await _store_proposal(
        knowledge,
        provider_candidates=[
            {
                "provider_profile_id": str(profile["id"]),
                "workspace_grant_id": str(grant["id"]),
            }
        ],
        evidence=[
            {
                "source": "reference_path",
                "summary": "Attached source file.",
                "reference": attached_path,
            },
            {
                "source": "provider_catalog",
                "summary": "Catalog returned the provider.",
                "reference": str(profile["id"]),
            },
        ],
    )
    monkeypatch.setattr(
        "api.services.agent_providers.targeting.authorization_support.load_external_catalog_preferences",
        lambda: SimpleNamespace(connections=SimpleNamespace(mcp_connections=[])),
    )
    authorization = await _authorization_service(knowledge).authorize_proposal(
        agent_task_id="task-1",
        root_task_id="root-task",
        proposal_id=str(proposal["id"]),
    )
    assert authorization["status"] == "authorized"
    return authorization


async def _create_second_authorized_delegation_fixture(
    knowledge: SQLiteKnowledgeService,
    first_authorization: dict[str, object],
) -> dict[str, object]:
    stored_first = await knowledge.provider_target_authorization_repository.get_authorization(
        str(first_authorization["id"])
    )
    assert stored_first is not None
    attached_path = str(
        Path(str(stored_first["resolved_workspace_path"])) / "attached.py"
    )
    proposal = await _store_proposal(
        knowledge,
        provider_candidates=[
            {
                "provider_profile_id": str(
                    stored_first["selected_provider_profile_id"]
                ),
                "workspace_grant_id": str(
                    stored_first["selected_workspace_grant_id"]
                ),
            }
        ],
        evidence=[
            {
                "source": "reference_path",
                "summary": "Second distinct proposal for the same source file.",
                "reference": attached_path,
            },
            {
                "source": "provider_catalog",
                "summary": "Catalog returned the same eligible provider.",
                "reference": str(stored_first["selected_provider_profile_id"]),
            },
        ],
    )
    authorization = await _authorization_service(knowledge).authorize_proposal(
        agent_task_id="task-1",
        root_task_id="root-task",
        proposal_id=str(proposal["id"]),
    )
    assert authorization["status"] == "authorized"
    assert authorization["id"] != first_authorization["id"]
    return authorization


@pytest.mark.asyncio
async def test_delegation_schema_and_dispatch_are_durable_and_idempotent(tmp_path, monkeypatch) -> None:
    knowledge = SQLiteKnowledgeService(tmp_path / "delegation.db")
    authorization = await _create_authorized_delegation_fixture(knowledge, tmp_path, monkeypatch)
    submission = _DelegationSubmissionService()
    service = _delegation_service(knowledge, submission)

    with pytest.raises(ProviderDelegationWaitRequest) as first_wait:
        await service.delegate_authorization(
            agent_task_id="task-1",
            root_task_id="root-task",
            authorization_id=str(authorization["id"]),
        )
    with pytest.raises(ProviderDelegationWaitRequest) as replay_wait:
        await service.delegate_authorization(
            agent_task_id="task-1",
            root_task_id="root-task",
            authorization_id=str(authorization["id"]),
        )

    assert replay_wait.value.delegation_id == first_wait.value.delegation_id
    assert replay_wait.value.child_agent_task_id == first_wait.value.child_agent_task_id
    stored = await knowledge.provider_target_delegation_repository.get_delegation_by_authorization(
        str(authorization["id"])
    )
    assert stored is not None
    run = await knowledge.delegated_agent_repository.get_run(str(stored["delegated_agent_run_id"]))
    assert run is not None
    assert run["status"] == "admitted"
    assert stored["child_agent_task_id"] == first_wait.value.child_agent_task_id
    assert len(submission.reserve_calls) == 1
    call = submission.reserve_calls[0]
    assert call["root_task_id"] == "root-task"
    assert call["parent_agent_task_id"] == "task-1"
    assert call["chain_sequence_number"] == 2
    assert call["delegation_context"]["provider_delegation"]["authorization_id"] == authorization["id"]
    assert "screen_text" not in call["delegation_context"]
    assert "evidence" not in call["delegation_context"]["provider_delegation"]


@pytest.mark.asyncio
async def test_distinct_authorizations_admit_independent_pending_children(
    tmp_path,
    monkeypatch,
) -> None:
    knowledge = SQLiteKnowledgeService(tmp_path / "parent-admission-pending.db")
    first_authorization = await _create_authorized_delegation_fixture(
        knowledge,
        tmp_path,
        monkeypatch,
    )
    second_authorization = await _create_second_authorized_delegation_fixture(
        knowledge,
        first_authorization,
    )
    submission = _DelegationSubmissionService()
    service = _delegation_service(knowledge, submission)

    with pytest.raises(ProviderDelegationWaitRequest) as first_wait:
        await service.delegate_authorization(
            agent_task_id="task-1",
            root_task_id="root-task",
            authorization_id=str(first_authorization["id"]),
        )
    with pytest.raises(ProviderDelegationWaitRequest) as second_wait:
        await service.delegate_authorization(
            agent_task_id="task-1",
            root_task_id="root-task",
            authorization_id=str(second_authorization["id"]),
        )

    assert second_wait.value.delegation_id != first_wait.value.delegation_id
    assert second_wait.value.child_agent_task_id != first_wait.value.child_agent_task_id
    assert len(submission.reserve_calls) == 2
    with sqlite3.connect(knowledge.db_path) as conn:
        rows = conn.execute(
            """
            SELECT d.authorization_id, d.child_agent_task_id, r.status
            FROM provider_target_delegations d
            JOIN delegated_agent_runs r ON r.id = d.delegated_agent_run_id
            WHERE d.parent_agent_task_id = ?
            """,
            ("task-1",),
        ).fetchall()
    assert set(rows) == {
        (str(first_authorization["id"]), first_wait.value.child_agent_task_id, "admitted"),
        (str(second_authorization["id"]), second_wait.value.child_agent_task_id, "admitted"),
    }


@pytest.mark.asyncio
async def test_distinct_authorizations_record_independent_launch_failures(
    tmp_path,
    monkeypatch,
) -> None:
    knowledge = SQLiteKnowledgeService(tmp_path / "parent-admission-launch-failure.db")
    first_authorization = await _create_authorized_delegation_fixture(
        knowledge,
        tmp_path,
        monkeypatch,
    )
    second_authorization = await _create_second_authorized_delegation_fixture(
        knowledge,
        first_authorization,
    )
    submission = _DelegationSubmissionService(
        result={"success": False, "status": "failed"}
    )
    service = _delegation_service(knowledge, submission)

    first = await service.delegate_authorization(
        agent_task_id="task-1",
        root_task_id="root-task",
        authorization_id=str(first_authorization["id"]),
    )
    second = await service.delegate_authorization(
        agent_task_id="task-1",
        root_task_id="root-task",
        authorization_id=str(second_authorization["id"]),
    )

    assert first["status"] == "launch_failed"
    assert second["status"] == "launch_failed"
    assert second["delegation_id"] != first["delegation_id"]
    assert len(submission.reserve_calls) == 2


@pytest.mark.asyncio
async def test_parent_lookup_prefers_earliest_historical_delegation(
    tmp_path,
    monkeypatch,
) -> None:
    knowledge = SQLiteKnowledgeService(tmp_path / "parent-admission-ordering.db")
    first_authorization = await _create_authorized_delegation_fixture(
        knowledge,
        tmp_path,
        monkeypatch,
    )
    second_authorization = await _create_second_authorized_delegation_fixture(
        knowledge,
        first_authorization,
    )
    service = _delegation_service(knowledge, _DelegationSubmissionService())

    with pytest.raises(ProviderDelegationWaitRequest) as first_wait:
        await service.delegate_authorization(
            agent_task_id="task-1",
            root_task_id="root-task",
            authorization_id=str(first_authorization["id"]),
        )

    stored_second = await knowledge.provider_target_authorization_repository.get_authorization(
        str(second_authorization["id"])
    )
    assert stored_second is not None
    with sqlite3.connect(knowledge.db_path) as conn:
        conn.execute(
            """
            INSERT INTO provider_target_delegations (
                id, authorization_id, parent_agent_task_id, root_task_id,
                child_agent_task_id, delegated_agent_run_id, provider_profile_id, workspace_grant_id,
                selected_connection_id, selected_tool_name, selected_service_policy,
                legacy_lifecycle_snapshot_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, '{}', ?, ?)
            """,
            (
                "historical-delegation-2",
                str(second_authorization["id"]),
                "task-1",
                "root-task",
                "historical-child-2",
                str(stored_second["selected_provider_profile_id"]),
                str(stored_second["selected_workspace_grant_id"]),
                stored_second["selected_connection_id"],
                stored_second["selected_tool_name"],
                stored_second["selected_service_policy"],
                "2099-01-01T00:00:00",
                "2099-01-01T00:00:00",
            ),
        )
        conn.commit()

    admitted = await knowledge.provider_target_delegation_repository.get_delegation_by_parent_agent_task(
        "task-1"
    )

    assert admitted is not None
    assert admitted["id"] == first_wait.value.delegation_id


@pytest.mark.asyncio
async def test_delegation_rejects_foreign_and_expired_authorizations(tmp_path, monkeypatch) -> None:
    knowledge = SQLiteKnowledgeService(tmp_path / "delegation-rejection.db")
    authorization = await _create_authorized_delegation_fixture(knowledge, tmp_path, monkeypatch)
    service = _delegation_service(knowledge, _DelegationSubmissionService())

    with pytest.raises(ProviderTargetDelegationUnavailableError) as foreign_error:
        await service.delegate_authorization(
            agent_task_id="foreign-task",
            root_task_id="foreign-task",
            authorization_id=str(authorization["id"]),
        )
    assert foreign_error.value.reason_code == "authorization_not_current_task"

    with sqlite3.connect(knowledge.db_path) as conn:
        conn.execute(
            "UPDATE provider_target_authorizations SET expires_at = ? WHERE id = ?",
            ("2000-01-01T00:00:00", str(authorization["id"])),
        )
        conn.commit()
    with pytest.raises(ProviderTargetDelegationUnavailableError) as expired_error:
        await service.delegate_authorization(
            agent_task_id="task-1",
            root_task_id="root-task",
            authorization_id=str(authorization["id"]),
        )
    assert expired_error.value.reason_code == "authorization_expired"


@pytest.mark.asyncio
async def test_delegation_marks_submission_rejection_without_retrying(tmp_path, monkeypatch) -> None:
    knowledge = SQLiteKnowledgeService(tmp_path / "delegation-submission-failure.db")
    authorization = await _create_authorized_delegation_fixture(knowledge, tmp_path, monkeypatch)
    submission = _DelegationSubmissionService(
        result={"success": False, "status": "failed"}
    )
    service = _delegation_service(knowledge, submission)

    first = await service.delegate_authorization(
        agent_task_id="task-1",
        root_task_id="root-task",
        authorization_id=str(authorization["id"]),
    )
    replay = await service.delegate_authorization(
        agent_task_id="task-1",
        root_task_id="root-task",
        authorization_id=str(authorization["id"]),
    )

    assert first["ok"] is False
    assert first["status"] == "launch_failed"
    assert replay["status"] == "launch_failed"
    assert len(submission.reserve_calls) == 1


@pytest.mark.asyncio
async def test_delegation_rejects_successful_submission_without_routing_status(
    tmp_path,
    monkeypatch,
) -> None:
    knowledge = SQLiteKnowledgeService(tmp_path / "delegation-unrouted-submission.db")
    authorization = await _create_authorized_delegation_fixture(knowledge, tmp_path, monkeypatch)
    submission = _DelegationSubmissionService(
        result={"success": True, "status": "completed"}
    )

    result = await _delegation_service(knowledge, submission).delegate_authorization(
        agent_task_id="task-1",
        root_task_id="root-task",
        authorization_id=str(authorization["id"]),
    )

    assert result["status"] == "launch_failed"
    assert result["reason_code"] == "child_submission_failed"
    assert len(submission.reserve_calls) == 1


@pytest.mark.asyncio
async def test_delegation_records_proposal_unavailability_after_durable_creation(
    tmp_path,
    monkeypatch,
) -> None:
    knowledge = SQLiteKnowledgeService(tmp_path / "delegation-missing-proposal.db")
    authorization = await _create_authorized_delegation_fixture(knowledge, tmp_path, monkeypatch)
    submission = _DelegationSubmissionService()
    service = _delegation_service(knowledge, submission)
    service._proposals = SimpleNamespace(get_proposal=AsyncMock(return_value=None))

    result = await service.delegate_authorization(
        agent_task_id="task-1",
        root_task_id="root-task",
        authorization_id=str(authorization["id"]),
    )

    stored = await knowledge.provider_target_delegation_repository.get_delegation_by_authorization(
        str(authorization["id"])
    )
    assert result["status"] == "launch_failed"
    assert result["reason_code"] == "proposal_unavailable"
    assert stored is None
    assert submission.calls == []


@pytest.mark.asyncio
async def test_delegation_revalidates_disabled_profile_and_revoked_grant(tmp_path, monkeypatch) -> None:
    knowledge = SQLiteKnowledgeService(tmp_path / "delegation-revalidation.db")
    authorization = await _create_authorized_delegation_fixture(knowledge, tmp_path, monkeypatch)
    stored = await knowledge.provider_target_authorization_repository.get_authorization(
        str(authorization["id"])
    )
    assert stored is not None
    submission = _DelegationSubmissionService()
    service = _delegation_service(knowledge, submission)

    await knowledge.provider_profile_repository.set_profile_status(
        str(stored["selected_provider_profile_id"]),
        "disabled",
    )
    disabled = await service.delegate_authorization(
        agent_task_id="task-1",
        root_task_id="root-task",
        authorization_id=str(authorization["id"]),
    )
    assert disabled == {
        "ok": False,
        "status": "unavailable",
        "reason_code": "selected_target_no_longer_authorized",
        "message": "The selected provider target is no longer authorized.",
    }
    assert submission.calls == []

    await knowledge.provider_profile_repository.set_profile_status(
        str(stored["selected_provider_profile_id"]),
        "enabled",
    )
    await knowledge.provider_profile_repository.revoke_workspace_grant(
        str(stored["selected_workspace_grant_id"]),
    )
    revoked = await service.delegate_authorization(
        agent_task_id="task-1",
        root_task_id="root-task",
        authorization_id=str(authorization["id"]),
    )
    assert revoked == {
        "ok": False,
        "status": "unavailable",
        "reason_code": "selected_target_no_longer_authorized",
        "message": "The selected provider target is no longer authorized.",
    }
    assert submission.calls == []


@pytest.mark.asyncio
async def test_delegation_does_not_create_rows_for_ordinary_tasks(tmp_path) -> None:
    knowledge = SQLiteKnowledgeService(tmp_path / "delegation-ordinary-task.db")
    await _seed_tasks(knowledge)

    with sqlite3.connect(knowledge.db_path) as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM provider_target_delegations"
        ).fetchone()

    assert count == (0,)


def test_existing_database_receives_delegation_table_without_losing_authorizations(
    tmp_path,
) -> None:
    db_path = tmp_path / "delegation-existing-schema.db"
    SQLiteKnowledgeService(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute("DROP INDEX IF EXISTS idx_provider_target_delegation_child")
        conn.execute("DROP INDEX IF EXISTS idx_provider_target_delegation_parent_created")
        conn.execute("DROP TABLE IF EXISTS provider_target_delegations")
        conn.commit()

    SchemaManager(str(db_path)).initialize_db()

    with sqlite3.connect(db_path) as conn:
        delegation_table = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
            ("provider_target_delegations",),
        ).fetchone()
        authorization_table = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
            ("provider_target_authorizations",),
        ).fetchone()

    assert delegation_table == ("provider_target_delegations",)
    assert authorization_table == ("provider_target_authorizations",)


def test_provider_relation_projection_excludes_lifecycle_fields(tmp_path) -> None:
    from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.providers.delegation_repository import (
        _relation_row,
    )

    excluded = {
        "status",
        "failure_reason",
        "child_terminal_status",
        "child_outcome",
        "child_terminal_at",
        "continuation_started_at",
        "continuation_finished_at",
        "continuation_failure_reason",
        "submitted_at",
        "idempotent_replay",
    }
    snapshot = {
        "status": "awaiting_child",
        "failure_reason": "launch_failed",
        "child_terminal_status": "completed",
        "child_outcome": {"message": "done"},
        "child_terminal_at": "2099-01-01T00:00:00",
        "continuation_started_at": "2099-01-01T00:00:00",
        "continuation_finished_at": "2099-01-01T00:00:00",
        "continuation_failure_reason": "resume_failed",
        "submitted_at": "2099-01-01T00:00:00",
        "idempotent_replay": True,
    }
    with sqlite3.connect(tmp_path / "relation.db") as conn:
        conn.row_factory = sqlite3.Row
        conn.execute(
            """
            CREATE TABLE provider_target_delegations (
                id TEXT PRIMARY KEY,
                authorization_id TEXT NOT NULL,
                parent_agent_task_id TEXT NOT NULL,
                root_task_id TEXT NOT NULL,
                child_agent_task_id TEXT NOT NULL,
                delegated_agent_run_id TEXT,
                provider_profile_id TEXT NOT NULL,
                workspace_grant_id TEXT NOT NULL,
                selected_connection_id TEXT,
                selected_tool_name TEXT,
                selected_service_policy TEXT,
                legacy_lifecycle_snapshot_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            INSERT INTO provider_target_delegations (
                id, authorization_id, parent_agent_task_id, root_task_id,
                child_agent_task_id, delegated_agent_run_id, provider_profile_id,
                workspace_grant_id, selected_connection_id, selected_tool_name,
                selected_service_policy, legacy_lifecycle_snapshot_json,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "delegation-1",
                "authorization-1",
                "task-1",
                "root-task",
                "child-1",
                "delegated-run-1",
                "profile-1",
                "grant-1",
                "connection-1",
                "tool-1",
                "always_ask",
                json.dumps(snapshot),
                "2099-01-01T00:00:00",
                "2099-01-01T00:00:00",
            ),
        )
        row = conn.execute("SELECT * FROM provider_target_delegations").fetchone()

    projected = _relation_row(row)

    assert excluded.isdisjoint(projected.keys())
    assert projected["legacy_lifecycle_snapshot"] == snapshot
