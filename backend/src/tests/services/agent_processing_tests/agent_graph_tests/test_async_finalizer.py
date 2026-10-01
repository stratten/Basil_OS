"""Unit tests for P2 async finalizer (provisional envelope + off-path verification)."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api.services.agent_processing.lifecycle.execution_graph.async_finalizer import (
    FinalizeInputs,
    build_provisional_envelope,
    mark_verification_status,
    schedule_outcome_verification,
)


def _sample_inputs() -> FinalizeInputs:
    return FinalizeInputs(
        original_prompt="look up the file",
        agent_task_id="task-123",
        active_app="Finder",
        steps=[{"service": "file_service", "method": "find_file_for_llm", "success": True}],
        standardized_messages=["Here is the answer."],
        metrics={"steps_completed": 1, "steps_total": 1},
    )


@pytest.mark.asyncio
async def test_build_provisional_envelope_preserves_deterministic_partial_outcome():
    """Regression: the provisional envelope must show the deterministic finalizer's
    real outcome while verification is pending, never a manufactured success. A
    "pending" badge is honest; forcing success is not (this is the exact defect
    that let an unverified local-model result present as a false success)."""
    captured: dict = {}

    async def _fake_finalize(**kwargs):
        captured.update(kwargs)
        return {
            "success": False,
            "summary_text": "Partial result: The requested change could not be independently confirmed.\n\nHere is the answer.",
            "outcome": "partial",
            "outcome_reason": "The requested change could not be independently confirmed.",
            "errors": ["Unverified material effect"],
            "retry_hint": "Try again.",
            "result_payload": {
                "outcome": "partial",
                "outcome_reason": "The requested change could not be independently confirmed.",
                "files": [],
            },
        }

    with patch(
        "api.services.agent_processing.lifecycle.execution_graph.async_finalizer.finalize_agent_task_result",
        new=AsyncMock(side_effect=_fake_finalize),
    ):
        envelope = await build_provisional_envelope(_sample_inputs())

    assert envelope is not None
    assert envelope["result_payload"]["verification_status"] == "pending"
    assert captured["llm_model"] is None
    assert captured["is_local_model"] is True
    assert captured["success"] is None
    assert envelope["success"] is False
    assert envelope["outcome"] == "partial"
    assert envelope["summary_text"].startswith("Partial result:")
    assert envelope["outcome_reason"] == "The requested change could not be independently confirmed."
    assert envelope["errors"] == ["Unverified material effect"]
    assert envelope["retry_hint"] == "Try again."
    assert envelope["result_payload"]["outcome"] == "partial"


@pytest.mark.asyncio
async def test_build_provisional_envelope_without_visible_result_preserves_failure_eligibility():
    captured: dict = {}
    inputs = _sample_inputs()
    inputs.standardized_messages = []

    async def _fake_finalize(**kwargs):
        captured.update(kwargs)
        return {
            "success": False,
            "summary_text": "Workflow failed.",
            "result_payload": {"outcome": "failure", "files": []},
        }

    with patch(
        "api.services.agent_processing.lifecycle.execution_graph.async_finalizer.finalize_agent_task_result",
        new=AsyncMock(side_effect=_fake_finalize),
    ):
        envelope = await build_provisional_envelope(inputs)

    assert envelope is not None
    assert captured["success"] is None


@pytest.mark.asyncio
async def test_build_provisional_envelope_keeps_unverified_material_result_visually_pending():
    inputs = FinalizeInputs(
        original_prompt="Create a calendar draft.",
        agent_task_id=None,
        active_app="Outlook",
        steps=[{
            "service": "applescript_service",
            "method": "execute_applescript",
            "success": True,
            "needs_outcome_review": True,
            "outcome_verification_status": "unverified",
            "outcome_review": {
                "material_write": True,
                "verification_status": "unverified",
                "summary": "Outlook accepted the write but did not expose readback.",
                "evidence": {},
                "expected": {"title": "Planning"},
                "actual": {},
                "discrepancies": [],
            },
        }],
        standardized_messages=["Outlook accepted the draft and verification is pending."],
        metrics={"steps_completed": 1, "steps_total": 1},
    )

    envelope = await build_provisional_envelope(inputs)

    assert envelope is not None
    assert envelope["success"] is True
    assert envelope["outcome"] == "success"
    assert envelope["result_payload"]["outcome"] == "success"
    assert envelope["result_payload"]["verification_status"] == "pending"
    assert not envelope["summary_text"].startswith("Partial result:")
    assert "Outlook accepted the draft and verification is pending." in envelope["summary_text"]
    assert envelope["result_payload"]["outcome_review_issues"] == [
        "Step 1: Outlook accepted the write but did not expose readback."
    ]


@pytest.mark.asyncio
async def test_build_provisional_envelope_returns_none_on_failure():
    with patch(
        "api.services.agent_processing.lifecycle.execution_graph.async_finalizer.finalize_agent_task_result",
        new=AsyncMock(side_effect=RuntimeError("boom")),
    ):
        envelope = await build_provisional_envelope(_sample_inputs())
    assert envelope is None


def test_mark_verification_status_updates_payload():
    envelope = {"result_payload": {"outcome": "success"}}
    mark_verification_status(envelope, "resolved")
    assert envelope["result_payload"]["verification_status"] == "resolved"


@pytest.mark.asyncio
async def test_schedule_outcome_verification_persists_and_broadcasts_resolved():
    refined = {
        "success": True,
        "summary_text": "Verified answer.",
        "result_payload": {"outcome": "success", "files": [{"name": "doc.txt", "full_path": "/tmp/doc.txt"}]},
    }
    mock_finalize = AsyncMock(return_value=refined)
    mock_update = AsyncMock()
    mock_get_task = AsyncMock(return_value=SimpleNamespace(
        result_data={"agent_output": "keep me"},
        execution_timeline=[],
    ))
    mock_service = SimpleNamespace(
        _queries=SimpleNamespace(get_agent_task=mock_get_task),
        update_agent_task_status=mock_update,
    )
    mock_knowledge = SimpleNamespace(agent_task_service=mock_service)
    ws_manager = SimpleNamespace(broadcast=AsyncMock())

    with patch(
        "api.services.agent_processing.lifecycle.execution_graph.async_finalizer.finalize_agent_task_result",
        new=mock_finalize,
    ), patch(
        "api.dependencies.get_sqlite_knowledge_service",
        return_value=mock_knowledge,
    ):
        schedule_outcome_verification(
            inputs=_sample_inputs(),
            llm_model=MagicMock(),
            ws_manager=ws_manager,
            agent_task_id="task-123",
            root_task_id="root-1",
            previous_task_id=None,
            cancel_event=None,
        )
        await asyncio.sleep(0.05)

    mock_finalize.assert_awaited_once()
    assert mock_finalize.await_args.kwargs["llm_model"] is not None
    assert mock_finalize.await_args.kwargs["is_local_model"] is False

    mock_update.assert_awaited_once()
    update_kwargs = mock_update.await_args.kwargs
    assert update_kwargs["agent_task_id"] == "task-123"
    assert update_kwargs["result_data"]["finalizer_result"]["result_payload"]["verification_status"] == "resolved"
    assert update_kwargs["result_data"]["agent_output"] == "keep me"

    ws_manager.broadcast.assert_awaited_once()
    message = ws_manager.broadcast.await_args.args[0]
    assert message["event_type"] == "agent_task_outcome_update"
    assert message["result_payload"]["verification_status"] == "resolved"
    assert message["agent_task_id"] == "task-123"
    assert message["root_task_id"] == "root-1"


@pytest.mark.asyncio
async def test_refined_outcome_replaces_provisional_timeline_summary():
    refined = {
        "success": True,
        "summary_text": "Verified answer.",
        "result_payload": {
            "outcome": "success",
            "files": [],
            "steps": {"completed": 1, "total": 1},
        },
    }
    mock_finalize = AsyncMock(return_value=refined)
    mock_update = AsyncMock()
    mock_update_timeline = AsyncMock()
    provisional_summary = {
        "id": "final_summary",
        "type": "step",
        "body": "Partial result: I was only able to complete part of the request.",
        "metadata": {
            "source": "finalizer",
            "outcome": "partial",
            "verification_status": "pending",
        },
    }
    mock_get_task = AsyncMock(return_value=SimpleNamespace(
        result_data={"agent_output": "keep me"},
        execution_timeline=[
            {"id": "tool-1", "type": "tool_complete", "body": "Found answer."},
            provisional_summary,
        ],
    ))
    mock_service = SimpleNamespace(
        _queries=SimpleNamespace(get_agent_task=mock_get_task),
        _mutations=SimpleNamespace(update_execution_timeline=mock_update_timeline),
        update_agent_task_status=mock_update,
    )
    mock_knowledge = SimpleNamespace(agent_task_service=mock_service)

    with patch(
        "api.services.agent_processing.lifecycle.execution_graph.async_finalizer.finalize_agent_task_result",
        new=mock_finalize,
    ), patch(
        "api.dependencies.get_sqlite_knowledge_service",
        return_value=mock_knowledge,
    ):
        schedule_outcome_verification(
            inputs=_sample_inputs(),
            llm_model=MagicMock(),
            ws_manager=SimpleNamespace(broadcast=AsyncMock()),
            agent_task_id="task-123",
            root_task_id="root-1",
            previous_task_id=None,
            cancel_event=None,
        )
        await asyncio.sleep(0.05)

    mock_update_timeline.assert_awaited_once()
    timeline = mock_update_timeline.await_args.kwargs["timeline"]
    assert timeline[0] == {"id": "tool-1", "type": "tool_complete", "body": "Found answer."}
    assert timeline[1]["body"] == "Verified answer."
    assert timeline[1]["metadata"]["outcome"] == "success"
    assert timeline[1]["metadata"]["verification_status"] == "resolved"


@pytest.mark.asyncio
async def test_schedule_outcome_verification_skips_when_canceled():
    cancel_event = asyncio.Event()
    cancel_event.set()
    mock_finalize = AsyncMock()
    ws_manager = SimpleNamespace(broadcast=AsyncMock())

    with patch(
        "api.services.agent_processing.lifecycle.execution_graph.async_finalizer.finalize_agent_task_result",
        new=mock_finalize,
    ):
        schedule_outcome_verification(
            inputs=_sample_inputs(),
            llm_model=MagicMock(),
            ws_manager=ws_manager,
            agent_task_id="task-123",
            root_task_id=None,
            previous_task_id=None,
            cancel_event=cancel_event,
        )
        await asyncio.sleep(0.05)

    mock_finalize.assert_not_awaited()
    ws_manager.broadcast.assert_not_awaited()
