"""Meeting Companion routes: live snapshot, enable and disable, sources, chat, watches and feedback."""

import asyncio
import logging
import re
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException

from api.services.meeting_companion import offline
from api.services.meeting_companion.context_search import RootRejected
from api.services.meeting_companion.models import (
    CompanionGlobalSettings,
    CompanionRoot,
    CompanionSnapshot,
    CompanionStatus,
    CompanionWatch,
)
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
    CompanionAck,
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
        session = await runtime.enable(meeting_id, mode=request.mode, model_id=_model_argument(request), focus=request.focus)
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
    session.update_settings(mode=request.mode, model_id=_model_argument(request), focus=request.focus)
    return session.status()


@router.post("/{meeting_id}/companion/roots", response_model=CompanionRoot, status_code=201)
async def attach_companion_root(
    meeting_id: str,
    request: CompanionRootRequest,
    runtime: MeetingCompanionRuntime = Depends(get_companion_runtime),
) -> CompanionRoot:
    session = _live_session(runtime, meeting_id)
    try:
        return session.attach_root(request.path)
    except RootRejected as rejection:
        raise HTTPException(status_code=422, detail=str(rejection))


@router.delete("/{meeting_id}/companion/roots/{root_id}", response_model=CompanionAck)
async def detach_companion_root(
    meeting_id: str,
    root_id: str,
    runtime: MeetingCompanionRuntime = Depends(get_companion_runtime),
) -> CompanionAck:
    session = _live_session(runtime, meeting_id)
    if not session.detach_root(root_id):
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
