"""Router composition for the setup assistant API."""

from __future__ import annotations

from fastapi import APIRouter

from . import (
    agent_routes,
    action_routes,
    completion_routes,
    connection_routes,
    discovery_routes,
    model_access_routes,
    proposal_routes,
    recommendation_routes,
)


router = APIRouter(prefix="/setup-assistant", tags=["Setup Assistant"])
router.include_router(agent_routes.router)
router.include_router(recommendation_routes.router)
router.include_router(discovery_routes.router)
router.include_router(action_routes.router)
router.include_router(proposal_routes.router)
router.include_router(connection_routes.router)
router.include_router(completion_routes.router)
router.include_router(model_access_routes.router)

