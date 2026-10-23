"""Focused coverage for Package 5D.1 provider catalog discovery."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from api.core.knowledge.sqlite.sqlite_knowledge_service import SQLiteKnowledgeService
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.infrastructure.connection import (
    get_sync_connection,
)
from api.services.agent_processing.lifecycle.execution_graph.service_tooling.optional_tool_registry import (
    register_optional_tools,
)
from api.services.agent_processing.tools.internal_basil_tools import provider_catalog_tool
from api.services.agent_processing.tools.internal_basil_tools.provider_catalog_tool import (
    create_provider_catalog_tool,
)
from api.services.agent_providers.targeting.delegation_service import (
    ProviderDelegationWaitRequest,
)
from api.services.agent_providers.catalog.catalog_service import (
    ProviderCatalogNotFoundError,
    ProviderCatalogService,
    ProviderCatalogUnavailableError,
)
from api.services.agent_providers.catalog.target_proposal_service import (
    ProviderTargetProposalUnavailableError,
)


class _FakeLogger:
    def info(self, *_args, **_kwargs) -> None:
        pass

    def warning(self, *_args, **_kwargs) -> None:
        pass


class _FakeProfileRepository:
    def __init__(self, profiles: list[dict[str, object]], grants: dict[str, list[dict[str, object]]]) -> None:
        self.profiles = {str(profile["id"]): profile for profile in profiles}
        self.profile_order = [str(profile["id"]) for profile in profiles]
        self.grants = grants

    async def list_profile_ids(self, *, include_removed: bool = False) -> list[str]:
        if include_removed:
            return list(self.profile_order)
        return [
            profile_id
            for profile_id in self.profile_order
            if self.profiles[profile_id].get("status") != "removed"
        ]

    async def get_profile(self, provider_profile_id: str) -> dict[str, object] | None:
        return self.profiles.get(provider_profile_id)

    async def list_workspace_grants_for_profile(
        self,
        provider_profile_id: str,
        *,
        include_revoked: bool = False,
    ) -> list[dict[str, object]]:
        records = list(self.grants.get(provider_profile_id, []))
        if include_revoked:
            return records
        return [record for record in records if record.get("status") == "active"]


class _FakeRunRepository:
    def __init__(self, latest_runs: dict[str, dict[str, object] | None] | None = None) -> None:
        self.latest_runs = latest_runs or {}

    async def get_latest_run_for_profile(
        self,
        provider_profile_id: str,
    ) -> dict[str, object] | None:
        return self.latest_runs.get(provider_profile_id)


def _profile(
    profile_id: str,
    *,
    status: str = "enabled",
    launch_argv: tuple[str, ...] = ("fixture-acp", "--stdio"),
    description: str | None = None,
    routing_hints: tuple[str, ...] = (),
) -> dict[str, object]:
    return {
        "id": profile_id,
        "display_name": f"Provider {profile_id}",
        "transport": "acp_stdio",
        "launch_argv": launch_argv,
        "environment_allowlist": ("PATH",),
        "status": status,
        "capability_state": "unverified",
        "description": description,
        "routing_hints": routing_hints,
        "revision": 0,
        "created_at": "2026-08-04T00:00:00",
        "updated_at": "2026-08-04T00:00:00",
        "removed_at": None,
    }


def _grant(
    grant_id: str,
    profile_id: str,
    *,
    status: str = "active",
    description: str | None = None,
    routing_hints: tuple[str, ...] = (),
) -> dict[str, object]:
    return {
        "id": grant_id,
        "provider_profile_id": profile_id,
        "canonical_workspace_root": f"/private/authorized/{grant_id}",
        "status": status,
        "workspace_label": f"Workspace {grant_id}",
        "description": description,
        "routing_hints": routing_hints,
        "revision": 0,
        "created_at": "2026-08-04T00:00:00",
        "updated_at": "2026-08-04T00:00:00",
        "revoked_at": None,
    }


def _service(
    profiles: list[dict[str, object]],
    grants: dict[str, list[dict[str, object]]],
    latest_runs: dict[str, dict[str, object] | None] | None = None,
) -> ProviderCatalogService:
    return ProviderCatalogService(
        _FakeProfileRepository(profiles, grants),
        _FakeRunRepository(latest_runs),
    )


@pytest.mark.asyncio
async def test_list_returns_only_enabled_valid_profiles_with_active_grants() -> None:
    profiles = [
        _profile(
            "eligible",
            description="Use token=super-secret for repository work at /Users/fixture/repository or ./fixture/repository",
            routing_hints=(
                "GitHub ghp_123456789secret",
                "file:///private/fixture/repository",
                "https://github.com/example/provider",
            ),
        ),
        _profile("disabled", status="disabled"),
        _profile("removed", status="removed"),
        _profile("invalid", launch_argv=()),
        _profile("no-grant"),
    ]
    service = _service(
        profiles,
        {
            "eligible": [
                _grant(
                    "grant-eligible",
                    "eligible",
                    description="Credential=hidden-value workspace at ~/fixture/repository",
                    routing_hints=("Primary repository", "C:\\fixture\\repository"),
                )
            ],
            "disabled": [_grant("grant-disabled", "disabled")],
            "removed": [_grant("grant-removed", "removed")],
            "invalid": [_grant("grant-invalid", "invalid")],
        },
    )

    result = await service.list_providers()

    assert result["total_eligible"] == 1
    assert result["next_offset"] is None
    providers = result["providers"]
    assert isinstance(providers, list)
    assert [provider["provider_profile_id"] for provider in providers] == ["eligible"]
    encoded = json.dumps(result)
    assert "super-secret" not in encoded
    assert "ghp_123456789secret" not in encoded
    assert "hidden-value" not in encoded
    assert "[redacted]" in encoded
    assert "/Users/fixture/repository" not in encoded
    assert "file:///private/fixture/repository" not in encoded
    assert "~/fixture/repository" not in encoded
    assert "./fixture/repository" not in encoded
    assert "C:\\fixture\\repository" not in encoded
    assert "https://github.com/example/provider" in encoded
    assert "canonical_workspace_root" not in encoded
    assert "/private/authorized" not in encoded
    assert "launch_argv" not in encoded
    assert "environment_allowlist" not in encoded


@pytest.mark.asyncio
async def test_list_is_bounded_and_paginated_after_eligibility_filtering() -> None:
    profiles = [_profile("p1"), _profile("disabled", status="disabled"), _profile("p2")]
    service = _service(
        profiles,
        {
            "p1": [_grant("g1", "p1")],
            "disabled": [_grant("gd", "disabled")],
            "p2": [_grant("g2", "p2")],
        },
    )

    first = await service.list_providers(offset=0, limit=1)
    second = await service.list_providers(offset=1, limit=1)

    assert first["total_eligible"] == 2
    assert first["next_offset"] == 1
    assert [item["provider_profile_id"] for item in first["providers"]] == ["p1"]
    assert second["next_offset"] is None
    assert [item["provider_profile_id"] for item in second["providers"]] == ["p2"]


@pytest.mark.asyncio
async def test_describe_distinguishes_unverified_from_observed_capabilities() -> None:
    service = _service(
        [_profile("observed"), _profile("unverified")],
        {
            "observed": [_grant("g-observed", "observed")],
            "unverified": [_grant("g-unverified", "unverified")],
        },
        {
            "observed": {
                "capabilities": {
                    "loadSession": True,
                    "workingDirectory": "/private/user/repository",
                    "token": "provider-secret",
                    "nested": {"mode": "safe"},
                }
            },
            "unverified": None,
        },
    )

    observed = await service.describe_provider("observed")
    unverified = await service.describe_provider("unverified")

    assert observed["capability_state"] == "observed"
    assert observed["observed_capabilities"] == {
        "loadSession": True,
        "workingDirectory": "[redacted path]",
        "token": "[redacted]",
        "nested": {"mode": "safe"},
    }
    assert unverified["capability_state"] == "unverified"
    assert unverified["observed_capabilities"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("profile", "grants", "reason_code"),
    [
        (_profile("disabled", status="disabled"), [_grant("gd", "disabled")], "disabled"),
        (_profile("removed", status="removed"), [_grant("gr", "removed")], "removed"),
        (_profile("invalid", launch_argv=()), [_grant("gi", "invalid")], "invalid_profile"),
        (_profile("unknown-status", status="unknown"), [_grant("gs", "unknown-status")], "invalid_profile"),
        (_profile("no-grant"), [], "no_active_workspace_grants"),
    ],
)
async def test_describe_returns_fixed_unavailable_reasons(
    profile: dict[str, object],
    grants: list[dict[str, object]],
    reason_code: str,
) -> None:
    service = _service([profile], {str(profile["id"]): grants})

    with pytest.raises(ProviderCatalogUnavailableError) as exc_info:
        await service.describe_provider(str(profile["id"]))

    assert exc_info.value.reason_code == reason_code
    assert exc_info.value.user_action_required


@pytest.mark.asyncio
async def test_describe_rejects_an_invented_profile_id() -> None:
    service = _service([], {})

    with pytest.raises(ProviderCatalogNotFoundError):
        await service.describe_provider("invented-provider")


@pytest.mark.asyncio
async def test_describe_revalidates_live_state_instead_of_trusting_a_prior_list() -> None:
    profile = _profile("stale")
    profile_repository = _FakeProfileRepository(
        [profile],
        {"stale": [_grant("g-stale", "stale")]},
    )
    service = ProviderCatalogService(profile_repository, _FakeRunRepository())
    listed = await service.list_providers()
    assert listed["total_eligible"] == 1

    profile["status"] = "disabled"

    with pytest.raises(ProviderCatalogUnavailableError) as exc_info:
        await service.describe_provider("stale")
    assert exc_info.value.reason_code == "disabled"


@pytest.mark.asyncio
async def test_describe_rejects_malformed_observed_capabilities() -> None:
    service = _service(
        [_profile("malformed-observed")],
        {"malformed-observed": [_grant("g-malformed", "malformed-observed")]},
        {"malformed-observed": {"capabilities": ["not", "a", "mapping"]}},
    )

    with pytest.raises(ProviderCatalogUnavailableError) as exc_info:
        await service.describe_provider("malformed-observed")

    assert exc_info.value.reason_code == "invalid_observed_capabilities"


@pytest.mark.asyncio
async def test_tool_returns_structured_success_not_found_and_unavailable_envelopes(monkeypatch) -> None:
    service = _service(
        [_profile("eligible"), _profile("disabled", status="disabled")],
        {
            "eligible": [_grant("g-eligible", "eligible")],
            "disabled": [_grant("g-disabled", "disabled")],
        },
    )
    monkeypatch.setattr(
        provider_catalog_tool,
        "_get_provider_catalog_service",
        lambda: service,
    )
    tool = create_provider_catalog_tool()

    listed = json.loads(await tool.ainvoke({"action": "list_providers"}))
    described = json.loads(
        await tool.ainvoke(
            {
                "action": "describe_provider",
                "provider_profile_id": "eligible",
            }
        )
    )
    unavailable = json.loads(
        await tool.ainvoke(
            {
                "action": "describe_provider",
                "provider_profile_id": "disabled",
            }
        )
    )
    missing = json.loads(
        await tool.ainvoke(
            {
                "action": "describe_provider",
                "provider_profile_id": "invented",
            }
        )
    )

    assert listed["ok"] is True
    assert described["ok"] is True
    assert unavailable["error"]["kind"] == "unavailable"
    assert unavailable["error"]["reason_code"] == "disabled"
    assert missing["error"]["kind"] == "not_found"


def test_provider_catalog_is_registered_as_a_distinct_optional_tool() -> None:
    tools = []
    tool_map = {}
    optional_warnings = []
    factory = SimpleNamespace(
        logger=_FakeLogger(),
        profile=None,
        current_agent_task_id="task-1",
        current_root_task_id="root-task",
    )

    register_optional_tools(factory, tools, tool_map, optional_warnings)

    assert "provider.catalog" in tool_map
    assert tool_map["provider.catalog"].name == "provider_catalog"
    assert tool_map["provider.catalog"] is not tool_map["external.catalog"]
    schema = tool_map["provider.catalog"].args_schema.model_json_schema()
    assert "agent_task_id" not in schema["properties"]
    assert "root_task_id" not in schema["properties"]
    assert "authorize_target" in schema["properties"]["action"]["enum"]
    assert "resolve_target_authorization" in schema["properties"]["action"]["enum"]


def test_delegated_provider_continuation_omits_provider_catalog_only() -> None:
    tools = []
    tool_map = {}
    optional_warnings = []
    factory = SimpleNamespace(
        logger=_FakeLogger(),
        profile=None,
        current_agent_task_id="task-1",
        current_root_task_id="root-task",
        allow_provider_catalog=False,
    )

    register_optional_tools(factory, tools, tool_map, optional_warnings)

    assert "provider.catalog" not in tool_map
    assert "external.catalog" in tool_map


@pytest.mark.asyncio
async def test_repository_lists_ids_without_decoding_malformed_profiles(tmp_path) -> None:
    service = SQLiteKnowledgeService(tmp_path / "provider_catalog.db")
    active = await service.provider_profile_repository.create_profile(
        display_name="Active",
        launch_argv=("fixture-acp",),
    )
    await service.provider_profile_repository.grant_workspace(
        provider_profile_id=str(active["id"]),
        canonical_workspace_root="/private/provider-catalog-active",
    )
    malformed = await service.provider_profile_repository.create_profile(
        display_name="Malformed",
        launch_argv=("fixture-acp",),
    )
    with get_sync_connection(service.db_path) as conn:
        conn.execute(
            "UPDATE provider_profiles SET launch_argv_json = ? WHERE id = ?",
            ("{", str(malformed["id"])),
        )
        conn.commit()

    visible_ids = await service.provider_profile_repository.list_profile_ids()
    all_ids = await service.provider_profile_repository.list_profile_ids(include_removed=True)
    catalog = await ProviderCatalogService(
        service.provider_profile_repository,
        service.provider_run_repository,
    ).list_providers()

    assert set(visible_ids) == {str(active["id"]), str(malformed["id"])}
    assert set(all_ids) == {str(active["id"]), str(malformed["id"])}
    assert [provider["provider_profile_id"] for provider in catalog["providers"]] == [
        str(active["id"])
    ]


@pytest.mark.asyncio
async def test_propose_target_uses_captured_ids_and_never_dispatches(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class _ProposalService:
        async def propose_target(self, **kwargs: object) -> dict[str, object]:
            captured.update(kwargs)
            return {"id": "proposal-1", "status": kwargs["status"]}

    monkeypatch.setattr(
        provider_catalog_tool,
        "_get_provider_target_proposal_service",
        lambda: _ProposalService(),
    )
    tool = create_provider_catalog_tool(
        agent_task_id="captured-task",
        root_task_id="captured-root",
    )
    result = json.loads(
        await tool.ainvoke(
            {
                "action": "propose_target",
                "proposal_status": "unavailable",
                "grounding_tier": "insufficient",
                "confidence": "low",
                "provider_candidates": [],
                "service_candidates": [],
                "evidence": [
                    {
                        "source": "user_request",
                        "summary": "The user asked for delegation.",
                        "reference": None,
                    }
                ],
                "exact_user_constraints": {
                    "provider": None,
                    "workspace": None,
                    "service": None,
                    "tool": None,
                },
                "rationale": "No eligible provider is registered.",
                "resolution_note": "Register a provider in Settings.",
            }
        )
    )

    assert result == {
        "ok": True,
        "result": {"id": "proposal-1", "status": "unavailable"},
    }
    assert captured["agent_task_id"] == "captured-task"
    assert captured["root_task_id"] == "captured-root"
    assert "non-activating" in tool.description.lower()


@pytest.mark.asyncio
async def test_propose_target_requires_captured_task_and_preserves_unavailable_envelope(
    monkeypatch,
) -> None:
    missing_context_tool = create_provider_catalog_tool()
    request = {
        "action": "propose_target",
        "proposal_status": "unavailable",
        "grounding_tier": "insufficient",
        "confidence": "low",
        "provider_candidates": [],
        "service_candidates": [],
        "evidence": [
            {
                "source": "user_request",
                "summary": "The user asked for delegation.",
                "reference": None,
            }
        ],
        "exact_user_constraints": {
            "provider": None,
            "workspace": None,
            "service": None,
            "tool": None,
        },
        "rationale": "No eligible provider is registered.",
        "resolution_note": "Register a provider in Settings.",
    }
    missing_context = json.loads(await missing_context_tool.ainvoke(request))
    assert missing_context["error"]["kind"] == "invalid_arguments"

    class _UnavailableProposalService:
        async def propose_target(self, **_kwargs: object) -> dict[str, object]:
            raise ProviderTargetProposalUnavailableError(
                reason_code="invalid_provider_candidate",
                message="The proposed provider is not currently eligible.",
            )

    monkeypatch.setattr(
        provider_catalog_tool,
        "_get_provider_target_proposal_service",
        lambda: _UnavailableProposalService(),
    )
    unavailable_tool = create_provider_catalog_tool(
        agent_task_id="task-1",
        root_task_id="root-task",
    )
    unavailable = json.loads(await unavailable_tool.ainvoke(request))
    assert unavailable == {
        "ok": False,
        "error": {
            "kind": "unavailable",
            "message": "The proposed provider is not currently eligible.",
            "retryable": False,
            "user_action_required": None,
            "reason_code": "invalid_provider_candidate",
        },
    }


@pytest.mark.asyncio
async def test_authorize_and_resolve_use_captured_ids_without_paths(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class _AuthorizationService:
        async def authorize_proposal(self, **kwargs: object) -> dict[str, object]:
            captured["authorize"] = kwargs
            return {
                "id": "auth-1",
                "status": "needs_user",
                "checkpoint": {
                    "checkpoint_id": "auth-1",
                    "input_type": "choice",
                    "prompt": "Choose a target",
                    "options": [{"id": "o1", "label": "Fixture", "value": "target-choice:1"}],
                    "metadata": {
                        "source": "provider_target_authorization",
                        "authorization_id": "auth-1",
                        "cancel_value": "target-cancel:1",
                    },
                },
            }

        async def resolve_checkpoint_response(self, **kwargs: object) -> dict[str, object]:
            captured["resolve"] = kwargs
            return {"id": "auth-2", "status": "authorized", "reason_code": "user_selected_verified_target"}

    monkeypatch.setattr(
        provider_catalog_tool,
        "_get_provider_target_authorization_service",
        lambda: _AuthorizationService(),
    )
    tool = create_provider_catalog_tool(
        agent_task_id="captured-task",
        root_task_id="captured-root",
    )
    authorized = json.loads(
        await tool.ainvoke(
            {
                "action": "authorize_target",
                "proposal_id": "proposal-1",
            }
        )
    )
    resolved = json.loads(
        await tool.ainvoke(
            {
                "action": "resolve_target_authorization",
                "authorization_id": "auth-1",
                "checkpoint_response": "target-choice:1",
            }
        )
    )

    assert authorized["ok"] is True
    assert "checkpoint" in authorized["result"]
    assert "/private" not in json.dumps(authorized)
    assert captured["authorize"] == {
        "agent_task_id": "captured-task",
        "root_task_id": "captured-root",
        "proposal_id": "proposal-1",
    }
    assert captured["resolve"] == {
        "agent_task_id": "captured-task",
        "root_task_id": "captured-root",
        "authorization_id": "auth-1",
        "response": "target-choice:1",
    }
    assert resolved["ok"] is True
    assert "authorize" in tool.description.lower()
    assert "checkpoint" in tool.description.lower()


@pytest.mark.asyncio
async def test_delegate_uses_captured_identity_and_returns_only_bounded_handle(
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}

    class _DelegationService:
        async def delegate_authorization(self, **kwargs: object) -> dict[str, object]:
            captured.update(kwargs)
            return {
                "ok": True,
                "delegation_id": "delegation-1",
                "child_agent_task_id": "child-1",
                "status": "submitted",
                "provider_profile_id": "profile-1",
                "workspace_grant_id": "grant-1",
                "selected_connection_id": "connection-1",
                "selected_tool_name": "tool-1",
                "reason_code": None,
                "idempotent_replay": False,
            }

    submission_service = object()

    def _delegation_factory(received_submission_service: object) -> _DelegationService:
        captured["submission_service"] = received_submission_service
        return _DelegationService()

    monkeypatch.setattr(
        provider_catalog_tool,
        "_get_provider_target_delegation_service",
        _delegation_factory,
    )
    tool = create_provider_catalog_tool(
        agent_task_id="captured-task",
        root_task_id="captured-root",
        submission_service=submission_service,
    )
    result = json.loads(
        await tool.ainvoke(
            {
                "action": "delegate",
                "authorization_id": "authorization-1",
            }
        )
    )

    assert result["ok"] is True
    assert result["result"]["delegation_id"] == "delegation-1"
    assert result["result"]["child_agent_task_id"] == "child-1"
    assert captured["submission_service"] is submission_service
    assert captured["agent_task_id"] == "captured-task"
    assert captured["root_task_id"] == "captured-root"
    assert captured["authorization_id"] == "authorization-1"
    assert "workspace_path" not in json.dumps(result)
    assert "credential" not in json.dumps(result)


@pytest.mark.asyncio
async def test_delegate_propagates_the_dedicated_workflow_wait_request(
    monkeypatch,
) -> None:
    class _DelegationService:
        async def delegate_authorization(self, **_kwargs: object) -> dict[str, object]:
            raise ProviderDelegationWaitRequest(
                delegation_id="delegation-1",
                child_agent_task_id="child-1",
            )

    monkeypatch.setattr(
        provider_catalog_tool,
        "_get_provider_target_delegation_service",
        lambda _submission_service: _DelegationService(),
    )
    tool = create_provider_catalog_tool(
        agent_task_id="captured-task",
        root_task_id="captured-root",
        submission_service=object(),
    )

    with pytest.raises(ProviderDelegationWaitRequest):
        await tool.ainvoke(
            {
                "action": "delegate",
                "authorization_id": "authorization-1",
            }
        )


@pytest.mark.asyncio
async def test_delegate_fails_closed_without_submission_ownership() -> None:
    tool = create_provider_catalog_tool(
        agent_task_id="captured-task",
        root_task_id="captured-root",
    )
    result = json.loads(
        await tool.ainvoke(
            {
                "action": "delegate",
                "authorization_id": "authorization-1",
            }
        )
    )

    assert result == {
        "ok": False,
        "error": {
            "kind": "unavailable",
            "message": "Provider delegation is unavailable in this workflow.",
            "retryable": False,
            "user_action_required": None,
            "reason_code": "delegation_submission_unavailable",
        },
    }
