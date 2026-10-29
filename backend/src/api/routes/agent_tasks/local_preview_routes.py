"""Routes for approval-gated local web preview dev-server sessions."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from api.core.knowledge.sqlite.sqlite_knowledge_service import SQLiteKnowledgeService
from api.dependencies import get_local_preview_launcher, get_sqlite_knowledge_service
from api.services.agent_processing.tools.direct_application_interactions.local_web_preview.local_preview_authorization import (
    require_artifact_within_working_directory,
    resolve_task_owned_preview_artifact,
)

router = APIRouter()


class StartLocalPreviewSessionRequest(BaseModel):
    command: str = Field(min_length=1, max_length=1_024)
    args: list[str] = Field(default_factory=list, max_length=128)
    cwd: str = Field(min_length=1, max_length=4_096)
    port: int = Field(ge=1, le=65_535)
    host: Literal["127.0.0.1"] = "127.0.0.1"


class LocalPreviewSessionResponse(BaseModel):
    session_id: str
    agent_task_id: str
    artifact_id: str
    status: str
    url: str
    host: str
    port: int
    pid: int | None
    last_error: str | None
    command: str
    args: list[str]
    cwd: str
    created_at: float
    stopped_at: float | None


@router.post(
    "/{agent_task_id}/artifacts/{artifact_id}/local-preview/sessions",
    response_model=LocalPreviewSessionResponse,
)
async def start_local_preview_session(
    agent_task_id: str,
    artifact_id: str,
    body: StartLocalPreviewSessionRequest,
    request: Request,
    knowledge_service: SQLiteKnowledgeService = Depends(get_sqlite_knowledge_service),
) -> LocalPreviewSessionResponse:
    artifact = await resolve_task_owned_preview_artifact(
        knowledge_service=knowledge_service,
        requested_agent_task_id=agent_task_id,
        artifact_id=artifact_id,
    )
    require_artifact_within_working_directory(artifact, body.cwd)
    launcher = get_local_preview_launcher(request=request)
    session = await launcher.start_session(
        agent_task_id=agent_task_id, artifact_id=artifact_id,
        command=body.command, args=body.args, cwd=body.cwd, host=body.host, port=body.port,
    )
    return LocalPreviewSessionResponse(**session.to_dto())


@router.get(
    "/{agent_task_id}/artifacts/{artifact_id}/local-preview/sessions/{session_id}",
    response_model=LocalPreviewSessionResponse,
)
async def get_local_preview_session(
    agent_task_id: str, artifact_id: str, session_id: str, request: Request
) -> LocalPreviewSessionResponse:
    launcher = get_local_preview_launcher(request=request)
    session = launcher._registry.get(session_id)
    if session is None or session.agent_task_id != agent_task_id or session.artifact_id != artifact_id:
        raise HTTPException(status_code=404, detail="Local preview session not found.")
    return LocalPreviewSessionResponse(**session.to_dto())


@router.post(
    "/{agent_task_id}/artifacts/{artifact_id}/local-preview/sessions/{session_id}/stop",
    response_model=LocalPreviewSessionResponse,
)
async def stop_local_preview_session(
    agent_task_id: str, artifact_id: str, session_id: str, request: Request
) -> LocalPreviewSessionResponse:
    launcher = get_local_preview_launcher(request=request)
    session = launcher._registry.get(session_id)
    if session is None or session.agent_task_id != agent_task_id or session.artifact_id != artifact_id:
        raise HTTPException(status_code=404, detail="Local preview session not found.")
    stopped = await launcher.stop_session(session_id)
    return LocalPreviewSessionResponse(**stopped.to_dto())
