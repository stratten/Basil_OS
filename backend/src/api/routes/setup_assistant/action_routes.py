"""Approved action endpoints for the setup assistant."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from api.core.knowledge.personalization_models import ContextType, SourceType, UserProfileCreate
from api.core.knowledge.personalization_service import PersonalizationService

from api.dependencies import get_model_service
from api.routes.setup_assistant.models import (
    SetupAction,
    SetupActionExecutionRequest,
    SetupActionExecutionResponse,
    SetupToolCall,
)
from api.services.setup_assistant.action_execution_service import (
    SetupAssistantActionExecutionService,
)
from api.services.memory.memory_service import MemoryService, get_memory_service
from api.services.memory.memory_store import MemoryFileBackpressureError


router = APIRouter(prefix="/actions", tags=["Setup Assistant"])
logger = logging.getLogger(__name__)


class SetupActionSequenceRequest(BaseModel):
    actions: List[SetupAction] = Field(default_factory=list)


class SetupActionSequenceResponse(BaseModel):
    actions: List[SetupAction]


class SetupToolCallValidationRequest(BaseModel):
    tool_calls: List[SetupToolCall] = Field(default_factory=list)


class SetupToolCallValidationResponse(BaseModel):
    tool_calls: List[SetupToolCall]


class SetupProfileApplyRequest(BaseModel):
    approved_fields: Dict[str, Any] = Field(default_factory=dict)


class SetupProfileApplyResponse(BaseModel):
    profile: Dict[str, Any]


class SetupWritingSampleApplyRequest(BaseModel):
    content: str = Field(min_length=1)
    context_type: str = "email_reply"
    recipient: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class SetupWritingSampleApplyResponse(BaseModel):
    sample_id: str
    context_type: str


@router.post("/sequence/validate", response_model=SetupActionSequenceResponse)
async def validate_setup_action_sequence(
    request: SetupActionSequenceRequest,
) -> SetupActionSequenceResponse:
    """Validate approved setup actions before execution."""

    try:
        actions = SetupAssistantActionExecutionService().build_sequential_action_queue(
            request.actions
        )
        return SetupActionSequenceResponse(actions=actions)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/tool-calls/validate", response_model=SetupToolCallValidationResponse)
async def validate_setup_tool_calls(
    request: SetupToolCallValidationRequest,
) -> SetupToolCallValidationResponse:
    """Validate approved schema-bound setup tool calls before native execution."""

    try:
        tool_calls = SetupAssistantActionExecutionService().validate_approved_tool_calls(
            request.tool_calls
        )
        return SetupToolCallValidationResponse(tool_calls=tool_calls)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/execute", response_model=SetupActionExecutionResponse)
async def execute_setup_actions(
    execution_request: SetupActionExecutionRequest,
    request: Request,
) -> SetupActionExecutionResponse:
    """Execute approved setup actions with backend-owned execution paths."""

    try:
        model_service = get_model_service()
        download_manager = getattr(request.app.state, "download_manager", None)

        async def refresh_connection_tools(connection_id: str) -> Dict[str, Any]:
            from api.routes.connections.routes import refresh_tools

            connection = await refresh_tools(connection_id, request)
            return connection.model_dump(mode="json")

        results = await SetupAssistantActionExecutionService(
            download_manager=download_manager,
            model_service=model_service,
            connection_refresher=refresh_connection_tools,
        ).execute_approved_setup_actions(
            actions=execution_request.actions,
            tool_calls=execution_request.tool_calls,
        )
        return SetupActionExecutionResponse(results=results)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/profile/apply", response_model=SetupProfileApplyResponse)
async def apply_setup_profile_suggestions(
    request: SetupProfileApplyRequest,
) -> SetupProfileApplyResponse:
    """Save user-approved setup profile fields through personalization."""

    try:
        profile_data = UserProfileCreate(**request.approved_fields)
        profile = await PersonalizationService().create_or_update_user_profile(profile_data)
        _persist_approved_profile_memory(request.approved_fields)
        return SetupProfileApplyResponse(profile=profile.model_dump())
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/writing-samples/apply", response_model=SetupWritingSampleApplyResponse)
async def apply_setup_writing_sample(
    request: SetupWritingSampleApplyRequest,
) -> SetupWritingSampleApplyResponse:
    """Save a user-approved writing sample through personalization."""

    try:
        context_type = _coerce_context_type(request.context_type)
        sample = await PersonalizationService().add_writing_sample(
            content=request.content,
            source_type=SourceType.MANUAL_ENTRY,
            context_type=context_type,
            app_name=str(request.metadata.get("app_name", "Setup Assistant")),
            recipient=request.recipient,
            subject=request.metadata.get("subject"),
        )
        _persist_approved_writing_sample_memory(context_type, request.recipient)
        return SetupWritingSampleApplyResponse(
            sample_id=sample.id,
            context_type=context_type.value,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _coerce_context_type(context_type: str) -> ContextType:
    try:
        return ContextType(context_type)
    except ValueError:
        return ContextType.EMAIL_REPLY


def _persist_approved_profile_memory(approved_fields: Dict[str, Any]) -> None:
    """Mirror user-approved setup profile facts into free-text working memory."""
    memory_service = get_memory_service()
    entries_by_file: Dict[str, List[str]] = {
        "essentials.md": [],
        "user.md": [],
    }

    preferred_name = approved_fields.get("preferred_name")
    if isinstance(preferred_name, str) and preferred_name.strip():
        entries_by_file["essentials.md"].append(f"- User preferred name: {preferred_name.strip()}")

    full_name = approved_fields.get("full_name")
    if isinstance(full_name, str) and full_name.strip():
        entries_by_file["essentials.md"].append(f"- User full name: {full_name.strip()}")

    email = approved_fields.get("email")
    if isinstance(email, str) and email.strip():
        entries_by_file["essentials.md"].append(f"- User email: {email.strip()}")

    job_title = approved_fields.get("job_title")
    company_name = approved_fields.get("company_name")
    if isinstance(job_title, str) and job_title.strip():
        role_entry = f"- User role: {job_title.strip()}"
        if isinstance(company_name, str) and company_name.strip():
            role_entry += f" at {company_name.strip()}"
        entries_by_file["user.md"].append(role_entry)

    industry = approved_fields.get("industry")
    if isinstance(industry, str) and industry.strip():
        entries_by_file["user.md"].append(f"- User industry: {industry.strip()}")

    default_tone = approved_fields.get("default_tone")
    if isinstance(default_tone, str) and default_tone.strip():
        entries_by_file["user.md"].append(f"- User preferred tone: {default_tone.strip()}")

    default_formality = approved_fields.get("default_formality")
    if isinstance(default_formality, str) and default_formality.strip():
        entries_by_file["user.md"].append(f"- User preferred formality: {default_formality.strip()}")

    _append_setup_memory_entries(memory_service, entries_by_file)


def _persist_approved_writing_sample_memory(
    context_type: ContextType,
    recipient: Optional[str],
) -> None:
    """Record that setup captured an approved writing-style sample."""
    recipient_fragment = f" for {recipient.strip()}" if isinstance(recipient, str) and recipient.strip() else ""
    entry = (
        f"- User approved a {context_type.value} writing sample during setup"
        f"{recipient_fragment} for future style learning."
    )
    _append_setup_memory_entries(get_memory_service(), {"user.md": [entry]})


def _append_setup_memory_entries(
    memory_service: MemoryService,
    entries_by_file: Dict[str, List[str]],
) -> None:
    for file_name, entries in entries_by_file.items():
        for entry in entries:
            try:
                memory_service.append_memory_entry(file_name, entry)
            except MemoryFileBackpressureError as exc:
                logger.warning(
                    "Setup memory write skipped because %s needs consolidation: %s",
                    file_name,
                    exc,
                )
            except Exception as exc:
                logger.warning("Setup memory write failed for %s: %s", file_name, exc)

