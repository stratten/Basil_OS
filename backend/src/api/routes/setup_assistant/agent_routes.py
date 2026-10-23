"""Model-backed Basil setup agent endpoints."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from starlette.responses import StreamingResponse

from api.routes.setup_assistant.models import (
    SetupAgentEventKind,
    SetupAgentRequest,
    SetupSuggestionChip,
)
from api.services.setup_assistant.agent_service import SetupAssistantAgentService


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/agent", tags=["Setup Assistant"])
setup_agent_service = SetupAssistantAgentService()

FINALIZE_TIMEOUT_SECONDS = 12.0


class SetupWrapUpResponse(BaseModel):
    """Payload returned by the synchronous finalize endpoint."""

    recap: str = Field(min_length=1)
    recommended_next_steps: List[SetupSuggestionChip] = Field(default_factory=list)
    optional_breadth: Optional[str] = None


@router.post("/stream")
async def stream_setup_agent_events(request: SetupAgentRequest) -> StreamingResponse:
    """Stream setup-agent events as Basil reasons and calls setup tools."""

    async def event_stream():
        async for event in setup_agent_service.respond_stream(request):
            yield f"data: {json.dumps(event.model_dump(mode='json'), default=str)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/finalize", response_model=SetupWrapUpResponse)
async def finalize_setup_agent(request: SetupAgentRequest) -> SetupWrapUpResponse:
    """Run one synchronous agent turn that forces a propose_wrap_up call and return its payload.

    Used when the user clicks Done before the agent has already proposed a wrap-up. The
    React UI shows an immediate honest 'preparing review' panel and then swaps in the
    rich recap returned here.
    """

    async def collect_wrap_up_payload() -> Dict[str, Any]:
        async for event in setup_agent_service.respond_stream(request, finalize_mode=True):
            if event.kind == SetupAgentEventKind.wrap_up_proposed:
                return event.payload
            if event.kind == SetupAgentEventKind.error:
                raise HTTPException(
                    status_code=502,
                    detail=event.payload.get("message", "Setup agent finalize failed."),
                )
        raise HTTPException(
            status_code=422,
            detail="Setup agent did not propose a wrap-up during finalize turn.",
        )

    try:
        payload = await asyncio.wait_for(
            collect_wrap_up_payload(),
            timeout=FINALIZE_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError as exc:
        logger.warning("Setup agent finalize timed out after %ss", FINALIZE_TIMEOUT_SECONDS)
        raise HTTPException(
            status_code=504,
            detail="Setup agent finalize timed out.",
        ) from exc

    next_steps_raw = payload.get("recommended_next_steps") or []
    next_steps: List[SetupSuggestionChip] = []
    for chip in next_steps_raw:
        if isinstance(chip, SetupSuggestionChip):
            next_steps.append(chip)
        elif isinstance(chip, dict):
            try:
                next_steps.append(SetupSuggestionChip(**chip))
            except Exception as exc:  # pragma: no cover - malformed chip from agent
                logger.warning("Skipping malformed wrap-up chip: %s", exc)

    optional_breadth_raw = payload.get("optional_breadth")
    optional_breadth = (
        optional_breadth_raw.strip()
        if isinstance(optional_breadth_raw, str) and optional_breadth_raw.strip()
        else None
    )

    recap = str(payload.get("recap", "")).strip() or "Setup wrap-up is ready."

    return SetupWrapUpResponse(
        recap=recap,
        recommended_next_steps=next_steps,
        optional_breadth=optional_breadth,
    )
