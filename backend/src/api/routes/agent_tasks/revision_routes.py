"""Read-only, task-owned artifact revision routes."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Path

from api.core.knowledge.sqlite.sqlite_knowledge_service import SQLiteKnowledgeService
from api.dependencies import get_sqlite_knowledge_service

from .models import (
    AgentTaskArtifactRevisionContentResponse,
    AgentTaskArtifactRevisionItemResponse,
    AgentTaskArtifactRevisionListResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter()


async def _require_agent_task(
    knowledge_service: SQLiteKnowledgeService,
    agent_task_id: str,
) -> None:
    agent_task_record = await knowledge_service.agent_task_service.get_agent_task(agent_task_id)
    if not agent_task_record:
        raise HTTPException(status_code=404, detail=f"AgentTask {agent_task_id} not found")


@router.get(
    "/{agent_task_id}/artifacts/{artifact_id}/revisions",
    response_model=AgentTaskArtifactRevisionListResponse,
    summary="List durable revisions for one task-owned artifact",
)
async def list_agent_task_artifact_revisions(
    agent_task_id: str = Path(...),
    artifact_id: str = Path(...),
    knowledge_service: SQLiteKnowledgeService = Depends(get_sqlite_knowledge_service),
) -> AgentTaskArtifactRevisionListResponse:
    """Return newest-first revision metadata for one task-owned artifact.

    Ownership is enforced by the underlying query, which filters by both
    ``agent_task_id`` and ``artifact_id``; a mismatched pair returns an
    empty list rather than another task's revisions. The parent task must
    exist, or this raises 404 to distinguish "unknown task" from "task has
    no revisions for this artifact yet".
    """
    await _require_agent_task(knowledge_service, agent_task_id)
    revisions = await knowledge_service.agent_task_service.list_artifact_revisions(
        agent_task_id,
        artifact_id,
    )
    return AgentTaskArtifactRevisionListResponse(
        revisions=[
            AgentTaskArtifactRevisionItemResponse(**revision) for revision in revisions
        ]
    )


@router.get(
    "/{agent_task_id}/artifacts/{artifact_id}/revisions/{revision}",
    response_model=AgentTaskArtifactRevisionContentResponse,
    summary="Get one durable revision snapshot for one task-owned artifact",
)
async def get_agent_task_artifact_revision(
    agent_task_id: str = Path(...),
    artifact_id: str = Path(...),
    revision: int = Path(..., ge=1),
    knowledge_service: SQLiteKnowledgeService = Depends(get_sqlite_knowledge_service),
) -> AgentTaskArtifactRevisionContentResponse:
    """Return one bounded text snapshot owned by one Agent Task, or 404."""
    await _require_agent_task(knowledge_service, agent_task_id)
    snapshot = await knowledge_service.agent_task_service.get_artifact_revision(
        agent_task_id,
        artifact_id,
        revision,
    )
    if snapshot is None:
        raise HTTPException(
            status_code=404,
            detail=f"Revision {revision} not found for artifact {artifact_id}",
        )
    return AgentTaskArtifactRevisionContentResponse(**snapshot)
