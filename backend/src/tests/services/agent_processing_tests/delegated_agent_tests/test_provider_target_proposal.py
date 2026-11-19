"""Focused persistence and semantic validation coverage for Package 5D.2."""

from __future__ import annotations

from datetime import datetime
import sqlite3
from types import SimpleNamespace

import pytest

from api.core.knowledge.sqlite.sqlite_knowledge_service import SQLiteKnowledgeService
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.infrastructure.schema_manager import (
    SchemaManager,
)
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.providers.discovery_proposal_repository import (
    ProviderDiscoveryProposalConflictError,
    ProviderDiscoveryProposalPersistenceError,
)
from api.services.agent_providers.catalog.catalog_service import ProviderCatalogNotFoundError
from api.services.agent_providers.catalog.target_proposal_service import (
    ProviderTargetProposalError,
    ProviderTargetProposalService,
    ProviderTargetProposalUnavailableError,
)


class _ProposalRepository:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def create_or_get_proposal(self, **kwargs: object) -> dict[str, object]:
        self.calls.append(kwargs)
        return {"id": "proposal-1", **kwargs, "idempotent_replay": False}


class _Catalog:
    def __init__(self, details: dict[str, dict[str, object]]) -> None:
        self.details = details

    async def describe_provider(self, profile_id: str) -> dict[str, object]:
        detail = self.details.get(profile_id)
        if detail is None:
            raise ProviderCatalogNotFoundError("missing")
        return detail


class _AgentTasks:
    def __init__(self, task, chain) -> None:
        self.task = task
        self.chain = chain

    async def get_agent_task(self, agent_task_id: str):
        return self.task if agent_task_id == self.task.id else None

    async def get_agent_task_chain(self, root_task_id: str):
        return self.chain if root_task_id == "root-task" else []


def _task(*, screen_text: str | None = None):
    return SimpleNamespace(
        id="task-1",
        root_task_id="root-task",
        accumulated_artifacts={"reference_paths": ["/repo/a.py"]},
        screen_text=screen_text,
        app_name="Cursor" if screen_text else None,
        window_title="Basil" if screen_text else None,
    )


def _service(*, screen_text: str | None = None) -> tuple[ProviderTargetProposalService, _ProposalRepository]:
    repository = _ProposalRepository()
    task = _task(screen_text=screen_text)
    catalog = _Catalog(
        {
            "provider-a": {
                "workspace_candidates": [
                    {"workspace_grant_id": "grant-a"},
                ]
            },
            "provider-b": {
                "workspace_candidates": [
                    {"workspace_grant_id": "grant-b"},
                ]
            },
        }
    )
    return (
        ProviderTargetProposalService(
            proposal_repository=repository,
            provider_catalog_service=catalog,
            agent_task_service=_AgentTasks(task, [task, SimpleNamespace(id="prior-task")]),
        ),
        repository,
    )


def _proposal_kwargs() -> dict[str, object]:
    return {
        "agent_task_id": "task-1",
        "root_task_id": "root-task",
        "status": "proposed",
        "grounding_tier": "explicit_reference_or_chain_context",
        "confidence": "high",
        "provider_candidates": [
            {
                "provider_profile_id": "provider-a",
                "workspace_grant_id": "grant-a",
            }
        ],
        "service_candidates": [],
        "evidence": [
            {
                "source": "reference_path",
                "summary": "The user attached the repository file.",
                "reference": "/repo/a.py",
            },
            {
                "source": "provider_catalog",
                "summary": "The catalog returned the eligible provider.",
                "reference": "provider-a",
            },
        ],
        "exact_user_constraints": {
            "provider": None,
            "workspace": None,
            "service": None,
            "tool": None,
        },
        "rationale": "The attached reference is evidence for the selected authorized workspace.",
        "resolution_note": None,
    }


@pytest.mark.asyncio
async def test_service_records_bound_explicit_proposal(monkeypatch) -> None:
    service, repository = _service()
    monkeypatch.setattr(
        "api.services.agent_providers.catalog.target_proposal_service.load_external_catalog_preferences",
        lambda: SimpleNamespace(connections=SimpleNamespace(mcp_connections=[])),
    )

    result = await service.propose_target(**_proposal_kwargs())

    assert result["id"] == "proposal-1"
    assert len(repository.calls) == 1
    assert repository.calls[0]["provider_candidates"] == _proposal_kwargs()["provider_candidates"]
    assert repository.calls[0]["expires_at"] > datetime.utcnow().isoformat()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "updates, expected",
    [
        ({"status": "proposed", "provider_candidates": []}, "exactly one"),
        ({"status": "unavailable", "provider_candidates": _proposal_kwargs()["provider_candidates"], "resolution_note": "No inventory"}, "zero provider"),
        ({"status": "ambiguous", "grounding_tier": "inferred_native_context", "resolution_note": "Confirm the current project"}, None),
        ({"status": "proposed", "grounding_tier": "inferred_native_context", "confidence": "high"}, None),
        ({"status": "proposed", "grounding_tier": "inferred_native_context", "confidence": "medium"}, "requires high confidence"),
        ({"status": "proposed", "grounding_tier": "inferred_native_context", "confidence": "high", "exact_user_constraints": {"provider": "Named Provider", "workspace": None, "service": None, "tool": None}}, "must not carry exact user constraints"),
        ({"status": "conflicts_with_user_target", "resolution_note": "The user target is unavailable"}, "exact user constraint"),
    ],
)
async def test_status_and_grounding_contract(
    monkeypatch,
    updates: dict[str, object],
    expected: str | None,
) -> None:
    service, repository = _service(screen_text="Basil — Cursor")
    monkeypatch.setattr(
        "api.services.agent_providers.catalog.target_proposal_service.load_external_catalog_preferences",
        lambda: SimpleNamespace(connections=SimpleNamespace(mcp_connections=[])),
    )
    kwargs = _proposal_kwargs()
    kwargs.update(updates)
    if kwargs["grounding_tier"] == "inferred_native_context":
        kwargs["evidence"] = [
            {
                "source": "screen_context",
                "summary": "Cursor is visibly editing the project.",
                "reference": None,
            },
            {
                "source": "provider_catalog",
                "summary": "The catalog returned the eligible provider.",
                "reference": "provider-a",
            },
        ]
    if expected is None:
        await service.propose_target(**kwargs)
        assert repository.calls[0]["status"] == kwargs["status"]
    else:
        with pytest.raises(ProviderTargetProposalError, match=expected):
            await service.propose_target(**kwargs)


@pytest.mark.asyncio
async def test_evidence_and_live_catalog_candidates_fail_closed(monkeypatch) -> None:
    service, _ = _service()
    monkeypatch.setattr(
        "api.services.agent_providers.catalog.target_proposal_service.load_external_catalog_preferences",
        lambda: SimpleNamespace(connections=SimpleNamespace(mcp_connections=[])),
    )
    bad_reference = _proposal_kwargs()
    bad_reference["evidence"] = [
        {
            "source": "reference_path",
            "summary": "Invented path.",
            "reference": "/not-attached",
        },
        {
            "source": "provider_catalog",
            "summary": "The catalog returned the eligible provider.",
            "reference": "provider-a",
        },
    ]
    with pytest.raises(ProviderTargetProposalError, match="current task reference path"):
        await service.propose_target(**bad_reference)

    bad_provider = _proposal_kwargs()
    bad_provider["provider_candidates"] = [
        {
            "provider_profile_id": "provider-a",
            "workspace_grant_id": "grant-b",
        }
    ]
    with pytest.raises(
        ProviderTargetProposalUnavailableError,
        match="workspace is not currently authorized",
    ):
        await service.propose_target(**bad_provider)


@pytest.mark.asyncio
async def test_service_candidates_require_exact_enabled_cached_tool(monkeypatch) -> None:
    service, repository = _service()
    enabled = SimpleNamespace(
        id="github-a",
        enabled=True,
        cached_tools=[SimpleNamespace(name="run_tests")],
    )
    disabled = SimpleNamespace(
        id="github-b",
        enabled=False,
        cached_tools=[SimpleNamespace(name="run_tests")],
    )
    monkeypatch.setattr(
        "api.services.agent_providers.catalog.target_proposal_service.load_external_catalog_preferences",
        lambda: SimpleNamespace(
            connections=SimpleNamespace(mcp_connections=[enabled, disabled])
        ),
    )
    kwargs = _proposal_kwargs()
    kwargs["service_candidates"] = [
        {"connection_id": "github-a", "tool_name": "run_tests"}
    ]
    kwargs["evidence"] = [
        *_proposal_kwargs()["evidence"],
        {
            "source": "external_catalog",
            "summary": "The stored GitHub inventory includes run_tests.",
            "reference": "github-a",
        },
    ]
    await service.propose_target(**kwargs)
    assert repository.calls[0]["service_candidates"] == kwargs["service_candidates"]

    kwargs["service_candidates"] = [
        {"connection_id": "github-b", "tool_name": "run_tests"}
    ]
    kwargs["evidence"] = [
        *_proposal_kwargs()["evidence"],
        {
            "source": "external_catalog",
            "summary": "The stored GitHub inventory includes run_tests.",
            "reference": "github-b",
        },
    ]
    with pytest.raises(ProviderTargetProposalUnavailableError, match="not enabled"):
        await service.propose_target(**kwargs)

    kwargs["service_candidates"] = [
        {"connection_id": "github-a", "tool_name": "invented_tool"}
    ]
    kwargs["evidence"] = [
        *_proposal_kwargs()["evidence"],
        {
            "source": "external_catalog",
            "summary": "The stored GitHub inventory was inspected.",
            "reference": "github-a",
        },
    ]
    with pytest.raises(ProviderTargetProposalUnavailableError, match="not in the stored"):
        await service.propose_target(**kwargs)


@pytest.mark.asyncio
async def test_exact_target_conflict_and_inferred_context_remain_non_authorizing(monkeypatch) -> None:
    service, repository = _service(screen_text="Basil — Cursor")
    monkeypatch.setattr(
        "api.services.agent_providers.catalog.target_proposal_service.load_external_catalog_preferences",
        lambda: SimpleNamespace(connections=SimpleNamespace(mcp_connections=[])),
    )
    kwargs = _proposal_kwargs()
    kwargs.update(
        {
            "status": "conflicts_with_user_target",
            "grounding_tier": "exact_user_target",
            "confidence": "high",
            "provider_candidates": [],
            "evidence": [
                {
                    "source": "user_request",
                    "summary": "The user explicitly named a provider that is unavailable.",
                    "reference": None,
                }
            ],
            "exact_user_constraints": {
                "provider": "Unavailable Provider",
                "workspace": None,
                "service": None,
                "tool": None,
            },
            "resolution_note": "The explicitly named provider is not registered.",
        }
    )

    await service.propose_target(**kwargs)

    assert repository.calls[0]["status"] == "conflicts_with_user_target"
    assert repository.calls[0]["exact_user_constraints"]["provider"] == "Unavailable Provider"
    assert not hasattr(repository, "delegate")
    assert not hasattr(repository, "authorize")


@pytest.mark.asyncio
async def test_fresh_schema_contains_proposal_table_indexes_and_reinitializes(tmp_path) -> None:
    db_path = tmp_path / "proposal-schema.db"
    SQLiteKnowledgeService(db_path)

    with sqlite3.connect(db_path) as conn:
        conn.execute("DROP TABLE provider_discovery_proposals")
        conn.commit()

    SchemaManager(str(db_path)).initialize_db()

    with sqlite3.connect(db_path) as conn:
        table = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
            ("provider_discovery_proposals",),
        ).fetchone()
        indexes = {
            row[0]
            for row in conn.execute(
                """
                SELECT name FROM sqlite_master
                WHERE type = 'index'
                  AND name IN (?, ?)
                """,
                (
                    "idx_provider_discovery_task_fingerprint",
                    "idx_provider_discovery_task_created",
                ),
            ).fetchall()
        }
        columns = {
            row[1]
            for row in conn.execute(
                "PRAGMA table_info(provider_discovery_proposals)"
            ).fetchall()
        }

    assert table == ("provider_discovery_proposals",)
    assert indexes == {
        "idx_provider_discovery_task_fingerprint",
        "idx_provider_discovery_task_created",
    }
    assert {
        "agent_task_id",
        "root_task_id",
        "proposal_fingerprint",
        "expires_at",
    }.issubset(columns)


@pytest.mark.asyncio
async def test_fresh_schema_also_contains_authorization_table_and_indexes(tmp_path) -> None:
    db_path = tmp_path / "proposal-and-authorization-schema.db"
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
async def test_repository_is_idempotent_bound_and_malformed_rows_fail_closed(tmp_path) -> None:
    knowledge = SQLiteKnowledgeService(tmp_path / "proposal.db")
    await knowledge.store_agent_task(
        agent_task_id="root-task",
        original_prompt="Root",
        transcribed_prompt="Root",
    )
    repository = knowledge.provider_discovery_proposal_repository
    payload = {
        "agent_task_id": "root-task",
        "root_task_id": "root-task",
        "status": "unavailable",
        "grounding_tier": "insufficient",
        "confidence": "low",
        "provider_candidates": [],
        "service_candidates": [],
        "evidence": [{"source": "user_request", "summary": "User asked.", "reference": None}],
        "exact_user_constraints": {"provider": None, "workspace": None, "service": None, "tool": None},
        "rationale": "No eligible provider is registered.",
        "resolution_note": "Register and enable a provider.",
        "expires_at": "2099-01-01T00:00:00",
    }
    first = await repository.create_or_get_proposal(**payload)
    second = await repository.create_or_get_proposal(**payload)
    assert first["id"] == second["id"]
    assert second["idempotent_replay"] is True

    with pytest.raises(ProviderDiscoveryProposalConflictError, match="does not exist"):
        await repository.create_or_get_proposal(
            **{**payload, "agent_task_id": "missing-task"}
        )

    with sqlite3.connect(knowledge.db_path) as conn:
        conn.execute(
            "UPDATE provider_discovery_proposals SET evidence_json = ? WHERE id = ?",
            ("{", first["id"]),
        )
        conn.commit()
    with pytest.raises(
        ProviderDiscoveryProposalPersistenceError,
        match="evidence_json contains invalid JSON",
    ):
        await repository.get_proposal(str(first["id"]))


@pytest.mark.asyncio
async def test_proposals_cascade_when_the_task_chain_is_deleted(tmp_path) -> None:
    knowledge = SQLiteKnowledgeService(tmp_path / "proposal-cascade.db")
    await knowledge.store_agent_task(
        agent_task_id="root-task",
        original_prompt="Root",
        transcribed_prompt="Root",
    )
    await knowledge.store_agent_task(
        agent_task_id="child-task",
        original_prompt="Child",
        transcribed_prompt="Child",
        root_task_id="root-task",
        previous_task_id="root-task",
        chain_sequence_number=1,
    )
    proposal = await knowledge.provider_discovery_proposal_repository.create_or_get_proposal(
        agent_task_id="child-task",
        root_task_id="root-task",
        status="unavailable",
        grounding_tier="insufficient",
        confidence="low",
        provider_candidates=[],
        service_candidates=[],
        evidence=[
            {"source": "user_request", "summary": "User requested delegation.", "reference": None}
        ],
        exact_user_constraints={
            "provider": None,
            "workspace": None,
            "service": None,
            "tool": None,
        },
        rationale="No eligible provider is registered.",
        resolution_note="Register and enable a provider.",
        expires_at="2099-01-01T00:00:00",
    )

    assert await knowledge.agent_task_service.delete_agent_task("root-task")
    assert await knowledge.provider_discovery_proposal_repository.get_proposal(
        str(proposal["id"])
    ) is None
