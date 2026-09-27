"""Agent task route package exports."""

from .core_routes import router
from .audio_routes import router as audio_router
from .execution_approval_routes import router as execution_approval_router
from .execution_control_routes import router as execution_control_router
from .history_routes import router as history_router
from .local_preview_routes import router as local_preview_router
from .managed_file_history_routes import router as managed_file_history_router
from .provider_interaction_routes import router as provider_interaction_router
from .schedule_routes import run_router, schedule_router

router.include_router(audio_router)
router.include_router(execution_approval_router)
router.include_router(provider_interaction_router)
router.include_router(local_preview_router)
router.include_router(managed_file_history_router)
# history_router's GET /{agent_task_id} is a catch-all single-segment path.
# It must be included last so it never shadows the specific literal routes
# above (e.g. GET /whitelist, GET /examples) that Starlette would otherwise
# never reach once the generic path claims a full match first.
router.include_router(history_router)

__all__ = ["router", "schedule_router", "run_router", "execution_control_router"]
