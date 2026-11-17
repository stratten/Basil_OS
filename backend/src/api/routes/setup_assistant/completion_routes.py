"""Completion and state endpoints for the setup assistant."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

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
    """Mirror of complete payload so partial progress is preserved across the skip boundary, plus what is needed to pick the session back up."""

    resume_stage: Optional[str] = None
    resume_summary: Optional[str] = None
    resume_model_access: Optional[Dict[str, Any]] = None
    resume_interaction_style: List[str] = Field(default_factory=list)
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
        resume_stage=request.resume_stage,
        resume_summary=request.resume_summary,
        resume_model_access=request.resume_model_access,
        resume_interaction_style=request.resume_interaction_style,
    )
    return SetupAssistantStateResponse(state=state)


@router.post("/progress", response_model=SetupAssistantStateResponse)
async def save_setup_assistant_progress(
    request: SetupAssistantSkipRequest,
) -> SetupAssistantStateResponse:
    """Keep the session's place as it goes, so it can be picked up however the window was closed."""

    state = SetupAssistantCompletionService().save_setup_progress(
        configured=request.configured,
        skipped=request.skipped,
        deferred=request.deferred,
        session_goals=request.session_goals,
        execution_outcomes=request.execution_outcomes,
        blockers=request.blockers,
        resume_stage=request.resume_stage,
        resume_summary=request.resume_summary,
        resume_model_access=request.resume_model_access,
        resume_interaction_style=request.resume_interaction_style,
    )
    return SetupAssistantStateResponse(state=state)


@router.post("/discard-saved-session", response_model=SetupAssistantStateResponse)
async def discard_saved_setup_session() -> SetupAssistantStateResponse:
    """Forget the saved session because the person chose to start from the top."""

    state = SetupAssistantCompletionService().discard_saved_session()
    return SetupAssistantStateResponse(state=state)


@router.post("/dismiss-reminder", response_model=SetupAssistantStateResponse)
async def dismiss_setup_assistant_reminder() -> SetupAssistantStateResponse:
    """Suppress the launch-time resume toast while leaving the pending flag intact."""

    state = SetupAssistantCompletionService().dismiss_setup_reminder()
    return SetupAssistantStateResponse(state=state)
