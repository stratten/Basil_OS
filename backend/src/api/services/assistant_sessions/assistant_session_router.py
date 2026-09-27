"""Public facade for the AssistantSession HTTP surface.

Aggregates the route families defined in
``assistant_session_router_components/route_*`` under a single
``/assistant-sessions`` ``APIRouter``. External callers should import only
``router`` from this module:

    from api.services.assistant_sessions.assistant_session_router import router

The actual endpoint handlers, streaming generators, response models, and
process-singleton state live in ``assistant_session_router_components``;
that package is an implementation detail and should not be imported from
outside this module.

Back-compat re-exports are provided for ``get_assistant_session_service`` and
``schedule_transcription_model_unload_with_voice_listener_check`` so any
existing import statements that referenced them via this module continue to
resolve without modification.
"""

import logging

from fastapi import APIRouter

from .assistant_session_router_components.route_personalization import router as personalization_router
from .assistant_session_router_components.route_refinement import router as refinement_router
from .assistant_session_router_components.route_session import router as session_router
from .assistant_session_router_components.route_assistant_session_input import router as assistant_session_process_router

# Back-compat re-exports.
from .assistant_session_router_components.model_unload_scheduling import (  # noqa: F401
    schedule_transcription_model_unload_with_voice_listener_check,
)
from .assistant_session_router_components.assistant_session_state import (  # noqa: F401
    get_assistant_session_service,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/assistant-sessions", tags=["Assistant Sessions"])
router.include_router(session_router)
router.include_router(assistant_session_process_router)
router.include_router(refinement_router)
router.include_router(personalization_router)
