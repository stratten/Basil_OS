"""Route module for ``POST /assistant-sessions/{session_id}/save-sample``.

A thin shell that defers to ``personalization_pipeline.save_assistant_session_as_sample``.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Body, Depends

from .personalization_pipeline import save_assistant_session_as_sample
from .assistant_session_models import SaveSampleResponse
from .assistant_session_state import get_assistant_session_service
from ..assistant_session_service import AssistantSessionService

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/{session_id}/save-sample", response_model=SaveSampleResponse)
async def save_assistant_session_as_sample_endpoint(
    session_id: str,
    service: AssistantSessionService = Depends(get_assistant_session_service),
    request_body: Optional[dict] = Body(None),
) -> SaveSampleResponse:
    """Save a AssistantSession as a writing sample for personalization.

    Called when the user explicitly clicks "Save as Sample" on a voice
    suggestion result. This captures the suggestion (or a user-edited
    variant) for future use in personalizing email/document generation.

    Optional request body:
        - content: str -- Custom content to save (overrides session
                          suggestion if provided)
    """
    return await save_assistant_session_as_sample(
        session_id=session_id,
        request_body=request_body,
        service=service,
    )
