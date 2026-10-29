"""Completion and state endpoints for the setup assistant."""

from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter
from pydantic import BaseModel, Field

from api.services.setup_assistant.completion_service import SetupAssistantCompletionService


router = APIRouter(prefix="/state", tags=["Setup Assistant"])


class SetupAssistantCompleteRequest(BaseModel):
    configured: List[str] = Field(default_factory=list)
    skipped: List[str] = Field(default_factory=list)
    deferred: List[str] = Field(default_factory=list)
    session_goals: List[Dict[str, Any]] = Field(default_factory=list)
    execution_outcomes: List[Dict[str, Any]] = Field(default_factory=list)
    blockers: List[Dict[str, Any]] = Field(default_factory=list)


class SetupAssistantSkipRequest(BaseModel):
    """Mirror of complete payload so partial progress is preserved across the skip boundary."""

    configured: List[str] = Field(default_factory=list)
    skipped: List[str] = Field(default_factory=list)
    deferred: List[str] = Field(default_factory=list)
    session_goals: List[Dict[str, Any]] = Field(default_factory=list)
    execution_outcomes: List[Dict[str, Any]] = Field(default_factory=list)
    blockers: List[Dict[str, Any]] = Field(default_factory=list)


class SetupAssistantStateResponse(BaseModel):
    state: Dict[str, Any]


@router.get("", response_model=SetupAssistantStateResponse)
async def get_setup_assistant_state() -> SetupAssistantStateResponse:
    """Return persisted setup assistant state."""

    return SetupAssistantStateResponse(
        state=SetupAssistantCompletionService().load_setup_state()
    )


@router.post("/complete", response_model=SetupAssistantStateResponse)
async def complete_setup_assistant(
    request: SetupAssistantCompleteRequest,
) -> SetupAssistantStateResponse:
    """Record setup assistant completion and satisfy first-run onboarding."""

    state = SetupAssistantCompletionService().mark_setup_complete(
        configured=request.configured,
        skipped=request.skipped,
        deferred=request.deferred,
        session_goals=request.session_goals,
        execution_outcomes=request.execution_outcomes,
        blockers=request.blockers,
    )
    return SetupAssistantStateResponse(state=state)


@router.post("/skip", response_model=SetupAssistantStateResponse)
async def skip_setup_assistant(
    request: SetupAssistantSkipRequest,
) -> SetupAssistantStateResponse:
    """Record a 'Skip for now' exit so we can resurface the resume reminder on next launch."""

    state = SetupAssistantCompletionService().mark_setup_skipped(
        configured=request.configured,
        skipped=request.skipped,
        deferred=request.deferred,
        session_goals=request.session_goals,
        execution_outcomes=request.execution_outcomes,
        blockers=request.blockers,
    )
    return SetupAssistantStateResponse(state=state)


@router.post("/dismiss-reminder", response_model=SetupAssistantStateResponse)
async def dismiss_setup_assistant_reminder() -> SetupAssistantStateResponse:
    """Suppress the launch-time resume toast while leaving the pending flag intact."""

    state = SetupAssistantCompletionService().dismiss_setup_reminder()
    return SetupAssistantStateResponse(state=state)
