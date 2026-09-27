"""Progress-route coverage for Zettel narrative run policy metadata."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from api.routes.settings_routes.zettel_routes import get_narrative_progress


@pytest.mark.asyncio
async def test_progress_route_exposes_parallel_run_policy():
    progress = SimpleNamespace(
        active=True,
        total=10,
        processed=2,
        finalized=2,
        still_open=0,
        failed=0,
        started_at=None,
        last_error=None,
        cancel_requested=False,
        analysis_concurrency=8,
        processing_strategy="api_parallel",
    )
    scheduler = SimpleNamespace(get_progress=lambda: progress)

    with patch(
        "api.services.zettel.narrative_scheduler.get_zettel_narrative_scheduler",
        return_value=scheduler,
    ):
        response = await get_narrative_progress()

    assert response.remaining == 8
    assert response.analysis_concurrency == 8
    assert response.processing_strategy == "api_parallel"
