"""Attended local configuration surface for provider profiles and workspace grants."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from api.core.security.backend_request_guard import require_host_credential

from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.providers.errors import (
    ProviderRunConflictError,
    ProviderRunPersistenceError,
)
from api.services.agent_providers.profiles.launch_validation import (
    ProviderProfileSummary,
    WorkspaceGrantSummary,
    list_provider_profile_summaries,
)
from .models import (
    ProfileRevisionRequest,
    ProviderProfileConfigurationDTO,
    ProviderProfileCreateRequest,
    ProviderProfileSummaryDTO,
    ProviderProfileUpdateRequest,
    ProviderProfilesListResponse,
    WorkspaceGrantCreateRequest,
    WorkspaceGrantSummaryDTO,
    WorkspaceGrantUpdateRequest,
)

router = APIRouter(prefix="/settings/provider-profiles", tags=["provider-profiles"])
logger = logging.getLogger(__name__)


def _workspace_grant_dto(grant: WorkspaceGrantSummary) -> WorkspaceGrantSummaryDTO:
    return WorkspaceGrantSummaryDTO(
        id=grant.id,
        canonical_workspace_root=grant.canonical_workspace_root,
        status=grant.status,
        workspace_label=grant.workspace_label,
        description=grant.description,
        routing_hints=list(grant.routing_hints),
        revision=grant.revision,
    )


def _profile_summary_dto(summary: ProviderProfileSummary) -> ProviderProfileSummaryDTO:
    return ProviderProfileSummaryDTO(
        id=summary.id,
        display_name=summary.display_name,
        status=summary.status,
        capability_state=summary.capability_state,
        description=summary.description,
        routing_hints=list(summary.routing_hints),
        revision=summary.revision,
        has_observed_capabilities=summary.observed_capabilities is not None,
        active_workspace_grants=[
            _workspace_grant_dto(grant) for grant in summary.active_workspace_grants
        ],
        is_structurally_valid=summary.is_structurally_valid,
        validation_error=summary.validation_error,
        created_at=summary.created_at,
        updated_at=summary.updated_at,
    )


async def _get_profile_summary(
    provider_profile_repository,
    provider_run_repository,
    provider_profile_id: str,
) -> ProviderProfileSummary:
    summaries = await list_provider_profile_summaries(
        provider_profile_repository,
        provider_run_repository,
    )
    for summary in summaries:
        if summary.id == provider_profile_id:
            return summary
    raise HTTPException(status_code=409, detail="Provider profile is unavailable.")


async def _get_configuration_dto(
    provider_profile_repository,
    provider_run_repository,
    provider_profile_id: str,
) -> ProviderProfileConfigurationDTO:
    profile = await provider_profile_repository.get_profile(provider_profile_id)
    if profile is None or profile["status"] == "removed":
        raise HTTPException(status_code=409, detail="Provider profile is unavailable.")
    summary = await _get_profile_summary(
        provider_profile_repository,
        provider_run_repository,
        provider_profile_id,
    )
    return ProviderProfileConfigurationDTO(
        **_profile_summary_dto(summary).model_dump(),
        launch_argv=list(profile["launch_argv"]),
        environment_allowlist=list(profile["environment_allowlist"]),
        authentication_method_id=profile["authentication_method_id"],
    )


def _raise_mutation_error(exc: Exception) -> None:
    if isinstance(exc, ProviderRunConflictError):
        raise HTTPException(
            status_code=409,
            detail="Provider registry state changed or is unavailable.",
        ) from exc
    raise HTTPException(
        status_code=422,
        detail="Provider profile configuration is invalid.",
    ) from exc
    logger.exception("Provider registry mutation failed", exc_info=exc)
    raise HTTPException(
        status_code=500,
        detail="Provider registry mutation failed.",
    ) from exc


@router.get("", response_model=ProviderProfilesListResponse)
async def list_provider_profiles() -> ProviderProfilesListResponse:
    """List every non-removed provider profile with sanitized validation and grant state."""
    from api.dependencies import get_sqlite_knowledge_service

    service = get_sqlite_knowledge_service()
    summaries = await list_provider_profile_summaries(
        service.provider_profile_repository,
        service.provider_run_repository,
    )
    return ProviderProfilesListResponse(
        profiles=[_profile_summary_dto(summary) for summary in summaries]
    )


@router.get("/{provider_profile_id}", response_model=ProviderProfileConfigurationDTO)
async def get_provider_profile_configuration(
    provider_profile_id: str,
) -> ProviderProfileConfigurationDTO:
    from api.dependencies import get_sqlite_knowledge_service

    return await _get_configuration_dto(
        get_sqlite_knowledge_service().provider_profile_repository,
        get_sqlite_knowledge_service().provider_run_repository,
        provider_profile_id,
    )


@router.post(
    "",
    response_model=ProviderProfileConfigurationDTO,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_host_credential)],
)
async def create_provider_profile(
    request: ProviderProfileCreateRequest,
) -> ProviderProfileConfigurationDTO:
    from api.dependencies import get_sqlite_knowledge_service

    service = get_sqlite_knowledge_service()
    repository = service.provider_profile_repository
    try:
        profile = await repository.create_profile(
            display_name=request.display_name,
            launch_argv=tuple(request.launch_argv),
            environment_allowlist=tuple(request.environment_allowlist),
            authentication_method_id=request.authentication_method_id,
            description=request.description,
            routing_hints=tuple(request.routing_hints),
            initial_status="disabled",
            require_executable=True,
        )
    except Exception as exc:
        _raise_mutation_error(exc)
    return await _get_configuration_dto(
        repository,
        service.provider_run_repository,
        str(profile["id"]),
    )


@router.put(
    "/{provider_profile_id}",
    response_model=ProviderProfileConfigurationDTO,
    dependencies=[Depends(require_host_credential)],
)
async def update_provider_profile(
    provider_profile_id: str,
    request: ProviderProfileUpdateRequest,
) -> ProviderProfileConfigurationDTO:
    from api.dependencies import get_sqlite_knowledge_service

    service = get_sqlite_knowledge_service()
    repository = service.provider_profile_repository
    try:
        await repository.update_profile_configuration(
            provider_profile_id=provider_profile_id,
            expected_revision=request.expected_revision,
            display_name=request.display_name,
            launch_argv=tuple(request.launch_argv),
            environment_allowlist=tuple(request.environment_allowlist),
            authentication_method_id=request.authentication_method_id,
            description=request.description,
            routing_hints=tuple(request.routing_hints),
        )
    except Exception as exc:
        _raise_mutation_error(exc)
    return await _get_configuration_dto(
        repository,
        service.provider_run_repository,
        provider_profile_id,
    )


@router.post(
    "/{provider_profile_id}/enable",
    response_model=ProviderProfileConfigurationDTO,
    dependencies=[Depends(require_host_credential)],
)
async def enable_provider_profile(
    provider_profile_id: str,
    request: ProfileRevisionRequest,
) -> ProviderProfileConfigurationDTO:
    return await _set_provider_profile_status(
        provider_profile_id,
        request.expected_revision,
        "enabled",
    )


@router.post("/{provider_profile_id}/disable", response_model=ProviderProfileConfigurationDTO)
async def disable_provider_profile(
    provider_profile_id: str,
    request: ProfileRevisionRequest,
) -> ProviderProfileConfigurationDTO:
    return await _set_provider_profile_status(
        provider_profile_id,
        request.expected_revision,
        "disabled",
    )


async def _set_provider_profile_status(
    provider_profile_id: str,
    expected_revision: int,
    next_status: str,
) -> ProviderProfileConfigurationDTO:
    from api.dependencies import get_sqlite_knowledge_service

    service = get_sqlite_knowledge_service()
    repository = service.provider_profile_repository
    try:
        await repository.set_profile_registry_status(
            provider_profile_id=provider_profile_id,
            expected_revision=expected_revision,
            next_status=next_status,
        )
    except Exception as exc:
        _raise_mutation_error(exc)
    return await _get_configuration_dto(
        repository,
        service.provider_run_repository,
        provider_profile_id,
    )


@router.delete("/{provider_profile_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_provider_profile(
    provider_profile_id: str,
    expected_revision: int = Query(ge=0),
) -> Response:
    from api.dependencies import get_sqlite_knowledge_service

    try:
        await get_sqlite_knowledge_service().provider_profile_repository.set_profile_registry_status(
            provider_profile_id=provider_profile_id,
            expected_revision=expected_revision,
            next_status="removed",
        )
    except Exception as exc:
        _raise_mutation_error(exc)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{provider_profile_id}/workspace-grants",
    response_model=WorkspaceGrantSummaryDTO,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_host_credential)],
)
async def create_workspace_grant(
    provider_profile_id: str,
    request: WorkspaceGrantCreateRequest,
) -> WorkspaceGrantSummaryDTO:
    from api.dependencies import get_sqlite_knowledge_service

    try:
        grant = await get_sqlite_knowledge_service().provider_profile_repository.grant_workspace(
            provider_profile_id=provider_profile_id,
            canonical_workspace_root=request.canonical_workspace_root,
            workspace_label=request.workspace_label,
            description=request.description,
            routing_hints=tuple(request.routing_hints),
            reject_active_duplicate=True,
        )
    except Exception as exc:
        _raise_mutation_error(exc)
    return WorkspaceGrantSummaryDTO(**grant)


@router.put(
    "/{provider_profile_id}/workspace-grants/{workspace_grant_id}",
    response_model=WorkspaceGrantSummaryDTO,
    dependencies=[Depends(require_host_credential)],
)
async def update_workspace_grant(
    provider_profile_id: str,
    workspace_grant_id: str,
    request: WorkspaceGrantUpdateRequest,
) -> WorkspaceGrantSummaryDTO:
    from api.dependencies import get_sqlite_knowledge_service

    try:
        grant = await get_sqlite_knowledge_service().provider_profile_repository.update_workspace_grant_configuration(
            provider_profile_id=provider_profile_id,
            workspace_grant_id=workspace_grant_id,
            expected_revision=request.expected_revision,
            workspace_label=request.workspace_label,
            description=request.description,
            routing_hints=tuple(request.routing_hints),
        )
    except Exception as exc:
        _raise_mutation_error(exc)
    return WorkspaceGrantSummaryDTO(**grant)


@router.delete(
    "/{provider_profile_id}/workspace-grants/{workspace_grant_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def revoke_workspace_grant(
    provider_profile_id: str,
    workspace_grant_id: str,
    expected_revision: int = Query(ge=0),
) -> Response:
    from api.dependencies import get_sqlite_knowledge_service

    try:
        await get_sqlite_knowledge_service().provider_profile_repository.revoke_workspace_grant_if_revision(
            provider_profile_id=provider_profile_id,
            workspace_grant_id=workspace_grant_id,
            expected_revision=expected_revision,
        )
    except Exception as exc:
        _raise_mutation_error(exc)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
