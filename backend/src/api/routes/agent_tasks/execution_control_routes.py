"""Composite router for agent-task execution-control routes."""

from fastapi import APIRouter

from .session_control_routes import router as session_control_router

router = APIRouter(
    prefix="/api/v1/agent-tasks",
    tags=["agent_tasks"],
)

router.include_router(session_control_router)
