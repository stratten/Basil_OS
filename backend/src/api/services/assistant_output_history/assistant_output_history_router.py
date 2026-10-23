"""REST API endpoints for AssistantSession history (shared across all output types)."""

import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from api.core.knowledge.personalization_service import PersonalizationService
from ...dependencies import get_sqlite_knowledge_service
from .assistant_output_history_service import AssistantOutputHistoryService
from .assistant_output_samples import attach_sample_state, save_assistant_output_as_sample

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/assistant-outputs", tags=["Assistant Output History"])

_service_instance: Optional[AssistantOutputHistoryService] = None


def _get_service() -> AssistantOutputHistoryService:
    global _service_instance
    if _service_instance is None:
        _service_instance = AssistantOutputHistoryService(get_sqlite_knowledge_service())
    return _service_instance


def _get_personalization_service() -> PersonalizationService:
    return PersonalizationService()


class SaveHistorySampleRequest(BaseModel):
    """Text to save from a History row; context is used only when the row has none."""
    content: str
    context_type: Optional[str] = None


@router.get("")
async def list_assistant_output_history(
    input_modality: Optional[str] = Query(
        None, description="Filter by input modality: voice or text"
    ),
    output_type: Optional[str] = Query(
        None, description="Filter by output type: assistant_session, regular, activity"
    ),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """List past AssistantSession outputs, newest first, optionally filtered by modality/type."""
    service = _get_service()
    return await service.list_assistant_outputs(
        input_modality_filter=input_modality,
        output_type_filter=output_type,
        limit=limit,
        offset=offset,
    )


@router.get("/search")
async def search_assistant_output_history(
    q: str = Query(..., min_length=1, description="Search query"),
    input_modality: Optional[str] = Query(
        None, description="Filter by input modality: voice or text"
    ),
    output_type: Optional[str] = Query(
        None, description="Filter by output type: assistant_session, regular, activity"
    ),
    limit: int = Query(50, ge=1, le=200),
):
    """Full-text search across user_request and output_text."""
    service = _get_service()
    return await service.search_assistant_outputs(
        query=q,
        input_modality_filter=input_modality,
        output_type_filter=output_type,
        limit=limit,
    )


@router.get("/{assistant_output_id}")
async def get_assistant_output_detail(assistant_output_id: int):
    """Retrieve full detail for a single AssistantSession output (for rehydration)."""
    service = _get_service()
    detail = await service.get_assistant_output_detail(assistant_output_id)
    if not detail:
        raise HTTPException(status_code=404, detail="AssistantSession output not found")
    try:
        return await attach_sample_state(detail, _get_personalization_service())
    except Exception as error:
        logger.warning(f"Could not resolve writing-sample state for assistant_output {assistant_output_id}: {error}")
        detail["sample_context_type"] = None
        detail["saved_sample"] = None
        return detail


@router.delete("/{assistant_output_id}")
async def delete_assistant_output(assistant_output_id: int):
    """Delete a AssistantSession output by id."""
    service = _get_service()
    deleted = await service.delete_assistant_output(assistant_output_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="AssistantSession output not found")
    return {"status": "deleted", "id": assistant_output_id}


@router.post("/{assistant_output_id}/save-sample")
async def save_assistant_output_sample(assistant_output_id: int, request: SaveHistorySampleRequest):
    """Save a History row's output (or an edited version) as a linked writing sample."""
    service = _get_service()
    detail = await service.get_assistant_output_detail(assistant_output_id)
    if not detail:
        raise HTTPException(status_code=404, detail="AssistantSession output not found")
    return await save_assistant_output_as_sample(
        detail,
        request.content,
        request.context_type,
        _get_personalization_service(),
    )


@router.post("/{assistant_output_id}/resume")
async def resume_assistant_output(assistant_output_id: int):
    """Load a persisted AssistantSession output into an in-memory session for continued refinement.

    For 'assistant_session' rows this returns the context needed to start a new
    refinement recording. For 'regular' rows it returns the data needed
    to display an inline refinement field.
    """
    service = _get_service()
    detail = await service.get_assistant_output_detail(assistant_output_id)
    if not detail:
        raise HTTPException(status_code=404, detail="AssistantSession output not found")

    return {
        "assistant_output_id": detail["id"],
        "output_type": detail["output_type"],
        "input_modality": detail["input_modality"],
        "output_text": detail["output_text"],
        "user_request": detail["user_request"],
        "context_text": detail["context_text"],
        "explanation_text": detail["explanation_text"],
        "app_name": detail["app_name"],
        "refinement_count": detail["refinement_count"],
        "refinements": detail["refinements"],
    }
