"""Tests for agent-task process route dispatch decisions."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from api.routes.agent_tasks import core_routes
from api.routes.agent_tasks.core_routes import process_agent_task
from api.routes.agent_tasks.models import AgentTaskProcessingResponse, AgentTaskRequest
from api.services.agent_processing.lifecycle.submission import AgentTaskSubmissionService
from api.services.agent_processing.lifecycle.submission.agent_task_processing.authorized_provider_delegation_submission_service import (
    AuthorizedProviderDelegationSubmissionService,
)


class _FakeKnowledgeServiceForRouting:
    def __init__(self):
        self.agent_task_service = SimpleNamespace(
            get_agent_task=AsyncMock(return_value=None),
            get_agent_task_chain=AsyncMock(return_value=[]),
        )


class _FakeAgentTaskService:
    def __init__(self):
        self.direct_calls = []

    async def determine_operation_type(self, agent_task, clarification_agent_task=None, root_task_id=None, model_id=None):
        assert agent_task == "Create a report from my recent activity"
        assert clarification_agent_task is None
        assert root_task_id is None
        return "multi_step_workflow"

    async def process_agent_task_direct(self, **kwargs):
        self.direct_calls.append(kwargs)
        return {
            "success": True,
            "operation": "multi_step_workflow",
            "confidence": 1.0,
            "reasoning": "Direct event-driven processing",
            "message": "Task received and being processed...",
            "processing_time": 0.0,
            "agent_task_id": "agent-task-123",
        }

@pytest.mark.asyncio
async def test_process_agent_task_routes_multi_step_workflow_to_direct_processing():
    """Current first-time agent tasks hard-route to direct event-driven processing."""

    service = _FakeAgentTaskService()
    payload = AgentTaskRequest(
        agent_task="Create a report from my recent activity",
        agent_task_id="agent-task-123",
        reference_paths=["/tmp/reference.txt"],
    )

    response = await process_agent_task(payload=payload, service=service, knowledge_service=_FakeKnowledgeServiceForRouting())

    assert isinstance(response, AgentTaskProcessingResponse)
    assert response.success is True
    assert response.operation == "multi_step_workflow"
    assert response.agent_task_id == "agent-task-123"
    assert len(service.direct_calls) == 1
    assert service.direct_calls[0]["agent_task"] == payload.agent_task
    assert service.direct_calls[0]["agent_task_id"] == "agent-task-123"
    assert service.direct_calls[0]["reference_paths"] == ["/tmp/reference.txt"]


def test_process_request_rejects_manual_provider_target_fields() -> None:
    for field_name in (
        "provider_profile_id",
        "workspace_grant_id",
        "provider_workspace_path",
    ):
        with pytest.raises(ValidationError):
            AgentTaskRequest(
                agent_task="Run a provider",
                **{field_name: "untrusted-model-value"},
            )


@pytest.mark.asyncio
async def test_authorized_provider_submission_preserves_child_chain_context() -> None:
    submission_service = SimpleNamespace(
        reserve_delegated_agent_task=AsyncMock(
            return_value={"success": True, "agent_task_id": "child-123", "status": "reserved"}
        )
    )
    service = AuthorizedProviderDelegationSubmissionService(submission_service)
    context = {
        "provider_target": {
            "provider_profile_id": "profile-123",
            "workspace_grant_id": "grant-123",
            "candidate_workspace_path": "/private/fixture",
        },
        "provider_delegation": {
            "delegation_id": "delegation-123",
            "authorization_id": "authorization-123",
            "reference_paths": ["/private/fixture/attached.py"],
        },
    }

    result = await service.submit_authorized_provider_delegation(
        agent_task="Run the authorized provider",
        child_agent_task_id="child-123",
        root_task_id="root-123",
        parent_agent_task_id="parent-123",
        chain_sequence_number=2,
        delegation_context=context,
    )

    assert result["status"] == "reserved"
    assert submission_service.reserve_delegated_agent_task.await_args.kwargs == {
        "agent_task": "Run the authorized provider",
        "child_agent_task_id": "child-123",
        "root_task_id": "root-123",
        "parent_agent_task_id": "parent-123",
        "chain_sequence_number": 2,
        "session_type": "provider_delegation",
        "accumulated_artifacts": context,
    }


@pytest.mark.asyncio
async def test_first_time_tasks_never_pay_the_fast_lane_gate_cost():
    """First-time tasks (no root_task_id) route to multi_step_workflow without
    ever calling the model -- there is no conversation context yet to gate on."""
    service = object.__new__(AgentTaskSubmissionService)

    assert await service.determine_operation_type("Suggest a response to this email") == "multi_step_workflow"
    assert await service.determine_operation_type("Summarize this screen") == "multi_step_workflow"


@pytest.mark.asyncio
async def test_follow_up_routing_defers_entirely_to_the_intent_gate(monkeypatch):
    """Follow-ups (root_task_id present) are routed purely by
    evaluate_fast_lane_intent's decision -- no keyword matching."""
    import api.services.agent_processing.lifecycle.submission.agent_task_submission_service as submission_module
    from api.services.agent_processing.lifecycle.submission.fast_lane_intent_gate import FastLaneDecision

    service = object.__new__(AgentTaskSubmissionService)
    service._build_chain_context = AsyncMock(return_value=None)
    monkeypatch.setattr(
        submission_module,
        "resolve_fast_lane_reasoning_model",
        AsyncMock(return_value=object()),
    )

    monkeypatch.setattr(
        submission_module, "evaluate_fast_lane_intent",
        AsyncMock(return_value=FastLaneDecision(can_answer_from_context=True, confidence=0.9, reason="x")),
    )
    assert await service.determine_operation_type("anything at all", root_task_id="root-123") == "discussion"

    monkeypatch.setattr(
        submission_module, "evaluate_fast_lane_intent",
        AsyncMock(return_value=FastLaneDecision(can_answer_from_context=False, confidence=0.9, reason="x")),
    )
    assert await service.determine_operation_type("anything at all", root_task_id="root-123") == "multi_step_workflow"


class _FakeDiscussionService:
    """Fake service that routes to the fast lane and records when the
    dispatched background work actually ran, to prove the route returns
    before that work completes (fire-and-forget), not after."""

    def __init__(self):
        self.discussion_calls = []
        self.discussion_started = asyncio.Event()
        self.discussion_finished = asyncio.Event()

    async def determine_operation_type(self, agent_task, clarification_agent_task=None, root_task_id=None, model_id=None):
        return "discussion"

    async def handle_discussion_followup(self, **kwargs):
        self.discussion_started.set()
        self.discussion_calls.append(kwargs)
        await asyncio.sleep(0.05)
        self.discussion_finished.set()
        return {"success": True, "operation": "discussion", "agent_task_id": kwargs.get("agent_task_id")}


@pytest.mark.asyncio
async def test_discussion_followup_returns_immediately_before_background_work_completes():
    """The fast lane must return its HTTP response before
    handle_discussion_followup finishes -- proving the dispatch is genuinely
    fire-and-forget, not just synchronously awaited under a different name."""
    service = _FakeDiscussionService()
    payload = AgentTaskRequest(
        agent_task="so can I use it right now?",
        root_task_id="root-123",
        previous_task_id="prev-456",
    )

    response = await process_agent_task(payload=payload, service=service, knowledge_service=_FakeKnowledgeServiceForRouting())

    assert isinstance(response, AgentTaskProcessingResponse)
    assert response.success is True
    assert response.operation == "discussion"
    assert response.agent_task_id is not None
    # The background call may or may not have started yet depending on
    # scheduling, but it must not have finished -- the route did not await it.
    assert not service.discussion_finished.is_set()

    await service.discussion_started.wait()
    await service.discussion_finished.wait()
    assert len(service.discussion_calls) == 1
    assert service.discussion_calls[0]["agent_task_id"] == response.agent_task_id
    assert service.discussion_calls[0]["root_task_id"] == "root-123"
    assert service.discussion_calls[0]["previous_task_id"] == "prev-456"


@pytest.mark.asyncio
async def test_discussion_followup_generates_agent_task_id_when_missing():
    """When the client doesn't supply agent_task_id, the route must generate
    one and use that same id both in the immediate response and in the
    dispatched call, so later WebSocket events correlate with it."""
    service = _FakeDiscussionService()
    payload = AgentTaskRequest(
        agent_task="what did you mean by that?",
        root_task_id="root-123",
    )

    response = await process_agent_task(payload=payload, service=service, knowledge_service=_FakeKnowledgeServiceForRouting())
    await service.discussion_started.wait()
    await service.discussion_finished.wait()

    assert response.agent_task_id is not None
    assert service.discussion_calls[0]["agent_task_id"] == response.agent_task_id


@pytest.mark.asyncio
async def test_discussion_followup_task_is_retained_until_completion():
    """Regression: asyncio.ensure_future only holds a weak reference, so the
    dispatched task must be retained in a module-level set (mirroring
    async_finalizer.py's _PENDING_VERIFICATIONS) or it risks disappearing
    mid-execution under GC pressure."""
    service = _FakeDiscussionService()
    payload = AgentTaskRequest(
        agent_task="so can I use it right now?",
        root_task_id="root-123",
    )

    baseline = len(core_routes._PENDING_FAST_LANE_TASKS)
    await process_agent_task(payload=payload, service=service, knowledge_service=_FakeKnowledgeServiceForRouting())

    assert len(core_routes._PENDING_FAST_LANE_TASKS) == baseline + 1
    await service.discussion_finished.wait()
    # The done-callback discards the task once it completes.
    await asyncio.sleep(0)
    assert len(core_routes._PENDING_FAST_LANE_TASKS) == baseline


class _FakeFeedbackKnowledgeService:
    def __init__(self, task):
        self.agent_task_service = SimpleNamespace(
            get_agent_task=AsyncMock(return_value=task),
            get_agent_task_chain=AsyncMock(return_value=[task]),
        )


class _FakeDirectService:
    def __init__(self):
        self.operation_type_calls = []
        self.direct_calls = []

    async def determine_operation_type(self, *args, **kwargs):
        self.operation_type_calls.append((args, kwargs))
        return "discussion"

    async def process_agent_task_direct(self, **kwargs):
        self.direct_calls.append(kwargs)
        return {
            "success": True,
            "operation": "multi_step_workflow",
            "confidence": 1.0,
            "reasoning": "Direct event-driven processing",
            "message": "Task received and being processed...",
            "processing_time": 0.0,
            "agent_task_id": "feedback-task-1",
        }


@pytest.mark.asyncio
async def test_local_preview_feedback_forces_multi_step_workflow(tmp_path):
    artifact_path = tmp_path / "report.html"
    artifact_path.write_text("<html></html>", encoding="utf-8")
    task = SimpleNamespace(
        id="root-123",
        root_task_id=None,
        status="completed",
        result_data={
            "files": [{
                "artifact_id": "artifact-1",
                "name": "report.html",
                "path": str(artifact_path),
                "kind": "file",
                "operation": "write",
            }]
        },
        execution_timeline=None,
        accumulated_artifacts=None,
    )
    service = _FakeDirectService()
    payload = AgentTaskRequest(
        agent_task="Fix the header spacing.",
        root_task_id="root-123",
        previous_task_id="root-123",
        local_preview_feedback={
            "source_artifact_id": "artifact-1",
            "mode": "static",
            "preview_url": "basil-preview-file://preview/report.html",
            "location_status": "fallback",
            "console_evidence": "",
        },
    )

    response = await process_agent_task(
        payload=payload,
        service=service,
        knowledge_service=_FakeFeedbackKnowledgeService(task),
    )

    assert response.operation == "multi_step_workflow"
    assert service.operation_type_calls == []
    assert len(service.direct_calls) == 1
    feedback = service.direct_calls[0]["local_preview_feedback"]
    assert feedback["kind"] == "local_web_preview_feedback"
    assert feedback["source_artifact_id"] == "artifact-1"
    assert feedback["preview_mode"] == "static"
    assert feedback["network_evidence"] == {"policy": "not_captured", "status": "not_captured"}


@pytest.mark.asyncio
async def test_local_preview_feedback_does_not_forward_a_rejected_screenshot_path(tmp_path):
    artifact_path = tmp_path / "report.html"
    artifact_path.write_text("<html></html>", encoding="utf-8")
    task = SimpleNamespace(
        id="root-123",
        root_task_id=None,
        status="completed",
        result_data={
            "files": [{
                "artifact_id": "artifact-1",
                "name": "report.html",
                "path": str(artifact_path),
                "kind": "file",
                "operation": "write",
            }]
        },
        execution_timeline=None,
        accumulated_artifacts=None,
    )
    service = _FakeDirectService()
    rejected_screenshot_path = str(tmp_path / "untrusted.png")
    payload = AgentTaskRequest(
        agent_task="Fix the header spacing.",
        root_task_id="root-123",
        previous_task_id="root-123",
        reference_paths=[rejected_screenshot_path],
        local_preview_feedback={
            "source_artifact_id": "artifact-1",
            "mode": "static",
            "preview_url": "basil-preview-file://preview/report.html",
            "location_status": "fallback",
            "screenshot_path": rejected_screenshot_path,
        },
    )

    await process_agent_task(
        payload=payload,
        service=service,
        knowledge_service=_FakeFeedbackKnowledgeService(task),
    )

    assert service.direct_calls[0]["reference_paths"] is None
    assert service.direct_calls[0]["local_preview_feedback"]["screenshot"]["status"] == "unavailable"


@pytest.mark.asyncio
async def test_local_preview_feedback_forwards_only_a_validated_screenshot_path(tmp_path, monkeypatch):
    artifact_path = tmp_path / "report.html"
    artifact_path.write_text("<html></html>", encoding="utf-8")
    screenshot_root = tmp_path / "data" / "local_web_preview" / "screenshots"
    screenshot_root.mkdir(parents=True)
    screenshot_path = screenshot_root / "snapshot.png"
    screenshot_path.write_bytes(b"png")
    monkeypatch.setenv("BASIL_DATA_DIR", str(tmp_path / "data"))
    task = SimpleNamespace(
        id="root-123",
        root_task_id=None,
        status="completed",
        result_data={
            "files": [{
                "artifact_id": "artifact-1",
                "name": "report.html",
                "path": str(artifact_path),
                "kind": "file",
                "operation": "write",
            }]
        },
        execution_timeline=None,
        accumulated_artifacts=None,
    )
    service = _FakeDirectService()
    payload = AgentTaskRequest(
        agent_task="Fix the header spacing.",
        root_task_id="root-123",
        previous_task_id="root-123",
        local_preview_feedback={
            "source_artifact_id": "artifact-1",
            "mode": "static",
            "preview_url": "basil-preview-file://preview/report.html",
            "location_status": "fallback",
            "screenshot_path": str(screenshot_path),
        },
    )

    await process_agent_task(
        payload=payload,
        service=service,
        knowledge_service=_FakeFeedbackKnowledgeService(task),
    )

    assert service.direct_calls[0]["reference_paths"] == [str(screenshot_path)]
    assert service.direct_calls[0]["local_preview_feedback"]["screenshot"] == {
        "status": "available",
        "path": str(screenshot_path.resolve()),
    }


@pytest.mark.asyncio
async def test_local_preview_feedback_rejects_a_basil_preview_file_url_outside_the_authorized_artifact(tmp_path):
    # The native preview window serves static documents through a
    # `basil-preview-file://` WKURLSchemeHandler scoped to the artifact's own
    # directory (see AgentTaskLocalWebPreviewWindow.swift's
    # LocalPreviewFileSchemeHandler). That directory scope alone would let
    # this field name any sibling file the handler is willing to serve, so
    # the requested filename must additionally match the artifact this
    # feedback was authorized against.
    artifact_path = tmp_path / "report.html"
    artifact_path.write_text("<html></html>", encoding="utf-8")
    task = SimpleNamespace(
        id="root-123",
        root_task_id=None,
        status="completed",
        result_data={
            "files": [{
                "artifact_id": "artifact-1",
                "name": "report.html",
                "path": str(artifact_path),
                "kind": "file",
                "operation": "write",
            }]
        },
        execution_timeline=None,
        accumulated_artifacts=None,
    )
    service = _FakeDirectService()
    payload = AgentTaskRequest(
        agent_task="Fix the header spacing.",
        root_task_id="root-123",
        previous_task_id="root-123",
        local_preview_feedback={
            "source_artifact_id": "artifact-1",
            "mode": "static",
            "preview_url": "basil-preview-file://preview/unrelated.html",
            "location_status": "fallback",
            "console_evidence": "",
        },
    )

    with pytest.raises(HTTPException) as excinfo:
        await process_agent_task(
            payload=payload,
            service=service,
            knowledge_service=_FakeFeedbackKnowledgeService(task),
        )

    assert excinfo.value.status_code == 422
    assert excinfo.value.detail == "Preview feedback URL is not a permitted local preview URL."


@pytest.mark.asyncio
async def test_approval_policy_override_requires_the_host_credential():
    service = _FakeAgentTaskService()
    payload = AgentTaskRequest(
        agent_task="Create a report from my recent activity",
        agent_task_id="agent-task-123",
        approval_policy_override={"approval_mode": "always_approve"},
    )

    with pytest.raises(HTTPException) as excinfo:
        await process_agent_task(
            payload=payload,
            service=service,
            knowledge_service=_FakeKnowledgeServiceForRouting(),
            credential_type="webview",
        )

    assert excinfo.value.status_code == 403
    assert excinfo.value.detail == "approval_policy_override requires the host credential."
    assert service.direct_calls == []


@pytest.mark.asyncio
async def test_host_credential_forwards_the_approval_policy_override():
    service = _FakeAgentTaskService()
    payload = AgentTaskRequest(
        agent_task="Create a report from my recent activity",
        agent_task_id="agent-task-123",
        approval_policy_override={"approval_mode": "always_approve"},
    )

    await process_agent_task(
        payload=payload,
        service=service,
        knowledge_service=_FakeKnowledgeServiceForRouting(),
        credential_type="host",
    )

    assert len(service.direct_calls) == 1
    assert service.direct_calls[0]["approval_policy_override"] == {"approval_mode": "always_approve"}
