"""execute_scheduled_run honors the chain plan: a skipped run submits nothing, and a continued run submits on the chain's root."""

from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from api.services.scheduled_agent_tasks.scheduled_agent_task_service_components import (
    scheduled_chain_runtime as chain_runtime,
    scheduled_run_execution as sre,
)


def _repo(**schedule_overrides):
    schedule = {
        "id": "schedule-1",
        "is_active": True,
        "agent_task_text": "Check my inbox",
        "title": "Check email",
        "reference_paths": [],
        "model_id": None,
        "connection_ids": [],
    }
    schedule.update(schedule_overrides)
    return SimpleNamespace(
        get_scheduled_run=AsyncMock(return_value={"status": "scheduled"}),
        get_scheduled_agent_task=AsyncMock(return_value=schedule),
        update_scheduled_run=AsyncMock(),
        claim_scheduled_run=AsyncMock(return_value=True),
    )


@pytest.mark.asyncio
async def test_a_skipped_run_submits_nothing_and_never_holds_the_sleep_guard(monkeypatch):
    submission_service = SimpleNamespace(process_agent_task_direct=AsyncMock(), broadcast=AsyncMock())
    monkeypatch.setattr("api.main.app", SimpleNamespace(state=SimpleNamespace(agent_task_submission_service=submission_service)))
    sleep_guard = AsyncMock()
    monkeypatch.setattr(sre, "_prevent_idle_system_sleep_for_scheduled_run", lambda **_kwargs: sleep_guard() or nullcontext())
    monkeypatch.setattr(chain_runtime, "plan_chain_run", AsyncMock(return_value=chain_runtime.ChainPlan(action=chain_runtime.ACTION_SKIP, skip_reason="Busy")))
    skip_finalizer = AsyncMock()
    monkeypatch.setattr(sre.scheduled_run_lifecycle, "finalize_skipped_run", skip_finalizer)
    finalize = AsyncMock()
    monkeypatch.setattr(sre.scheduled_run_lifecycle, "finalize_run_after_execution", finalize)

    result = await sre.execute_scheduled_run(_repo(), SimpleNamespace(), "schedule-1", "run-1")

    assert result == {"success": False, "skipped": True, "error": "Busy"}
    skip_finalizer.assert_awaited_once()
    assert skip_finalizer.await_args.kwargs == {"scheduled_agent_task_id": "schedule-1", "run_id": "run-1", "reason": "Busy"}
    submission_service.process_agent_task_direct.assert_not_awaited()
    sleep_guard.assert_not_called()
    finalize.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_continued_run_is_submitted_on_the_chain_root_with_the_visible_prompt_unchanged(monkeypatch):
    submission_service = SimpleNamespace(
        process_agent_task_direct=AsyncMock(return_value={"success": False, "error": "stop here"}),
        broadcast=AsyncMock(),
    )
    monkeypatch.setattr("api.main.app", SimpleNamespace(state=SimpleNamespace(agent_task_submission_service=submission_service)))
    monkeypatch.setattr(sre, "_prevent_idle_system_sleep_for_scheduled_run", lambda **_kwargs: nullcontext())
    plan = chain_runtime.ChainPlan(
        action=chain_runtime.ACTION_START,
        handoff_block="PREVIOUS SCHEDULED CONVERSATION (read-only background):\nlast result",
        notice="Started a new conversation because the previous one reached its limit of 3 runs.",
    )
    monkeypatch.setattr(chain_runtime, "plan_chain_run", AsyncMock(return_value=plan))
    monkeypatch.setattr(sre.scheduled_run_lifecycle, "finalize_run_after_execution", AsyncMock())
    repo = _repo()

    await sre.execute_scheduled_run(repo, SimpleNamespace(), "schedule-1", "run-1")

    kwargs = submission_service.process_agent_task_direct.await_args.kwargs
    assert kwargs["agent_task"] == "Check my inbox\n\nPREVIOUS SCHEDULED CONVERSATION (read-only background):\nlast result"
    assert kwargs["display_prompt_markdown"] == "Check my inbox"
    assert "root_task_id" not in kwargs
    notice_calls = [call.kwargs.get("notice") for call in repo.update_scheduled_run.await_args_list if call.kwargs.get("notice")]
    assert notice_calls == ["Started a new conversation because the previous one reached its limit of 3 runs."]


@pytest.mark.asyncio
async def test_a_continue_plan_passes_the_root_task_id(monkeypatch):
    submission_service = SimpleNamespace(
        process_agent_task_direct=AsyncMock(return_value={"success": False, "error": "stop here"}),
        broadcast=AsyncMock(),
    )
    monkeypatch.setattr("api.main.app", SimpleNamespace(state=SimpleNamespace(agent_task_submission_service=submission_service)))
    monkeypatch.setattr(sre, "_prevent_idle_system_sleep_for_scheduled_run", lambda **_kwargs: nullcontext())
    monkeypatch.setattr(
        chain_runtime,
        "plan_chain_run",
        AsyncMock(return_value=chain_runtime.ChainPlan(action=chain_runtime.ACTION_CONTINUE, root_task_id="root-9")),
    )
    monkeypatch.setattr(sre.scheduled_run_lifecycle, "finalize_run_after_execution", AsyncMock())

    await sre.execute_scheduled_run(_repo(), SimpleNamespace(), "schedule-1", "run-1")

    kwargs = submission_service.process_agent_task_direct.await_args.kwargs
    assert kwargs["root_task_id"] == "root-9"
    assert kwargs["agent_task"] == "Check my inbox"
    assert kwargs["origin_type"] == "scheduled_task" and kwargs["origin_id"] == "schedule-1"
