"""Composite router for agent-task execution-control routes."""

from fastapi import APIRouter

from .run_control_routes import router as run_control_router
from .session_control_routes import router as session_control_router

router = APIRouter(
    prefix="/api/v1/agent-tasks",
    tags=["agent_tasks"],
)

router.include_router(session_control_router)
router.include_router(run_control_router)
