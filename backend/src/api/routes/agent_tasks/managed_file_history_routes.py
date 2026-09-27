"""Routes for managed file-history version listing and one-click restore."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.dependencies import get_managed_file_history_service_for_routes
from api.services.agent_processing.tools.direct_application_interactions.file_system.managed_history.managed_file_history_service import (
    ManagedFileHistoryService,
)

router = APIRouter()


class ManagedFileVersionResponse(BaseModel):
    id: str
    root_task_id: str
    agent_task_id: str
    canonical_path: str
    operation: str
    origin: str
    post_image_size_bytes: int | None
    restores_change_id: str | None
    created_at: str
    applied_at: str | None


class ManagedFileVersionsResponse(BaseModel):
    canonical_path: str
    versions: list[ManagedFileVersionResponse]


class RestoreManagedFileVersionRequest(BaseModel):
    root_task_id: str = Field(min_length=1, max_length=256)
    canonical_path: str = Field(min_length=1, max_length=4_096)
    restores_change_id: str = Field(min_length=1, max_length=256)
    agent_task_id: str | None = Field(default=None, max_length=256)


class RestoreManagedFileVersionResponse(BaseModel):
    success: bool
    change_id: str | None = None
    canonical_path: str | None = None
    restored_from_change_id: str | None = None
    error: str | None = None
    error_type: str | None = None


class ManagedFileVersionContentResponse(BaseModel):
    change_id: str
    canonical_path: str
    content: str | None
    truncated: bool
    byte_size: int | None


def _to_version_response(change: dict[str, Any]) -> ManagedFileVersionResponse:
    return ManagedFileVersionResponse(
        id=change["id"],
        root_task_id=change["root_task_id"],
        agent_task_id=change["agent_task_id"],
        canonical_path=change["canonical_path"],
        operation=change["operation"],
        origin=change["origin"],
        post_image_size_bytes=change["post_image_size_bytes"],
        restores_change_id=change["restores_change_id"],
        created_at=change["created_at"],
        applied_at=change["applied_at"],
    )


@router.get("/managed-file-history/versions", response_model=ManagedFileVersionsResponse)
async def list_managed_file_versions(
    canonical_path: str,
    service: ManagedFileHistoryService = Depends(get_managed_file_history_service_for_routes),
) -> ManagedFileVersionsResponse:
    versions = await service.list_versions(canonical_path)
    return ManagedFileVersionsResponse(
        canonical_path=canonical_path,
        versions=[_to_version_response(version) for version in versions],
    )


@router.post("/managed-file-history/restore", response_model=RestoreManagedFileVersionResponse)
async def restore_managed_file_version(
    body: RestoreManagedFileVersionRequest,
    service: ManagedFileHistoryService = Depends(get_managed_file_history_service_for_routes),
) -> RestoreManagedFileVersionResponse:
    result = await service.restore_version(
        root_task_id=body.root_task_id,
        canonical_path=body.canonical_path,
        restores_change_id=body.restores_change_id,
        agent_task_id=body.agent_task_id,
    )
    if not result.get("success"):
        raise HTTPException(status_code=409, detail=result)
    return RestoreManagedFileVersionResponse(**result)


@router.get(
    "/managed-file-history/versions/{change_id}/content",
    response_model=ManagedFileVersionContentResponse,
)
async def get_managed_file_version_content(
    change_id: str,
    service: ManagedFileHistoryService = Depends(get_managed_file_history_service_for_routes),
) -> ManagedFileVersionContentResponse:
    result = await service.get_version_content(change_id)
    if not result.get("success"):
        raise HTTPException(status_code=404, detail=result)
    return ManagedFileVersionContentResponse(
        change_id=result["change_id"],
        canonical_path=result["canonical_path"],
        content=result["content"],
        truncated=result["truncated"],
        byte_size=result["byte_size"],
    )
