"""Pydantic request/response models for the AssistantSession HTTP surface.

These are the wire schemas shared across the route families in this package.
External callers should not import from here directly; the response shapes
are part of the facade's public OpenAPI surface and are documented at
``/docs`` under the ``AssistantSession`` tag.
"""

from typing import Optional

from pydantic import BaseModel


class StartSessionResponse(BaseModel):
    session_id: str


class AssistantSessionOutputResponse(BaseModel):
    """Response body for non-streaming AssistantSession processing.

    Renamed from the legacy ``SuggestionResponse`` (and field
    ``suggestion`` -> ``assistant_output``) as part of the AssistantSession
    rename rollout.
    """
    transcription: str
    assistant_output: str


class ImagePathRequest(BaseModel):
    image_path: str


class ContextTextRequest(BaseModel):
    """Request body for ``POST /assistant-sessions/start_from_text``.

    Used by callers (e.g., the setup-launched Dill flow) that already hold
    the relevant context text and do not need the server to run OCR on a
    screen capture. The provided ``context_text`` is stored in the session's
    ``ocr_result`` slot as a synthetic OCRResult so the downstream
    audio/text processing pipelines find it where they expect.
    """

    context_text: str


class CancelSessionResponse(BaseModel):
    """Response for cancelling a AssistantSession session."""
    status: str
    session_id: str


class SaveSampleResponse(BaseModel):
    """Response for saving a AssistantSession output as a writing sample."""
    status: str
    sample_id: Optional[str] = None
    context_type: Optional[str] = None
    signature_detected: Optional[bool] = None
    contact_tracked: Optional[bool] = None
    error: Optional[str] = None
    message: Optional[str] = None


class AssistantSessionRehydrateResponse(BaseModel):
    """Response for rehydrating a AssistantSession session from history.

    Returned by ``POST /assistant-sessions/rehydrate-from-history/{assistant_output_id}``.
    A fresh in-memory session is created so the existing refine flow
    (``POST /assistant-sessions/{session_id}/refine``) can run against the
    historical state without requiring a new screen capture or initial
    recording.
    """
    session_id: str
    assistant_output_id: int
    output_text: str
    input_modality: Optional[str] = None
    user_request: Optional[str] = None
    context_text: Optional[str] = None
    explanation_text: Optional[str] = None
    model_name: Optional[str] = None
    app_name: Optional[str] = None
    refinement_count: int = 0
