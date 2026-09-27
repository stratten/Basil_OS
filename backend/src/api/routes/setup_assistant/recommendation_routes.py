"""Recommendation contract endpoints for the setup assistant."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from api.routes.setup_assistant.models import (
    SetupAgentContractResponse,
    SetupAgentValidationRequest,
    SetupAgentValidationResponse,
)
from api.services.setup_assistant.recommendation_service import (
    SetupAssistantRecommendationService,
)


router = APIRouter(tags=["Setup Assistant"])


@router.get("/agent-contract", response_model=SetupAgentContractResponse)
async def get_setup_agent_contract() -> SetupAgentContractResponse:
    """Return the setup agent prompt, output schema, and validation rules."""

    return SetupAssistantRecommendationService().build_setup_agent_contract()


@router.post("/validate-agent-output", response_model=SetupAgentValidationResponse)
async def validate_setup_agent_output(
    request: SetupAgentValidationRequest,
) -> SetupAgentValidationResponse:
    """Validate structured setup agent output before the UI can present it."""

    try:
        return SetupAssistantRecommendationService().validate_setup_agent_output(
            request.output,
            discovery_facts=request.discovery_facts,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/recommendations/synthesize")
async def synthesize_setup_recommendations() -> None:
    """Reject obsolete deterministic setup recommendation synthesis."""

    raise HTTPException(
        status_code=410,
        detail="Setup recommendations must be produced by /setup-assistant/agent/respond.",
    )

