"""Origin provenance for scheduled agent task runs."""

from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from api.services.scheduled_agent_tasks.scheduled_agent_task_service_components import (
    scheduled_run_execution as sre,
)


@pytest.mark.asyncio
async def test_execute_scheduled_run_passes_scheduled_task_origin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    submission_service = SimpleNamespace(
        process_agent_task_direct=AsyncMock(return_value={"success": False, "message": "fail fast"}),
        broadcast=AsyncMock(),
    )
    fake_app = SimpleNamespace(state=SimpleNamespace(agent_task_submission_service=submission_service))
    monkeypatch.setattr("api.main.app", fake_app)
    monkeypatch.setattr(
        sre,
        "_prevent_idle_system_sleep_for_scheduled_run",
        lambda **_kwargs: nullcontext(),
    )
    monkeypatch.setattr(
        sre.scheduled_run_lifecycle,
        "finalize_run_after_execution",
        AsyncMock(return_value={"status": "failed", "next_run_at": None}),
    )

    repo = SimpleNamespace(
        get_scheduled_run=AsyncMock(return_value={"status": "scheduled"}),
        get_scheduled_agent_task=AsyncMock(
            return_value={
                "is_active": True,
                "agent_task_text": "Do the thing",
                "title": "Daily check",
                "reference_paths": [],
            }
        ),
        update_scheduled_run=AsyncMock(),
    )
    db = SimpleNamespace()

    await sre.execute_scheduled_run(repo, db, "schedule-1", "run-1")

    kwargs = submission_service.process_agent_task_direct.await_args.kwargs
    assert kwargs["origin_type"] == "scheduled_task"
    assert kwargs["origin_id"] == "schedule-1"
