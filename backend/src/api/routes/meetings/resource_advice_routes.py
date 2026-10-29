"""Resource advice routes: current advice, the client's thermal report, and dismissal."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict

from api.services.meeting_resources.advisor import ResourceAdvisor
from api.services.meeting_resources.models import ResourceAdviceState
from api.services.meeting_resources.service import get_resource_advisor

router = APIRouter()


class ThermalReportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    thermal_state: Literal["nominal", "fair", "serious", "critical"]


def get_advisor() -> ResourceAdvisor:
    advisor = get_resource_advisor()
    if advisor is None:
        raise HTTPException(status_code=503, detail="The resource advisor is not available.")
    return advisor


@router.get("/resource-advice", response_model=ResourceAdviceState)
async def read_resource_advice(advisor: ResourceAdvisor = Depends(get_advisor)) -> ResourceAdviceState:
    return advisor.state()


@router.put("/resource-advice/client-state", response_model=ResourceAdviceState)
async def report_client_state(request: ThermalReportRequest, advisor: ResourceAdvisor = Depends(get_advisor)) -> ResourceAdviceState:
    advisor.report_thermal_state(request.thermal_state)
    return advisor.state()


@router.post("/resource-advice/{advice_id}/dismiss", response_model=ResourceAdviceState)
async def dismiss_resource_advice(advice_id: str, advisor: ResourceAdvisor = Depends(get_advisor)) -> ResourceAdviceState:
    if not advisor.dismiss(advice_id):
        raise HTTPException(status_code=404, detail="That advice is not showing.")
    await advisor.publish_if_changed()
    return advisor.state()
