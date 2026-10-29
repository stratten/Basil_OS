"""Meeting Companion routes: live snapshot, enable and disable, sources, chat, watches and feedback."""

import asyncio
import logging
import re
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException

from api.services.meeting_companion import offline
from api.services.meeting_companion.audit import AuditRejected
from api.services.meeting_companion.context_search import RootRejected
from api.services.meeting_companion.investigator.models import InvestigationRejected
from api.services.meeting_companion.models import (
    CompanionGlobalSettings,
    CompanionRoot,
    CompanionSnapshot,
    CompanionStatus,
    CompanionWatch,
)
from api.services.meeting_companion.proposals import ProposalNotFound, ProposalRejected
from api.services.meeting_companion.runtime import (
    CompanionNotLive,
    MeetingCompanionRuntime,
    get_meeting_companion_runtime,
)
from api.services.meeting_companion.session import UNSET, CompanionSession
from api.services.meeting_companion.watches import WatchRejected

from .companion_models import (
    CompanionChatAccepted,
    CompanionChatRequest,
    CompanionFeedbackRequest,
    CompanionGlobalSettingsUpdate,
    CompanionInvestigationAccepted,
    CompanionInvestigationRequest,
    CompanionAck,
    CompanionAuditAccepted,
    CompanionItemActionRequest,
    CompanionItemActionResult,
    CompanionProposalRequest,
    CompanionProposalResult,
    CompanionRootRequest,
    CompanionSettingsRequest,
    CompanionWatchRequest,
)

logger = logging.getLogger(__name__)
router = APIRouter()

_MEETING_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


def get_companion_runtime() -> MeetingCompanionRuntime:
    runtime = get_meeting_companion_runtime()
    if runtime is None:
        raise HTTPException(status_code=503, detail="The meeting Companion is not available.")
    return runtime


def _checked_meeting_id(meeting_id: str) -> str:
    if not _MEETING_ID.match(meeting_id):
        raise HTTPException(status_code=404, detail="Meeting not found.")
    return meeting_id


_RECORDING_WITHOUT_COMPANION = "Turn the Companion on to attach sources to this meeting while it is recording."


def _live_session(runtime: MeetingCompanionRuntime, meeting_id: str) -> CompanionSession:
    session = runtime.session_for(_checked_meeting_id(meeting_id))
    if session is None:
        raise HTTPException(status_code=409, detail="The Companion is only available while this meeting is recording with the Companion turned on.")
    return session


def _model_argument(request: CompanionSettingsRequest) -> Any:
    return request.model_id if "model_id" in request.model_fields_set else UNSET


async def _snapshot_for(runtime: MeetingCompanionRuntime, meeting_id: str) -> CompanionSnapshot:
    live = runtime.snapshot(meeting_id)
    if live is not None:
        return live
    stored = await asyncio.to_thread(offline.load_stored_snapshot, meeting_id)
    if stored is not None:
        return stored
    if await asyncio.to_thread(offline.meeting_exists, meeting_id):
        return offline.empty_snapshot(meeting_id)
    raise HTTPException(status_code=404, detail="Meeting not found.")


@router.get("/companion/settings", response_model=CompanionGlobalSettings)
async def get_global_settings(runtime: MeetingCompanionRuntime = Depends(get_companion_runtime)) -> CompanionGlobalSettings:
    return await asyncio.to_thread(runtime.get_global_settings)


@router.put("/companion/settings", response_model=CompanionGlobalSettings)
async def put_global_settings(
    update: CompanionGlobalSettingsUpdate,
    runtime: MeetingCompanionRuntime = Depends(get_companion_runtime),
) -> CompanionGlobalSettings:
    return await asyncio.to_thread(
        lambda: runtime.update_global_settings(
            auto_enable=update.auto_enable,
            default_mode=update.default_mode,
            screen_share_note_dismissed=update.screen_share_note_dismissed,
            next_focus=update.next_focus,
            proposal_mode=update.proposal_mode,
            proposal_capabilities=update.proposal_capabilities,
            auto_execute_capabilities=update.auto_execute_capabilities,
        )
    )


@router.get("/{meeting_id}/companion", response_model=CompanionSnapshot)
async def get_companion(meeting_id: str, runtime: MeetingCompanionRuntime = Depends(get_companion_runtime)) -> CompanionSnapshot:
    return await _snapshot_for(runtime, _checked_meeting_id(meeting_id))


@router.post("/{meeting_id}/companion/enable", response_model=CompanionSnapshot)
async def enable_companion(
    meeting_id: str,
    request: CompanionSettingsRequest,
    runtime: MeetingCompanionRuntime = Depends(get_companion_runtime),
) -> CompanionSnapshot:
    _checked_meeting_id(meeting_id)
    try:
        session = await runtime.enable(
            meeting_id,
            mode=request.mode,
            model_id=_model_argument(request),
            focus=request.focus,
            investigate=request.investigate,
        )
    except CompanionNotLive:
        raise HTTPException(status_code=409, detail="The Companion can only be turned on while this meeting is recording.")
    return session.snapshot(meeting_id)


@router.post("/{meeting_id}/companion/disable", response_model=CompanionSnapshot)
async def disable_companion(meeting_id: str, runtime: MeetingCompanionRuntime = Depends(get_companion_runtime)) -> CompanionSnapshot:
    _checked_meeting_id(meeting_id)
    await runtime.disable(meeting_id)
    return await _snapshot_for(runtime, meeting_id)


@router.patch("/{meeting_id}/companion/settings", response_model=CompanionStatus)
async def patch_companion_settings(
    meeting_id: str,
    request: CompanionSettingsRequest,
    runtime: MeetingCompanionRuntime = Depends(get_companion_runtime),
) -> CompanionStatus:
    session = _live_session(runtime, meeting_id)
    session.update_settings(mode=request.mode, model_id=_model_argument(request), focus=request.focus, investigate=request.investigate)
    return session.status()


@router.post("/{meeting_id}/companion/roots", response_model=CompanionRoot, status_code=201)
async def attach_companion_root(
    meeting_id: str,
    request: CompanionRootRequest,
    runtime: MeetingCompanionRuntime = Depends(get_companion_runtime),
) -> CompanionRoot:
    """Attach a source to a live Companion, or to a finished meeting's saved notes. A recording meeting whose Companion is off refuses, so the client queues the source."""
    _checked_meeting_id(meeting_id)
    session = runtime.session_for(meeting_id)
    try:
        if session is not None:
            return session.attach_root(request.path)
        if runtime.is_recording(meeting_id):
            raise HTTPException(status_code=409, detail=_RECORDING_WITHOUT_COMPANION)
        stored = await asyncio.to_thread(offline.attach_stored_root, meeting_id, request.path)
    except RootRejected as rejection:
        raise HTTPException(status_code=422, detail=str(rejection))
    if stored is None:
        raise HTTPException(status_code=404, detail="Meeting not found.")
    runtime.stored_investigations.sync_attached(meeting_id, stored)
    return stored


@router.delete("/{meeting_id}/companion/roots/{root_id}", response_model=CompanionAck)
async def detach_companion_root(
    meeting_id: str,
    root_id: str,
    runtime: MeetingCompanionRuntime = Depends(get_companion_runtime),
) -> CompanionAck:
    _checked_meeting_id(meeting_id)
    session = runtime.session_for(meeting_id)
    if session is not None:
        detached: Optional[bool] = session.detach_root(root_id)
    elif runtime.is_recording(meeting_id):
        raise HTTPException(status_code=409, detail=_RECORDING_WITHOUT_COMPANION)
    else:
        detached = await asyncio.to_thread(offline.detach_stored_root, meeting_id, root_id)
        if detached is None:
            raise HTTPException(status_code=404, detail="This meeting has no saved Companion notes.")
        if detached:
            runtime.stored_investigations.sync_detached(meeting_id, root_id)
    if not detached:
        raise HTTPException(status_code=404, detail="That source is not attached.")
    return CompanionAck()


@router.post("/{meeting_id}/companion/items/{item_id}/feedback", response_model=CompanionAck)
async def record_companion_feedback(
    meeting_id: str,
    item_id: str,
    request: CompanionFeedbackRequest,
    runtime: MeetingCompanionRuntime = Depends(get_companion_runtime),
) -> CompanionAck:
    _checked_meeting_id(meeting_id)
    session = runtime.session_for(meeting_id)
    if session is not None:
        recorded: Optional[bool] = session.record_feedback(item_id, request.action)
    else:
        recorded = await asyncio.to_thread(offline.record_stored_feedback, meeting_id, item_id, request.action)
        if recorded is None:
            raise HTTPException(status_code=404, detail="This meeting has no saved Companion notes.")
    if not recorded:
        raise HTTPException(status_code=404, detail="That Companion item does not exist.")
    return CompanionAck()


@router.post("/{meeting_id}/companion/chat", response_model=CompanionChatAccepted, status_code=202)
async def send_companion_chat(
    meeting_id: str,
    request: CompanionChatRequest,
    runtime: MeetingCompanionRuntime = Depends(get_companion_runtime),
) -> CompanionChatAccepted:
    session = _live_session(runtime, meeting_id)
    try:
        return CompanionChatAccepted(message_id=session.submit_chat(request.text))
    except ValueError as invalid:
        raise HTTPException(status_code=422, detail=str(invalid))
    except RuntimeError as closed:
        raise HTTPException(status_code=409, detail=str(closed))


@router.post("/{meeting_id}/companion/watches", response_model=CompanionWatch, status_code=201)
async def create_companion_watch(
    meeting_id: str,
    request: CompanionWatchRequest,
    runtime: MeetingCompanionRuntime = Depends(get_companion_runtime),
) -> CompanionWatch:
    session = _live_session(runtime, meeting_id)
    try:
        return session.create_watch(request.topic, request.instruction)
    except WatchRejected as rejection:
        raise HTTPException(status_code=422, detail=str(rejection))


@router.delete("/{meeting_id}/companion/watches/{watch_id}", response_model=CompanionAck)
async def cancel_companion_watch(
    meeting_id: str,
    watch_id: str,
    runtime: MeetingCompanionRuntime = Depends(get_companion_runtime),
) -> CompanionAck:
    session = _live_session(runtime, meeting_id)
    if not session.cancel_watch(watch_id):
        raise HTTPException(status_code=404, detail="That watch does not exist or was already canceled.")
    return CompanionAck()


@router.post("/{meeting_id}/companion/investigations", response_model=CompanionInvestigationAccepted, status_code=202)
async def start_companion_investigation(
    meeting_id: str,
    request: CompanionInvestigationRequest,
    runtime: MeetingCompanionRuntime = Depends(get_companion_runtime),
) -> CompanionInvestigationAccepted:
    _checked_meeting_id(meeting_id)
    session = runtime.session_for(meeting_id)
    try:
        if session is not None:
            investigation_id: Optional[str] = session.request_investigation(request.question, request.reply_to_message_id)
        else:
            investigation_id = await runtime.stored_investigations.request(meeting_id, request.question, request.reply_to_message_id)
            if investigation_id is None:
                raise HTTPException(status_code=404, detail="This meeting has no saved Companion notes.")
        return CompanionInvestigationAccepted(investigation_id=investigation_id)
    except InvestigationRejected as rejection:
        raise HTTPException(status_code=409, detail=str(rejection))
    except ValueError as invalid:
        raise HTTPException(status_code=422, detail=str(invalid))
    except RuntimeError as closed:
        raise HTTPException(status_code=409, detail=str(closed))


@router.delete("/{meeting_id}/companion/investigations/{investigation_id}", response_model=CompanionAck)
async def cancel_companion_investigation(
    meeting_id: str,
    investigation_id: str,
    runtime: MeetingCompanionRuntime = Depends(get_companion_runtime),
) -> CompanionAck:
    _checked_meeting_id(meeting_id)
    session = runtime.session_for(meeting_id)
    canceled = session.cancel_investigation(investigation_id) if session is not None else runtime.stored_investigations.cancel(meeting_id, investigation_id)
    if not canceled:
        raise HTTPException(status_code=404, detail="That investigation is not running.")
    return CompanionAck()


@router.post("/{meeting_id}/companion/audit", response_model=CompanionAuditAccepted, status_code=202)
async def start_companion_audit(
    meeting_id: str,
    runtime: MeetingCompanionRuntime = Depends(get_companion_runtime),
) -> CompanionAuditAccepted:
    """Audit the meeting in the background; the report arrives as an ``audit`` timeline event."""
    _checked_meeting_id(meeting_id)
    session = runtime.session_for(meeting_id)
    try:
        if session is not None:
            session.request_audit()
        elif await runtime.stored_audits.request(meeting_id) is None:
            raise HTTPException(status_code=404, detail="This meeting has no saved Companion notes.")
    except AuditRejected as rejection:
        raise HTTPException(status_code=409, detail=str(rejection))
    return CompanionAuditAccepted()


@router.post("/{meeting_id}/companion/items/{item_id}/action", response_model=CompanionItemActionResult)
async def act_on_companion_item(
    meeting_id: str,
    item_id: str,
    request: CompanionItemActionRequest,
    runtime: MeetingCompanionRuntime = Depends(get_companion_runtime),
) -> CompanionItemActionResult:
    """Make a to-do or hand an agent a note; the click is the approval."""
    _checked_meeting_id(meeting_id)
    session = runtime.session_for(meeting_id)
    try:
        if session is not None:
            result = await session.act_on_item(item_id, request.action)
        else:
            stored = await offline.act_on_stored_item(meeting_id, item_id, request.action, runtime.proposal_launcher, runtime.proposal_policy)
            if stored is None:
                raise HTTPException(status_code=404, detail="This meeting has no saved Companion notes.")
            result = stored
    except ProposalNotFound as missing:
        raise HTTPException(status_code=404, detail=str(missing))
    except ProposalRejected as rejection:
        raise HTTPException(status_code=409, detail=str(rejection))
    outcome = result.decision
    return CompanionItemActionResult(
        item_id=result.card_id,
        state=outcome.state,  # type: ignore[arg-type]
        title=outcome.title,
        instruction=outcome.instruction,
        todo_id=outcome.todo_id,
        agent_task_id=outcome.agent_task_id,
        error=outcome.error,
    )


@router.post("/{meeting_id}/companion/items/{item_id}/proposal", response_model=CompanionProposalResult)
async def decide_companion_proposal(
    meeting_id: str,
    item_id: str,
    request: CompanionProposalRequest,
    runtime: MeetingCompanionRuntime = Depends(get_companion_runtime),
) -> CompanionProposalResult:
    _checked_meeting_id(meeting_id)
    session = runtime.session_for(meeting_id)
    try:
        if session is not None:
            outcome = await session.decide_proposal(item_id, request.decision)
        else:
            stored = await offline.decide_stored_proposal(meeting_id, item_id, request.decision, runtime.proposal_launcher)
            if stored is None:
                raise HTTPException(status_code=404, detail="This meeting has no saved Companion notes.")
            outcome = stored
    except ProposalNotFound as missing:
        raise HTTPException(status_code=404, detail=str(missing))
    except ProposalRejected as rejection:
        raise HTTPException(status_code=409, detail=str(rejection))
    return CompanionProposalResult(
        state=outcome.state,  # type: ignore[arg-type]
        title=outcome.title,
        instruction=outcome.instruction,
        todo_id=outcome.todo_id,
        agent_task_id=outcome.agent_task_id,
        error=outcome.error,
    )
