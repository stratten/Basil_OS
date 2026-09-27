"""Process-singleton state for the AssistantSession HTTP router.

All four pieces of module-level state for the AssistantSession route family
live here, so every pipeline and every route module mutates the same objects
(not copies). External code should never read or write these directly --
``get_assistant_session_service`` and ``get_assistant_output_history_service`` are the only
intended access points, and they are wired into FastAPI via
``Depends(get_assistant_session_service)`` from the route modules.

Mutation pattern:
    from . import assistant_session_state
    assistant_session_state.model_unload_task = new_task          # rebind the module attr
    assistant_session_state.active_ocr_tasks[session_id] = task   # mutate in place

Importing the names directly (e.g. ``from .assistant_session_state import model_unload_task``)
would capture a stale reference at import time -- always go through the
module attribute.
"""

import asyncio
import logging
from typing import Dict, Optional

from ..assistant_session_service import AssistantSessionService
from ...assistant_output_history.assistant_output_history_service import AssistantOutputHistoryService
from ....dependencies import get_sqlite_knowledge_service

logger = logging.getLogger(__name__)


assistant_session_service_instance: Optional[AssistantSessionService] = None
"""Lazily-initialised singleton AssistantSessionService for the process."""

_assistant_output_history_service_instance: Optional[AssistantOutputHistoryService] = None
"""Lazily-initialised singleton AssistantOutputHistoryService for the process."""

model_unload_task: Optional[asyncio.Task] = None
"""Handle for the most recently scheduled transcription-model unload task.

Pipelines rebind this via ``assistant_session_state.model_unload_task = new_task`` after
calling ``schedule_transcription_model_unload_with_voice_listener_check``.
"""

active_ocr_tasks: Dict[str, asyncio.Task] = {}
"""Map of session_id -> in-flight OCR ``asyncio.Task`` so that
``DELETE /cancel/{session_id}`` can cancel an OCR pass that is still running
when the user dismisses the widget."""


def get_assistant_session_service() -> AssistantSessionService:
    """FastAPI dependency: resolve (and lazily build) the shared service.

    Reuses the wake-word service's transcription pipeline when one is
    available on ``app.state``; otherwise constructs a standalone
    ``AssistantSessionService`` that owns its own transcription stack.
    """
    global assistant_session_service_instance
    if assistant_session_service_instance is None:
        try:
            from ....main import app
            if hasattr(app.state, 'wake_word_service') and app.state.wake_word_service:
                transcription_service = app.state.wake_word_service.transcription_service
                assistant_session_service_instance = AssistantSessionService(transcription_service=transcription_service)
                logger.info("AssistantSession service initialized with shared transcription service")
            else:
                logger.warning("No shared transcription service found, AssistantSession will create its own")
                assistant_session_service_instance = AssistantSessionService()
        except Exception as e:
            logger.warning(f"Error accessing shared transcription service: {e}")
            assistant_session_service_instance = AssistantSessionService()

    return assistant_session_service_instance


def get_assistant_output_history_service() -> AssistantOutputHistoryService:
    """Lazily build and return the singleton ``AssistantOutputHistoryService``.

    Used by the refinement pipeline for persisting refinement turns and by
    the rehydration factory for loading historical AssistantSession outputs.
    """
    global _assistant_output_history_service_instance
    if _assistant_output_history_service_instance is None:
        _assistant_output_history_service_instance = AssistantOutputHistoryService(get_sqlite_knowledge_service())
    return _assistant_output_history_service_instance
