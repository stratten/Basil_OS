"""Discovery endpoints for the setup assistant."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from api.core.services.model_service import ModelService
from api.dependencies import get_model_service
from api.routes.setup_assistant.models import SetupDiscoveryResponse
from api.services.setup_assistant.discovery_service import SetupAssistantDiscoveryService


router = APIRouter(prefix="/discovery", tags=["Setup Assistant"])


class SentEmailMetadataDiscoveryRequest(BaseModel):
    days_back: int = Field(default=14, ge=1, le=60)
    limit: int = Field(default=25, ge=1, le=50)


@router.get("/low-risk", response_model=SetupDiscoveryResponse)
async def collect_low_risk_setup_discovery(
    model_service: ModelService = Depends(get_model_service),
) -> SetupDiscoveryResponse:
    """Collect non-mutating setup facts that do not inspect user content."""

    service = SetupAssistantDiscoveryService(model_service=model_service)
    return await service.collect_low_risk_setup_facts()


@router.get("/models/catalog", response_model=SetupDiscoveryResponse)
async def collect_model_catalog_setup_discovery(
    model_service: ModelService = Depends(get_model_service),
) -> SetupDiscoveryResponse:
    """Collect model catalog facts for onboarding recommendations."""

    service = SetupAssistantDiscoveryService(model_service=model_service)
    return await service.collect_model_catalog_facts()


@router.get("/email-clients", response_model=SetupDiscoveryResponse)
async def collect_email_client_setup_discovery(
    model_service: ModelService = Depends(get_model_service),
) -> SetupDiscoveryResponse:
    """Detect available email clients without reading message contents."""

    service = SetupAssistantDiscoveryService(model_service=model_service)
    return await service.collect_email_client_facts()


@router.get("/connections/catalog", response_model=SetupDiscoveryResponse)
async def collect_connection_catalog_setup_discovery(
    model_service: ModelService = Depends(get_model_service),
) -> SetupDiscoveryResponse:
    """Collect supported and registered connection state for onboarding."""

    service = SetupAssistantDiscoveryService(model_service=model_service)
    return await service.collect_connection_catalog_facts()


@router.post("/writing-samples/sent-email-metadata", response_model=SetupDiscoveryResponse)
async def collect_sent_email_metadata_setup_discovery(
    request: SentEmailMetadataDiscoveryRequest,
    model_service: ModelService = Depends(get_model_service),
) -> SetupDiscoveryResponse:
    """Collect opt-in sent-email metadata for writing-sample triage."""

    service = SetupAssistantDiscoveryService(model_service=model_service)
    return await service.collect_sent_email_metadata_facts(
        days_back=request.days_back,
        limit=request.limit,
    )

