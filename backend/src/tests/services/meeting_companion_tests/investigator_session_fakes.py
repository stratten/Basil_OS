"""A fake investigator for session and route tests: scripted results, an optional release gate and cancellation awareness."""

import asyncio
from typing import Any, List, Optional

from api.services.meeting_companion.investigator.models import InvestigationRequest, InvestigationResult
from api.services.meeting_companion.models import FileCitation


def cited_result(request: InvestigationRequest, status: str = "completed") -> InvestigationResult:
    if status != "completed":
        return InvestigationResult(investigation_id=request.investigation_id, status=status, detail="scripted")  # type: ignore[arg-type]
    return InvestigationResult(
        investigation_id=request.investigation_id,
        status="completed",
        answer="The renewal term is twelve months.",
        confidence=0.9,
        citations=[FileCitation(path="proj/contract.md", line_start=4, line_end=6, excerpt="Renewal term: twelve months.")],
        tool_calls=2,
        evidence_count=3,
        duration_ms=1200,
    )


class FakeInvestigator:
    def __init__(self, status: str = "completed") -> None:
        self.status = status
        self.requests: List[InvestigationRequest] = []
        self.release: Optional["asyncio.Event"] = None
        self.canceled: List[str] = []
        self.concurrency_limit = 1
        self.proposals: List[Any] = []

    async def investigate(self, request: InvestigationRequest, *, context: Any, cancel_event: "asyncio.Event", model_provider: Any) -> InvestigationResult:
        self.requests.append(request)
        if self.release is not None:
            waiter = asyncio.ensure_future(self.release.wait())
            canceler = asyncio.ensure_future(cancel_event.wait())
            try:
                await asyncio.wait({waiter, canceler}, return_when=asyncio.FIRST_COMPLETED)
            finally:
                waiter.cancel()
                canceler.cancel()
                await asyncio.gather(waiter, canceler, return_exceptions=True)
            if cancel_event.is_set():
                self.canceled.append(request.investigation_id)
                return InvestigationResult(investigation_id=request.investigation_id, status="canceled")
        result = cited_result(request, self.status)
        result.proposals = list(self.proposals)
        return result
