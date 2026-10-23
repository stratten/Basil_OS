"""Ambient suggestion routes."""

from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api.core.models.preferences import Preferences
from api.core.preferences.preferences_io import load_preferences
from api.services.ambient_suggestions.models import AmbientSuggestionRecord, SuggestionOutcome
from api.services.ambient_suggestions.runtime import get_ambient_suggestion_runtime
from api.services.ambient_suggestions.store import AmbientSuggestionStore

router = APIRouter(prefix="/ambient-suggestions", tags=["ambient_suggestions"])


class AmbientSuggestionActionRequest(BaseModel):
    outcome: SuggestionOutcome


class AmbientSuggestionOperationResponse(BaseModel):
    success: bool
    suggestion: AmbientSuggestionRecord | None = None
    message: str


def _load_preferences() -> Preferences:
    return load_preferences()


def _get_runtime_or_raise():
    runtime = get_ambient_suggestion_runtime()
    if runtime is None:
        raise HTTPException(status_code=503, detail="Proactive Suggestions runtime is not initialized")
    return runtime


async def _start_runtime_from_preferences() -> AmbientSuggestionOperationResponse:
    preferences = _load_preferences()
    if not preferences.ambient_suggestions.enabled:
        raise HTTPException(status_code=409, detail="Proactive Suggestions are disabled in Settings")
    runtime = _get_runtime_or_raise()
    await runtime.apply_settings(preferences.ambient_suggestions)
    await runtime.start()
    return AmbientSuggestionOperationResponse(success=True, suggestion=None, message="Proactive Suggestions started")


async def _stop_runtime() -> AmbientSuggestionOperationResponse:
    runtime = _get_runtime_or_raise()
    await runtime.stop()
    return AmbientSuggestionOperationResponse(success=True, suggestion=None, message="Proactive Suggestions stopped")


@router.get("/suggestions", response_model=List[AmbientSuggestionRecord])
async def list_ambient_suggestions() -> List[AmbientSuggestionRecord]:
    """Return currently open suggestion cards."""
    return AmbientSuggestionStore().list_open_suggestions()


@router.post("/capture-once", response_model=AmbientSuggestionOperationResponse)
async def capture_ambient_suggestion_once() -> AmbientSuggestionOperationResponse:
    """Run one ambient capture/evaluation pass."""
    runtime = get_ambient_suggestion_runtime()
    if runtime is None:
        raise HTTPException(status_code=503, detail="Proactive Suggestions runtime is not initialized")
    suggestion = await runtime.run_once()
    return AmbientSuggestionOperationResponse(
        success=True,
        suggestion=suggestion,
        message="Suggestion created" if suggestion else "No suggestion created",
    )


@router.post("/start", response_model=AmbientSuggestionOperationResponse)
async def start_ambient_suggestions() -> AmbientSuggestionOperationResponse:
    """Start the ambient suggestion runtime if enabled in settings."""
    return await _start_runtime_from_preferences()


@router.post("/stop", response_model=AmbientSuggestionOperationResponse)
async def stop_ambient_suggestions() -> AmbientSuggestionOperationResponse:
    """Stop the ambient suggestion runtime without disabling the feature."""
    return await _stop_runtime()


@router.post("/toggle", response_model=AmbientSuggestionOperationResponse)
async def toggle_ambient_suggestions() -> AmbientSuggestionOperationResponse:
    """Toggle the ambient suggestion runtime running state."""
    runtime = _get_runtime_or_raise()
    if runtime.is_running():
        return await _stop_runtime()
    return await _start_runtime_from_preferences()


@router.post("/suggestions/{suggestion_id}/outcome", response_model=AmbientSuggestionOperationResponse)
async def update_ambient_suggestion_outcome(
    suggestion_id: str,
    request: AmbientSuggestionActionRequest,
) -> AmbientSuggestionOperationResponse:
    """Record an accept/reject/dismiss outcome for a suggestion card."""
    store = AmbientSuggestionStore()
    suggestion = store.update_outcome(suggestion_id, request.outcome)
    if suggestion is None:
        raise HTTPException(status_code=404, detail="Proactive suggestion not found")
    runtime = get_ambient_suggestion_runtime()
    if runtime:
        await runtime.broadcast_suggestion_updated(suggestion)
    return AmbientSuggestionOperationResponse(
        success=True,
        suggestion=suggestion,
        message=f"Suggestion marked {request.outcome}",
    )


@router.get("/status")
async def get_ambient_suggestion_status() -> Dict[str, Any]:
    """Return runtime status for ambient suggestions."""
    runtime = get_ambient_suggestion_runtime()
    if runtime is None:
        return {"initialized": False, "enabled": False}
    return runtime.get_status()
