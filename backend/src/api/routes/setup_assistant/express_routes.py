"""Express setup: a hardware-aware plan, an apply step and a receipt."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from api.core.services.model_service import ModelService, get_model_service
from api.services.setup_assistant.express.applier import ExpressApplier
from api.services.setup_assistant.express.models import (
    ComfortLevel,
    ExpressApplyRequest,
    ExpressApplyResult,
    ExpressPlan,
    SetupReceipt,
)
from api.services.setup_assistant.express.planner import ExpressEnvironment, ExpressPlanner, default_environment
from api.services.setup_assistant.express.receipt import build_receipt

router = APIRouter(prefix="/express", tags=["Setup Assistant"])


def _environment_for(model_service: ModelService) -> ExpressEnvironment:
    """The seam tests replace to feed the routes a fake Mac."""
    return default_environment(model_service)


@router.get("/plan", response_model=ExpressPlan)
async def get_express_plan(
    comfort: ComfortLevel = Query(...),
    model_service: ModelService = Depends(get_model_service),
) -> ExpressPlan:
    """What this comfort level would do on this Mac, with disk and network checks. Nothing is changed."""
    return await ExpressPlanner(_environment_for(model_service)).build_plan(comfort)


@router.post("/apply", response_model=ExpressApplyResult)
async def apply_express_plan(
    body: ExpressApplyRequest,
    http_request: Request,
    model_service: ModelService = Depends(get_model_service),
) -> ExpressApplyResult:
    """Start the selected downloads and turn on the selected settings. The plan is rebuilt here, so only item ids are trusted."""
    manager = getattr(http_request.app.state, "download_manager", None)
    if manager is None:
        raise HTTPException(status_code=503, detail="Downloads are not ready yet. Try again in a moment.")
    applier = ExpressApplier(ExpressPlanner(_environment_for(model_service)), manager)
    try:
        return await applier.apply(body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/receipt", response_model=SetupReceipt)
async def get_express_receipt(model_service: ModelService = Depends(get_model_service)) -> SetupReceipt:
    """What is on right now, read from the real settings and installed models."""
    environment = _environment_for(model_service)
    return build_receipt(ExpressPlanner(environment).download_specs(), environment.load_preferences())
