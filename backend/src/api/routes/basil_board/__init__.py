"""BasilBoard API routes."""

from __future__ import annotations

from fastapi import APIRouter

from api.routes.basil_board import home_routes

router = APIRouter()
router.include_router(home_routes.router)

__all__ = ["router"]
