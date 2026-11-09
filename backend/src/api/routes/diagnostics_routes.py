"""Report a problem: builds a redacted diagnostics bundle on this Mac and a pre-filled GitHub issue link."""

from __future__ import annotations

import asyncio
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ..core.logging.api_logger import api_logger
from ..core.services.model_service import ModelService
from ..dependencies import get_model_service
from ..services.diagnostics.log_redaction import redacted_log_excerpt
from ..services.diagnostics.problem_report import issue_url, write_report_bundle
from ..services.diagnostics.problem_report_collector import collect_problem_report_facts

router = APIRouter(prefix="/diagnostics", tags=["Diagnostics"])


class ProblemReportRequest(BaseModel):
    """What the app knows when the user opens Report a problem. `detail` is a native return code or similar, never conversation text."""

    source: str = Field(default="app", max_length=80)
    detail: Optional[str] = Field(default=None, max_length=1000)
    app_version: Optional[str] = Field(default=None, max_length=80)
    macos_version: Optional[str] = Field(default=None, max_length=120)


class ProblemReportResponse(BaseModel):
    bundle_path: str
    issue_url: str
    log_excerpt_available: bool


def reports_directory() -> Path:
    return Path.home() / ".basil" / "diagnostics" / "reports"


def backend_log_path() -> Optional[Path]:
    """The bundled app's backend log, or None for a development run that has no such file."""
    app_support = os.environ.get("APP_SUPPORT_DIR")
    if not app_support:
        return None
    path = Path(app_support) / "logs" / "backend.log"
    return path if path.is_file() else None


def _build_bundle(request: ProblemReportRequest, model_service: ModelService) -> ProblemReportResponse:
    facts = collect_problem_report_facts(
        model_service,
        source=request.source,
        detail=request.detail,
        app_version=request.app_version,
        macos_version=request.macos_version,
    )
    log_path = backend_log_path()
    if log_path is None:
        facts.collection_notes.append("No backend log file was available.")
        excerpt = "No backend log file was available.\n"
    else:
        excerpt = redacted_log_excerpt(log_path)
    bundle = write_report_bundle(reports_directory(), facts, excerpt, datetime.now())
    return ProblemReportResponse(
        bundle_path=str(bundle),
        issue_url=issue_url(facts, bundle.name),
        log_excerpt_available=log_path is not None,
    )


@router.post("/problem-report", response_model=ProblemReportResponse)
async def create_problem_report(
    request: ProblemReportRequest,
    model_service: ModelService = Depends(get_model_service),
) -> ProblemReportResponse:
    """Write the bundle to `~/.basil/diagnostics/reports/` and return its path and the issue link. Nothing is sent anywhere."""
    response = await asyncio.to_thread(_build_bundle, request, model_service)
    api_logger.info("Problem report bundle written (source=%s)", request.source)
    return response
