"""BasilBoard Home routes."""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from api.dependencies import (
    get_agent_task_submission_service,
    get_conversation_service,
)
from api.services.agent_processing.lifecycle.submission import AgentTaskSubmissionService
from api.services.basil_board.home_turn_router import HomeTurnRouter
from api.services.basil_board.models import (
    BasilBoardHydration,
    BoardInquiryDetail,
    HomeTranscribeResponse,
    HomeTurnRequest,
    HomeTurnRerouteRequest,
    HomeTurnResponse,
)
from api.services.basil_board.service import BasilBoardService
from api.services.conversation.conversation_service import ConversationService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/basil-board", tags=["BasilBoard"])

_service_instance: Optional[BasilBoardService] = None


def _get_board_service() -> BasilBoardService:
    global _service_instance
    if _service_instance is None:
        _service_instance = BasilBoardService()
    return _service_instance


def _router(
    conversation_service: ConversationService = Depends(get_conversation_service),
    submission_service: AgentTaskSubmissionService = Depends(get_agent_task_submission_service),
) -> HomeTurnRouter:
    return HomeTurnRouter(
        basil_board_service=_get_board_service(),
        conversation_service=conversation_service,
        agent_task_submission_service=submission_service,
    )


@router.get("/hydrate", response_model=BasilBoardHydration)
async def hydrate_basil_board() -> BasilBoardHydration:
    try:
        return await _get_board_service().hydrate_board()
    except Exception as exc:
        logger.error("Error hydrating BasilBoard: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error hydrating BasilBoard: {exc}") from exc


@router.get("/inquiries/{inquiry_id}", response_model=BoardInquiryDetail)
async def get_board_inquiry(inquiry_id: str) -> BoardInquiryDetail:
    try:
        inquiry = await _get_board_service().hydrate_inquiry(inquiry_id)
    except Exception as exc:
        logger.error("Error hydrating inquiry %s: %s", inquiry_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error hydrating inquiry: {exc}") from exc
    if not inquiry:
        raise HTTPException(status_code=404, detail="Inquiry not found")
    return inquiry


@router.post("/home/turn", response_model=HomeTurnResponse)
async def submit_home_turn(
    body: HomeTurnRequest,
    turn_router: HomeTurnRouter = Depends(_router),
) -> HomeTurnResponse:
    if not body.content.strip():
        raise HTTPException(status_code=400, detail="content must not be blank")
    try:
        return await turn_router.submit_turn(body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("Error submitting Home turn: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error submitting Home turn: {exc}") from exc


@router.post("/home/inquiries/{inquiry_id}/reroute", response_model=HomeTurnResponse)
async def reroute_home_inquiry(
    inquiry_id: str,
    body: HomeTurnRerouteRequest,
    turn_router: HomeTurnRouter = Depends(_router),
) -> HomeTurnResponse:
    try:
        return await turn_router.reroute_inquiry(inquiry_id, body.route_kind)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("Error rerouting Home inquiry %s: %s", inquiry_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error rerouting Home inquiry: {exc}") from exc


async def _transcribe_basil_board_voice(
    audio_file: UploadFile,
    *,
    source: str,
    notes: str,
    capture_method: str,
    default_filename: str,
) -> HomeTranscribeResponse:
    from api.dependencies import resolve_transcription_service

    if not audio_file.content_type or not audio_file.content_type.startswith("audio/"):
        return HomeTranscribeResponse(
            success=False,
            transcription="",
            error_code="invalid_content_type",
        )

    audio_data = await audio_file.read()
    if len(audio_data) < 44:
        return HomeTranscribeResponse(
            success=False,
            transcription="",
            error_code="audio_too_small",
        )

    transcription_service = resolve_transcription_service()
    if not transcription_service:
        raise HTTPException(status_code=500, detail="Transcription service not available")

    context_info = {
        "source": source,
        "notes": notes,
        "original_filename": audio_file.filename or default_filename,
        "capture_method": capture_method,
        "file_size": len(audio_data),
        "content_type": audio_file.content_type,
    }

    try:
        transcribed_text = await transcription_service.transcribe(
            audio_data,
            context_info=context_info,
        )
    except Exception as exc:
        logger.error("BasilBoard transcription failed: %s", exc, exc_info=True)
        return HomeTranscribeResponse(
            success=False,
            transcription="",
            error_code="transcription_failed",
        )

    if not transcribed_text or not transcribed_text.strip():
        return HomeTranscribeResponse(
            success=False,
            transcription="",
            error_code="no_speech",
        )

    return HomeTranscribeResponse(success=True, transcription=transcribed_text.strip())


@router.post("/home/transcribe", response_model=HomeTranscribeResponse)
async def transcribe_home_turn(
    audio_file: UploadFile = File(...),
) -> HomeTranscribeResponse:
    return await _transcribe_basil_board_voice(
        audio_file,
        source="basil_board_home",
        notes="BasilBoard Home voice capture",
        capture_method="basil_board_home_voice",
        default_filename="home_turn.wav",
    )


@router.post("/conversation/transcribe", response_model=HomeTranscribeResponse)
async def transcribe_conversation_turn(
    audio_file: UploadFile = File(...),
) -> HomeTranscribeResponse:
    return await _transcribe_basil_board_voice(
        audio_file,
        source="basil_board_conversation",
        notes="BasilBoard Conversation voice capture",
        capture_method="basil_board_conversation_voice",
        default_filename="conversation_turn.wav",
    )


@router.get("/home/turns/{message_id}", response_model=HomeTurnResponse)
async def reconcile_home_turn(message_id: str) -> HomeTurnResponse:
    turn = await _get_board_service().reconcile_home_turn(message_id)
    if not turn:
        raise HTTPException(status_code=404, detail="Home turn not found")

    assistant_content = None
    if turn.assistant_message_id:
        messages = await _get_board_service()._repo.list_conversation_messages(turn.conversation_id)
        assistant_content = next(
            (item["content"] for item in messages if item["id"] == turn.assistant_message_id),
            None,
        )

    inquiry = await _get_board_service()._repo.get_inquiry_by_user_message(message_id)
    inquiry_id = inquiry.id if inquiry else message_id

    return HomeTurnResponse(
        inquiry_id=inquiry_id,
        user_message_id=turn.user_message_id,
        conversation_id=turn.conversation_id,
        route_kind=turn.route_kind,
        route_reason=turn.route_reason,
        route_confidence=turn.route_confidence,
        state=turn.state,
        assistant_message_id=turn.assistant_message_id,
        agent_task_id=turn.agent_task_id,
        assistant_content=assistant_content,
    )
