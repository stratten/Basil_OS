"""Central FastAPI router registration for the Basil API."""

from __future__ import annotations

import logging

from fastapi import APIRouter, FastAPI

from api.core.hotkey.router import HotkeyRouter
from api.routes import websocket
from api.routes.ambient_suggestions import router as ambient_suggestions_router
from api.routes.agent_tasks import (
    execution_control_router,
    router as agent_task_router,
    run_router as agent_task_run_router,
    schedule_router as agent_task_schedule_router,
)
from api.routes.capture import (
    activity_capture_router,
    capture_management_router,
    capture_router,
    manual_capture_router,
)
from api.routes.connections import router as connections_router
from api.routes.todos import router as todo_router
from api.routes.basil_board import router as basil_board_router
from api.routes.model_routes import (
    custom_models_router,
    model_management_router,
    model_testing_router,
    models_router,
)
from api.routes.meeting_detection import router as meeting_detection_router
from api.routes.meetings import (
    live_transcription_router,
    router as meetings_router,
)
from api.routes.memory import (
    reconciliation_router as memory_reconciliation_router,
    router as memory_router,
)
from api.routes.onboarding import router as onboarding_router
from api.routes.personalization import router as personalization_router
from api.routes.provider_profiles import router as provider_profiles_router
from api.routes.setup_assistant import router as setup_assistant_router
from api.routes.settings_routes import router as settings_router
from api.routes.startup_status_router import router as startup_status_router
from api.routes.transcription import router as transcription_router
from api.routes.voice_listener_routes import router as voice_listener_router
from api.core.config.api_settings import settings
from api.services.ios_pairing.ios_pair_router import router as ios_pair_router
from api.services.assistant_output_history.assistant_output_history_router import (
    router as assistant_output_history_router,
)
from api.services.assistant_sessions.assistant_session_router import (
    router as assistant_session_router,
)
from api.services.conversation import router as conversation_router
from api.services.image_processing import router as image_processing_router
from api.services.ocr.ocr_routes import ocr_router


def build_ordered_application_routers() -> list[APIRouter]:
    """Build routers in the app's route-registration order."""
    hotkey_router = HotkeyRouter()
    return [
        model_testing_router,
        manual_capture_router,
        settings_router,
        models_router,
        model_management_router,
        websocket.router,
        ambient_suggestions_router,
        meeting_detection_router,
        live_transcription_router,
        meetings_router,
        ocr_router,
        image_processing_router,
        conversation_router,
        assistant_session_router,
        assistant_output_history_router,
        startup_status_router,
        capture_management_router,
        capture_router,
        voice_listener_router,
        agent_task_router,
        agent_task_schedule_router,
        agent_task_run_router,
        execution_control_router,
        personalization_router,
        memory_router,
        memory_reconciliation_router,
        onboarding_router,
        setup_assistant_router,
        todo_router,
        basil_board_router,
        custom_models_router,
        connections_router,
        provider_profiles_router,
        activity_capture_router,
        hotkey_router.router,
    ]


def register_application_routers(app: FastAPI, logger: logging.Logger) -> None:
    """Register application routers while preserving route precedence."""
    for router in build_ordered_application_routers():
        app.include_router(router)

    if settings.IOS_PAIR_ENABLED:
        logger.info("Registering iOS pairing router")
        app.include_router(ios_pair_router)

    logger.info("Registering transcription router with routes:")
    for route in transcription_router.routes:
        # Newer FastAPI represents an included sub-router as an entry without a path or methods.
        route_path = getattr(route, "path", None)
        if route_path is None:
            continue
        logger.info(f"  - {route_path} [{', '.join(sorted(getattr(route, 'methods', None) or []))}]")
    app.include_router(transcription_router)


__all__ = ["build_ordered_application_routers", "register_application_routers"]
