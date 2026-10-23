"""Onboarding-specific connection recommendation endpoints."""

from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter
from pydantic import BaseModel, Field

from api.services.setup_assistant.connection_recommendation_service import (
    SetupAssistantConnectionRecommendationService,
)


router = APIRouter(prefix="/connections", tags=["Setup Assistant"])


class SetupConnectionCatalogRequest(BaseModel):
    starter_servers: List[Dict[str, Any]] = Field(default_factory=list)
    registered_connections: List[Dict[str, Any]] = Field(default_factory=list)


class SetupConnectionCatalogResponse(BaseModel):
    cards: List[Dict[str, Any]]


@router.post("/catalog/cards", response_model=SetupConnectionCatalogResponse)
async def build_setup_connection_cards(
    request: SetupConnectionCatalogRequest,
) -> SetupConnectionCatalogResponse:
    """Build catalog-driven connection cards from supported connection state."""

    cards = SetupAssistantConnectionRecommendationService().build_connection_card_inputs(
        starter_servers=request.starter_servers,
        registered_connections=request.registered_connections,
    )
    return SetupConnectionCatalogResponse(cards=cards)

