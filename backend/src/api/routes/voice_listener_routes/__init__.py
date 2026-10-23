"""Voice listener routes - main router aggregating all voice listener functionality."""

from fastapi import APIRouter
import logging

# Import voice-listener-only subrouters
from .control_routes import router as control_router
from .wake_word_routes import router as wake_word_router

logger = logging.getLogger(__name__)

# Create the main voice listener router
router = APIRouter(
    prefix="/api/v1/voice-listener",
    tags=["Voice Listener"],
)

# Include all subrouters
router.include_router(control_router)
router.include_router(wake_word_router)

# Note: Voice listener settings have been moved to /settings/voice-listener
# and /settings/agent-task as part of the settings API reorganization.
# This keeps all application settings under the /settings prefix for consistency.

__all__ = ["router"]

