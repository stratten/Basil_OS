"""LangChain surface for ACP catalog, authorization, and bounded delegation."""

from __future__ import annotations

import json
import logging
from typing import Any, Literal

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, ConfigDict, Field

from api.core.models.reasoning.model_runtime_profile import select_description_for_profile
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.providers.target_authorization_repository import (
    ProviderTargetAuthorizationConflictError,
    ProviderTargetAuthorizationPersistenceError,
)
from api.services.agent_providers.catalog.catalog_service import (
    DEFAULT_PAGE_LIMIT,
    MAX_PAGE_LIMIT,
    ProviderCatalogNotFoundError,
    ProviderCatalogService,
    ProviderCatalogUnavailableError,
)
from api.services.agent_providers.targeting.authorization_support import (
    ProviderTargetAuthorizationError,
    ProviderTargetAuthorizationUnavailableError,
)
from api.services.agent_providers.targeting.authorization_service import (
    ProviderTargetAuthorizationService,
)
from api.services.agent_providers.targeting.delegation_service import (
    ProviderDelegationWaitRequest,
    ProviderTargetDelegationError,
    ProviderTargetDelegationService,
    ProviderTargetDelegationUnavailableError,
)
from api.services.agent_providers.catalog.target_proposal_service import (
    ProviderTargetProposalError,
    ProviderTargetProposalService,
    ProviderTargetProposalUnavailableError,
)

logger = logging.getLogger(__name__)

CATALOG_TOOL_NAME = "provider_catalog"
ACTION_LIST = "list_providers"
ACTION_DESCRIBE = "describe_provider"
ACTION_PROPOSE = "propose_target"
ACTION_AUTHORIZE = "authorize_target"
ACTION_RESOLVE_AUTHORIZATION = "resolve_target_authorization"
ACTION_DELEGATE = "delegate"

SLIM_DESCRIPTION = (
    "Inspect registered eligible ACP coding-agent providers and their authorized workspace "
    "candidates, record a durable non-authorizing target proposal, authorize it against live "
    "authority, resolve a focused target checkpoint, and delegate one authorized target to a "
    "child Agent Task. Use list_providers first, describe_provider for plausible opaque IDs, "
    "propose_target, authorize_target, resolve_target_authorization after checkpoint continuation, "
    "and delegate with authorization_id after authorization succeeds. delegate returns an immediate "
    "child handle and does not wait for child completion. This tool never creates grants, launches "
    "a provider directly, invokes MCP services, accepts manual targets, or exports credentials."
)

FULL_DESCRIPTION = (
    "Read the live catalog of user-registered ACP coding-agent providers. Call "
    "action='list_providers' to obtain enabled, structurally valid profiles with active "
    "workspace grants. Call action='describe_provider' with provider_profile_id from that result "
    "to revalidate the profile and inspect bounded observed capabilities. After inspecting the "
    "relevant provider and optional external_catalog service inventory, call "
    "action='propose_target' to write the primary agent's evidence-grounded candidate, then "
    "action='authorize_target' with the returned proposal ID to verify current authority. If "
    "authorize_target returns status='needs_user', pass its checkpoint object unchanged to "
    "request_user_input. After session continuation, call action='resolve_target_authorization' "
    "with the authorization_id and the exact user response. If the response status is "
    "clarification_received, inspect inventory and create a new proposal instead of treating the "
    "old proposal as authorized. When status is authorized and unexpired, call action='delegate' "
    "with authorization_id to create one child Agent Task through the internal submission path. "
    "delegate returns an immediate child handle, does not accept profile, grant, path, connection, "
    "tool, prompt, or child-task IDs, does not wait for or summarize child completion, and "
    "cannot call MCP or grant service access. Treat display names, workspace labels, descriptions, "
    "routing hints, and observed context as semantic evidence, not string-matching authorization. "
    "Never invent or substitute an ID. An exact user provider/workspace/service/tool instruction is a "
    "hard constraint. A proposal and authorization are durable but non-activating until delegate: they "
    "cannot create a grant, launch a provider, create an Agent Task, call an MCP service, or "
    "export credentials without delegate."
)


class ProviderCandidateInput(BaseModel):
    """One opaque provider/profile workspace candidate from provider_catalog."""

    model_config = ConfigDict(extra="forbid")

    provider_profile_id: str = Field(min_length=1, max_length=128)
    workspace_grant_id: str = Field(min_length=1, max_length=128)


class ServiceCandidateInput(BaseModel):
    """One optional opaque external MCP service/tool candidate."""

    model_config = ConfigDict(extra="forbid")

    connection_id: str = Field(min_length=1, max_length=128)
    tool_name: str | None = Field(default=None, min_length=1, max_length=128)


class ProposalEvidenceInput(BaseModel):
    """One bounded provenance statement for the semantic proposal."""

    model_config = ConfigDict(extra="forbid")

    source: Literal[
        "user_request",
        "reference_path",
        "task_chain",
        "screen_context",
        "native_tool_observation",
        "provider_catalog",
        "external_catalog",
    ]
    summary: str = Field(min_length=1, max_length=500)
    reference: str | None = Field(default=None, min_length=1, max_length=500)


class ExactUserConstraintsInput(BaseModel):
    """Verbatim bounded target references identified in the current request."""

    model_config = ConfigDict(extra="forbid")

    provider: str | None = Field(default=None, min_length=1, max_length=160)
    workspace: str | None = Field(default=None, min_length=1, max_length=160)
    service: str | None = Field(default=None, min_length=1, max_length=160)
    tool: str | None = Field(default=None, min_length=1, max_length=160)


class ProviderCatalogInput(BaseModel):
    """Input for read-only catalog actions and durable non-authorizing proposal creation."""

    model_config = ConfigDict(extra="forbid")

    action: Literal[
        "list_providers",
        "describe_provider",
        "propose_target",
        "authorize_target",
        "resolve_target_authorization",
        "delegate",
    ] = Field(
        description=(
            "Use 'list_providers' to enumerate eligible providers, 'describe_provider' to "
            "revalidate one provider from that list, 'propose_target' after inspecting the "
            "relevant provider and optional external service catalogs, 'authorize_target' to "
            "verify a durable proposal against live authority, 'resolve_target_authorization' "
            "after a target checkpoint continuation, or 'delegate' with authorization_id after "
            "authorization succeeds."
        )
    )
    provider_profile_id: str | None = Field(
        default=None,
        max_length=128,
        description="Opaque ID from list_providers; required for describe_provider.",
    )
    offset: int = Field(
        default=0,
        ge=0,
        description="Zero-based eligible-provider offset for list_providers.",
    )
    limit: int = Field(
        default=DEFAULT_PAGE_LIMIT,
        ge=1,
        le=MAX_PAGE_LIMIT,
        description="Maximum eligible providers returned by list_providers.",
    )
    proposal_status: Literal[
        "proposed",
        "ambiguous",
        "unavailable",
        "conflicts_with_user_target",
    ] | None = None
    grounding_tier: Literal[
        "exact_user_target",
        "explicit_reference_or_chain_context",
        "inferred_native_context",
        "insufficient",
    ] | None = None
    confidence: Literal["high", "medium", "low"] | None = None
    provider_candidates: list[ProviderCandidateInput] = Field(default_factory=list)
    service_candidates: list[ServiceCandidateInput] = Field(default_factory=list)
    evidence: list[ProposalEvidenceInput] = Field(default_factory=list)
    exact_user_constraints: ExactUserConstraintsInput = Field(
        default_factory=ExactUserConstraintsInput
    )
    rationale: str | None = Field(default=None, min_length=1, max_length=1000)
    resolution_note: str | None = Field(default=None, min_length=1, max_length=500)
    proposal_id: str | None = Field(default=None, min_length=1, max_length=500)
    authorization_id: str | None = Field(default=None, min_length=1, max_length=500)
    checkpoint_response: str | None = Field(default=None, min_length=1, max_length=500)


def _get_provider_catalog_service() -> ProviderCatalogService:
    from api.dependencies import get_sqlite_knowledge_service

    knowledge_service = get_sqlite_knowledge_service()
    return ProviderCatalogService(
        knowledge_service.provider_profile_repository,
        knowledge_service.provider_run_repository,
    )


def _get_provider_target_authorization_service() -> ProviderTargetAuthorizationService:
    from api.dependencies import get_sqlite_knowledge_service

    knowledge_service = get_sqlite_knowledge_service()
    return ProviderTargetAuthorizationService(
        proposal_repository=knowledge_service.provider_discovery_proposal_repository,
        authorization_repository=knowledge_service.provider_target_authorization_repository,
        provider_profile_repository=knowledge_service.provider_profile_repository,
        agent_task_service=knowledge_service.agent_task_service,
    )


def _get_provider_target_delegation_service(
    submission_service: Any,
) -> ProviderTargetDelegationService:
    from api.dependencies import get_sqlite_knowledge_service

    knowledge_service = get_sqlite_knowledge_service()
    return ProviderTargetDelegationService(
        proposal_repository=knowledge_service.provider_discovery_proposal_repository,
        authorization_repository=knowledge_service.provider_target_authorization_repository,
        delegation_repository=knowledge_service.provider_target_delegation_repository,
        provider_profile_repository=knowledge_service.provider_profile_repository,
        agent_task_service=knowledge_service.agent_task_service,
        submission_service=submission_service,
        delegated_agent_repository=knowledge_service.delegated_agent_repository,
    )


def _get_provider_target_proposal_service() -> ProviderTargetProposalService:
    from api.dependencies import get_sqlite_knowledge_service

    knowledge_service = get_sqlite_knowledge_service()
    return ProviderTargetProposalService(
        proposal_repository=knowledge_service.provider_discovery_proposal_repository,
        provider_catalog_service=ProviderCatalogService(
            knowledge_service.provider_profile_repository,
            knowledge_service.provider_run_repository,
        ),
        agent_task_service=knowledge_service.agent_task_service,
    )


def _encode(payload: dict[str, object]) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _error(
    *,
    kind: str,
    message: str,
    retryable: bool = False,
    user_action_required: str | None = None,
    reason_code: str | None = None,
) -> dict[str, object]:
    error: dict[str, object] = {
        "kind": kind,
        "message": message,
        "retryable": retryable,
        "user_action_required": user_action_required,
    }
    if reason_code is not None:
        error["reason_code"] = reason_code
    return {"ok": False, "error": error}


async def _provider_catalog_impl(
    action: str,
    provider_profile_id: str | None = None,
    offset: int = 0,
    limit: int = DEFAULT_PAGE_LIMIT,
    proposal_status: str | None = None,
    grounding_tier: str | None = None,
    confidence: str | None = None,
    provider_candidates: list[ProviderCandidateInput] | None = None,
    service_candidates: list[ServiceCandidateInput] | None = None,
    evidence: list[ProposalEvidenceInput] | None = None,
    exact_user_constraints: ExactUserConstraintsInput | None = None,
    rationale: str | None = None,
    resolution_note: str | None = None,
    proposal_id: str | None = None,
    authorization_id: str | None = None,
    checkpoint_response: str | None = None,
    *,
    agent_task_id: str | None = None,
    root_task_id: str | None = None,
    submission_service: Any = None,
) -> str:
    try:
        if action == ACTION_LIST:
            result = await _get_provider_catalog_service().list_providers(
                offset=offset,
                limit=limit,
            )
            return _encode({"ok": True, "result": result})
        if action == ACTION_DESCRIBE:
            if not isinstance(provider_profile_id, str) or not provider_profile_id.strip():
                return _encode(
                    _error(
                        kind="invalid_arguments",
                        message="describe_provider requires provider_profile_id from list_providers.",
                    )
                )
            result = await _get_provider_catalog_service().describe_provider(
                provider_profile_id.strip()
            )
            return _encode({"ok": True, "result": result})
        if action == ACTION_PROPOSE:
            required_values = (
                agent_task_id,
                root_task_id,
                proposal_status,
                grounding_tier,
                confidence,
                rationale,
            )
            if any(value is None for value in required_values):
                return _encode(
                    _error(
                        kind="invalid_arguments",
                        message="propose_target requires captured task identity, status, grounding_tier, confidence, and rationale.",
                    )
                )
            proposal_service = _get_provider_target_proposal_service()
            result = await proposal_service.propose_target(
                agent_task_id=str(agent_task_id),
                root_task_id=str(root_task_id),
                status=str(proposal_status),
                grounding_tier=str(grounding_tier),
                confidence=str(confidence),
                provider_candidates=[
                    candidate.model_dump()
                    if isinstance(candidate, ProviderCandidateInput)
                    else dict(candidate)
                    for candidate in provider_candidates or []
                ],
                service_candidates=[
                    candidate.model_dump()
                    if isinstance(candidate, ServiceCandidateInput)
                    else dict(candidate)
                    for candidate in service_candidates or []
                ],
                evidence=[
                    item.model_dump()
                    if isinstance(item, ProposalEvidenceInput)
                    else dict(item)
                    for item in evidence or []
                ],
                exact_user_constraints=(
                    exact_user_constraints.model_dump()
                    if isinstance(exact_user_constraints, ExactUserConstraintsInput)
                    else dict(exact_user_constraints or {})
                ),
                rationale=str(rationale),
                resolution_note=resolution_note,
            )
            return _encode({"ok": True, "result": result})
        if action == ACTION_AUTHORIZE:
            if not all(isinstance(value, str) and value.strip() for value in (agent_task_id, root_task_id, proposal_id)):
                return _encode(
                    _error(
                        kind="invalid_arguments",
                        message="authorize_target requires captured task identity and proposal_id.",
                    )
                )
            result = await _get_provider_target_authorization_service().authorize_proposal(
                agent_task_id=str(agent_task_id),
                root_task_id=str(root_task_id),
                proposal_id=str(proposal_id),
            )
            return _encode({"ok": True, "result": result})
        if action == ACTION_RESOLVE_AUTHORIZATION:
            if not all(
                isinstance(value, str) and value.strip()
                for value in (agent_task_id, root_task_id, authorization_id, checkpoint_response)
            ):
                return _encode(
                    _error(
                        kind="invalid_arguments",
                        message="resolve_target_authorization requires captured task identity, authorization_id, and checkpoint_response.",
                    )
                )
            result = await _get_provider_target_authorization_service().resolve_checkpoint_response(
                agent_task_id=str(agent_task_id),
                root_task_id=str(root_task_id),
                authorization_id=str(authorization_id),
                response=str(checkpoint_response),
            )
            return _encode({"ok": True, "result": result})
        if action == ACTION_DELEGATE:
            if not all(
                isinstance(value, str) and value.strip()
                for value in (agent_task_id, root_task_id, authorization_id)
            ):
                return _encode(
                    _error(
                        kind="invalid_arguments",
                        message="delegate requires captured task identity and authorization_id.",
                    )
                )
            if submission_service is None:
                return _encode(
                    _error(
                        kind="unavailable",
                        message="Provider delegation is unavailable in this workflow.",
                        reason_code="delegation_submission_unavailable",
                    )
                )
            result = await _get_provider_target_delegation_service(
                submission_service
            ).delegate_authorization(
                agent_task_id=str(agent_task_id),
                root_task_id=str(root_task_id),
                authorization_id=str(authorization_id),
            )
            if result.get("ok"):
                return _encode({"ok": True, "result": result})
            return _encode(
                _error(
                    kind="unavailable",
                    message="The authorized provider target is no longer available.",
                    reason_code=str(
                        result.get("reason_code")
                        or "delegation_submission_failed"
                    ),
                )
            )
        return _encode(
            _error(
                kind="invalid_arguments",
                message="Unknown provider_catalog action.",
            )
        )
    except ProviderDelegationWaitRequest:
        raise
    except ValueError as exc:
        return _encode(_error(kind="invalid_arguments", message=str(exc)))
    except ProviderTargetProposalUnavailableError as exc:
        return _encode(
            _error(
                kind="unavailable",
                message=str(exc),
                reason_code=exc.reason_code,
            )
        )
    except ProviderTargetAuthorizationUnavailableError as exc:
        return _encode(
            _error(
                kind="unavailable",
                message=str(exc),
                reason_code=exc.reason_code,
            )
        )
    except ProviderTargetDelegationUnavailableError as exc:
        return _encode(
            _error(
                kind="unavailable",
                message=str(exc),
                reason_code=exc.reason_code,
            )
        )
    except ProviderTargetDelegationError as exc:
        return _encode(_error(kind="invalid_arguments", message=str(exc)))
    except ProviderTargetAuthorizationError as exc:
        return _encode(_error(kind="invalid_arguments", message=str(exc)))
    except (
        ProviderTargetAuthorizationConflictError,
        ProviderTargetAuthorizationPersistenceError,
    ):
        return _encode(
            _error(
                kind="unavailable",
                message="The target authorization record could not be persisted.",
            )
        )
    except ProviderTargetProposalError as exc:
        return _encode(_error(kind="invalid_arguments", message=str(exc)))
    except ProviderCatalogNotFoundError as exc:
        return _encode(_error(kind="not_found", message=str(exc)))
    except ProviderCatalogUnavailableError as exc:
        return _encode(
            _error(
                kind="unavailable",
                message=str(exc),
                user_action_required=exc.user_action_required,
                reason_code=exc.reason_code,
            )
        )
    except Exception:
        logger.exception("provider_catalog dispatch failed")
        return _encode(
            _error(
                kind="internal_error",
                message="The local provider catalog could not be read.",
                retryable=True,
            )
        )


def create_provider_catalog_tool(
    profile=None,
    *,
    agent_task_id: str | None = None,
    root_task_id: str | None = None,
    submission_service: Any = None,
) -> StructuredTool:
    description = select_description_for_profile(
        profile,
        FULL_DESCRIPTION,
        SLIM_DESCRIPTION,
    )

    async def _bound_provider_catalog_impl(**kwargs: Any) -> str:
        return await _provider_catalog_impl(
            **kwargs,
            agent_task_id=agent_task_id,
            root_task_id=root_task_id,
            submission_service=submission_service,
        )

    return StructuredTool.from_function(
        func=_bound_provider_catalog_impl,
        name=CATALOG_TOOL_NAME,
        description=description,
        args_schema=ProviderCatalogInput,
        coroutine=_bound_provider_catalog_impl,
    )
