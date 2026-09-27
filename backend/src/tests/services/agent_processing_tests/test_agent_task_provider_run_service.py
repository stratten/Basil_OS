"""Focused coverage for AgentTaskProviderRunService (Package 3A)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from api.core.knowledge.sqlite.sqlite_knowledge_service import SQLiteKnowledgeService
from api.services.agent_processing.lifecycle.submission.agent_task_processing.agent_task_provider_run_service import (
    AgentTaskProviderRunService,
)
from api.services.agent_processing.lifecycle.submission.agent_task_processing.agent_task_routing_service import (
    AgentTaskRoutingService,
)
from api.services.agent_providers.acp.session_client import AcpClientProtocolError
from api.services.agent_providers.runtime.process_supervisor import (
    ProviderLaunchOutcome,
    ProviderLaunchOutcomeStatus,
)


SOURCE_ROOT = Path(__file__).resolve().parents[3]


async def _seed_profile_and_grant(
    service: SQLiteKnowledgeService,
    *,
    workspace_root: str,
    launch_argv: tuple[str, ...] = ("fixture-acp", "--stdio"),
    authentication_method_id: str | None = None,
) -> tuple[dict[str, object], dict[str, object]]:
    profile = await service.provider_profile_repository.create_profile(
        display_name="Fixture Provider",
        launch_argv=launch_argv,
        environment_allowlist=("PYTHONPATH",),
        authentication_method_id=authentication_method_id,
    )
    grant = await service.provider_profile_repository.grant_workspace(
        provider_profile_id=str(profile["id"]),
        canonical_workspace_root=workspace_root,
    )
    return profile, grant


async def _store_agent_task(
    service: SQLiteKnowledgeService,
    *,
    agent_task_id: str,
    root_task_id: str | None = None,
) -> SimpleNamespace:
    effective_root = root_task_id or agent_task_id
    await service.store_agent_task(
        agent_task_id=agent_task_id,
        original_prompt="run provider",
        transcribed_prompt="run provider",
        status="processing",
        root_task_id=effective_root,
    )
    record = await service.get_agent_task(agent_task_id)
    assert record is not None
    return record


class _FakeSupervisor:
    def __init__(
        self,
        validated_request,
        *,
        client_info,
        client_capabilities,
        request_timeout_seconds=5.0,
    ) -> None:
        self.validated_request = validated_request
        self.launch_outcome = ProviderLaunchOutcome(
            status=ProviderLaunchOutcomeStatus.RUNNING,
            provider_profile_id=validated_request.provider_profile_id,
            display_name=validated_request.display_name,
            runtime_version="2.0.0-fixture",
            agent_capabilities={},
            diagnostic_message=None,
            exit_code=None,
            pid=12345,
            protocol_version=2,
        )
        self.last_outcome = self.launch_outcome
        self.session_id = "fixture-process-session"
        self.wait_outcome = ProviderLaunchOutcome(
            status=ProviderLaunchOutcomeStatus.COMPLETED,
            provider_profile_id=validated_request.provider_profile_id,
            display_name=validated_request.display_name,
            runtime_version="2.0.0-fixture",
            agent_capabilities={},
            diagnostic_message=None,
            exit_code=0,
            pid=12345,
        )
        self.create_session_event: asyncio.Event | None = None
        self.cancel_called = False
        self.request_handlers: dict[str, object] = {}
        self.send_prompt_raises: Exception | None = None
        self.last_prompt = None
        self.launch_outcome_override: ProviderLaunchOutcome | None = None

    async def launch(self) -> ProviderLaunchOutcome:
        if self.launch_outcome_override is not None:
            self.last_outcome = self.launch_outcome_override
            return self.launch_outcome_override
        self.last_outcome = self.launch_outcome
        return self.launch_outcome

    async def create_session(self):
        if self.create_session_event is not None:
            await self.create_session_event.wait()
        from api.services.agent_providers.acp.session_client import AcpSessionHandle

        return AcpSessionHandle(session_id=self.session_id)

    async def send_prompt(self, *, session_id: str, prompt):
        self.last_prompt = prompt
        if self.send_prompt_raises is not None:
            self.last_outcome = ProviderLaunchOutcome(
                status=ProviderLaunchOutcomeStatus.CRASHED,
                provider_profile_id=self.validated_request.provider_profile_id,
                display_name=self.validated_request.display_name,
                runtime_version="2.0.0-fixture",
                agent_capabilities={},
                diagnostic_message="simulated crash",
                exit_code=1,
                pid=12345,
            )
            raise self.send_prompt_raises
        return {}

    def register_notification_handler(self, method: str, handler) -> None:
        return None

    def register_request_handler(self, method: str, handler) -> None:
        self.request_handlers[method] = handler

    async def complete_turn(self) -> ProviderLaunchOutcome:
        self.last_outcome = self.wait_outcome
        return self.wait_outcome

    def mark_turn_idle(self) -> None:
        return None

    async def wait_for_exit(self) -> ProviderLaunchOutcome:
        self.last_outcome = self.wait_outcome
        return self.wait_outcome

    async def cancel(self) -> ProviderLaunchOutcome:
        self.cancel_called = True
        self.last_outcome = ProviderLaunchOutcome(
            status=ProviderLaunchOutcomeStatus.CANCELLED,
            provider_profile_id=self.validated_request.provider_profile_id,
            display_name=self.validated_request.display_name,
            runtime_version="2.0.0-fixture",
            agent_capabilities={},
            diagnostic_message=None,
            exit_code=None,
            pid=12345,
        )
        return self.last_outcome


@pytest.mark.asyncio
async def test_run_provider_task_persists_completed_run_and_returns_success_result(tmp_path) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    db_service = SQLiteKnowledgeService(tmp_path / "provider_runs.db")
    profile, grant = await _seed_profile_and_grant(db_service, workspace_root=str(workspace_root))
    record = await _store_agent_task(db_service, agent_task_id="task-1")
    routing_service = AgentTaskRoutingService(db_service=db_service, websocket_manager=None)
    fake_supervisor = _FakeSupervisor

    service = AgentTaskProviderRunService(
        provider_profile_repository=db_service.provider_profile_repository,
        provider_run_repository=db_service.provider_run_repository,
        provider_interaction_repository=db_service.provider_interaction_repository,
        routing_service=routing_service,
        supervisor_factory=fake_supervisor,
    )

    result = await service.run_provider_task(
        agent_task_id="task-1",
        agent_task_record=record,
        provider_target={
            "provider_profile_id": str(profile["id"]),
            "workspace_grant_id": str(grant["id"]),
            "candidate_workspace_path": str(workspace_root),
        },
    )

    assert result.success is True
    assert result.operation == "provider_run"
    runs = await db_service.provider_run_repository.list_runs_for_root("task-1")
    assert len(runs) == 1
    assert runs[0]["status"] == "completed"
    assert runs[0]["provider_session_id"] == "fixture-process-session"
    assert runs[0]["runtime_version"] == "2.0.0-fixture"
    assert runs[0]["capabilities"] == {
        "protocol_version": 2,
        "agent_capabilities": {},
    }
    assert result.data["delegated_turn_response"] == {}


@pytest.mark.asyncio
async def test_run_provider_task_forwards_the_configured_authentication_method_to_supervision(
    tmp_path,
) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    db_service = SQLiteKnowledgeService(tmp_path / "provider_runs.db")
    profile, grant = await _seed_profile_and_grant(
        db_service,
        workspace_root=str(workspace_root),
        authentication_method_id="api-key",
    )
    record = await _store_agent_task(db_service, agent_task_id="task-auth-success")
    supervisors: list[_FakeSupervisor] = []

    def factory(validated_request, *, client_info, client_capabilities):
        supervisor = _FakeSupervisor(
            validated_request,
            client_info=client_info,
            client_capabilities=client_capabilities,
        )
        supervisors.append(supervisor)
        return supervisor

    service = AgentTaskProviderRunService(
        provider_profile_repository=db_service.provider_profile_repository,
        provider_run_repository=db_service.provider_run_repository,
        provider_interaction_repository=db_service.provider_interaction_repository,
        routing_service=AgentTaskRoutingService(
            db_service=db_service,
            websocket_manager=None,
        ),
        supervisor_factory=factory,
    )

    result = await service.run_provider_task(
        agent_task_id="task-auth-success",
        agent_task_record=record,
        provider_target={
            "provider_profile_id": str(profile["id"]),
            "workspace_grant_id": str(grant["id"]),
            "candidate_workspace_path": str(workspace_root),
        },
    )

    assert result.success is True
    assert supervisors[0].validated_request.authentication_method_id == "api-key"
    assert supervisors[0].session_id == "fixture-process-session"


@pytest.mark.asyncio
async def test_authentication_rejection_fails_the_run_without_a_provider_session_or_secret_text(
    tmp_path,
) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    db_service = SQLiteKnowledgeService(tmp_path / "provider_runs.db")
    profile, grant = await _seed_profile_and_grant(
        db_service,
        workspace_root=str(workspace_root),
        authentication_method_id="api-key",
    )
    record = await _store_agent_task(db_service, agent_task_id="task-auth-rejected")
    supervisors: list[_FakeSupervisor] = []

    def factory(validated_request, *, client_info, client_capabilities):
        supervisor = _FakeSupervisor(
            validated_request,
            client_info=client_info,
            client_capabilities=client_capabilities,
        )
        supervisor.launch_outcome_override = ProviderLaunchOutcome(
            status=ProviderLaunchOutcomeStatus.AUTHENTICATION_FAILED,
            provider_profile_id=validated_request.provider_profile_id,
            display_name=validated_request.display_name,
            runtime_version="2.0.0-fixture",
            agent_capabilities={},
            diagnostic_message="AcpRemoteRequestError: Authentication required",
            exit_code=0,
            pid=12345,
        )
        supervisors.append(supervisor)
        return supervisor

    service = AgentTaskProviderRunService(
        provider_profile_repository=db_service.provider_profile_repository,
        provider_run_repository=db_service.provider_run_repository,
        provider_interaction_repository=db_service.provider_interaction_repository,
        routing_service=AgentTaskRoutingService(
            db_service=db_service,
            websocket_manager=None,
        ),
        supervisor_factory=factory,
    )

    result = await service.run_provider_task(
        agent_task_id="task-auth-rejected",
        agent_task_record=record,
        provider_target={
            "provider_profile_id": str(profile["id"]),
            "workspace_grant_id": str(grant["id"]),
            "candidate_workspace_path": str(workspace_root),
        },
    )

    runs = await db_service.provider_run_repository.list_runs_for_root(
        "task-auth-rejected"
    )

    assert result.success is False
    assert supervisors[0].last_outcome.status is ProviderLaunchOutcomeStatus.AUTHENTICATION_FAILED
    assert len(runs) == 1
    assert runs[0]["status"] == "failed"
    assert runs[0]["provider_session_id"] is None
    assert "Authentication required" in str(runs[0]["terminal_reason"])
    assert "api-key" not in str(runs[0])


@pytest.mark.asyncio
async def test_v1_provider_run_does_not_register_unadvertised_elicitation_handler(tmp_path) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    db_service = SQLiteKnowledgeService(tmp_path / "provider_runs.db")
    profile, grant = await _seed_profile_and_grant(
        db_service,
        workspace_root=str(workspace_root),
    )
    record = await _store_agent_task(db_service, agent_task_id="task-v1")
    supervisors: list[_FakeSupervisor] = []

    def factory(validated_request, *, client_info, client_capabilities, request_timeout_seconds=5.0):
        supervisor = _FakeSupervisor(
            validated_request,
            client_info=client_info,
            client_capabilities=client_capabilities,
            request_timeout_seconds=request_timeout_seconds,
        )
        supervisor.launch_outcome = ProviderLaunchOutcome(
            status=ProviderLaunchOutcomeStatus.RUNNING,
            provider_profile_id=validated_request.provider_profile_id,
            display_name=validated_request.display_name,
            runtime_version="1.18.13-fixture",
            agent_capabilities={},
            diagnostic_message=None,
            exit_code=None,
            pid=12345,
            protocol_version=1,
        )
        supervisors.append(supervisor)
        return supervisor

    service = AgentTaskProviderRunService(
        provider_profile_repository=db_service.provider_profile_repository,
        provider_run_repository=db_service.provider_run_repository,
        provider_interaction_repository=db_service.provider_interaction_repository,
        routing_service=AgentTaskRoutingService(db_service=db_service, websocket_manager=None),
        supervisor_factory=factory,
    )

    result = await service.run_provider_task(
        agent_task_id="task-v1",
        agent_task_record=record,
        provider_target={
            "provider_profile_id": str(profile["id"]),
            "workspace_grant_id": str(grant["id"]),
            "candidate_workspace_path": str(workspace_root),
        },
    )

    assert result.success is True
    assert supervisors[0].request_handlers.keys() == {"session/request_permission"}
    runs = await db_service.provider_run_repository.list_runs_for_root("task-v1")
    assert runs[0]["capabilities"] == {
        "protocol_version": 1,
        "agent_capabilities": {},
    }


@pytest.mark.asyncio
async def test_run_provider_task_persists_failed_run_when_launch_never_reaches_running(tmp_path) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    db_service = SQLiteKnowledgeService(tmp_path / "provider_runs.db")
    profile, grant = await _seed_profile_and_grant(db_service, workspace_root=str(workspace_root))
    record = await _store_agent_task(db_service, agent_task_id="task-2")

    def factory(validated_request, *, client_info, client_capabilities, request_timeout_seconds=5.0):
        supervisor = _FakeSupervisor(
            validated_request,
            client_info=client_info,
            client_capabilities=client_capabilities,
            request_timeout_seconds=request_timeout_seconds,
        )
        supervisor.launch_outcome_override = ProviderLaunchOutcome(
            status=ProviderLaunchOutcomeStatus.EXECUTABLE_NOT_FOUND,
            provider_profile_id=validated_request.provider_profile_id,
            display_name=validated_request.display_name,
            runtime_version=None,
            agent_capabilities=None,
            diagnostic_message="missing executable",
            exit_code=None,
            pid=None,
        )
        return supervisor

    service = AgentTaskProviderRunService(
        provider_profile_repository=db_service.provider_profile_repository,
        provider_run_repository=db_service.provider_run_repository,
        provider_interaction_repository=db_service.provider_interaction_repository,
        routing_service=AgentTaskRoutingService(db_service=db_service, websocket_manager=None),
        supervisor_factory=factory,
    )

    result = await service.run_provider_task(
        agent_task_id="task-2",
        agent_task_record=record,
        provider_target={
            "provider_profile_id": str(profile["id"]),
            "workspace_grant_id": str(grant["id"]),
            "candidate_workspace_path": str(workspace_root),
        },
    )

    assert result.success is False
    runs = await db_service.provider_run_repository.list_runs_for_root("task-2")
    assert len(runs) == 1
    assert runs[0]["status"] == "failed"
    assert runs[0]["terminal_reason"] == "missing executable"
    task = await db_service.get_agent_task("task-2")
    assert any(
        entry["metadata"].get("progress_step") == "Launching provider"
        and entry["metadata"].get("status") == "failed"
        for entry in task.execution_timeline
    )


@pytest.mark.asyncio
async def test_run_provider_task_persists_failed_run_when_send_prompt_crashes(tmp_path) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    db_service = SQLiteKnowledgeService(tmp_path / "provider_runs.db")
    profile, grant = await _seed_profile_and_grant(db_service, workspace_root=str(workspace_root))
    record = await _store_agent_task(db_service, agent_task_id="task-3")

    def factory(validated_request, *, client_info, client_capabilities, request_timeout_seconds=5.0):
        supervisor = _FakeSupervisor(
            validated_request,
            client_info=client_info,
            client_capabilities=client_capabilities,
            request_timeout_seconds=request_timeout_seconds,
        )
        supervisor.send_prompt_raises = AcpClientProtocolError("simulated crash")
        return supervisor

    service = AgentTaskProviderRunService(
        provider_profile_repository=db_service.provider_profile_repository,
        provider_run_repository=db_service.provider_run_repository,
        provider_interaction_repository=db_service.provider_interaction_repository,
        routing_service=AgentTaskRoutingService(db_service=db_service, websocket_manager=None),
        supervisor_factory=factory,
    )

    result = await service.run_provider_task(
        agent_task_id="task-3",
        agent_task_record=record,
        provider_target={
            "provider_profile_id": str(profile["id"]),
            "workspace_grant_id": str(grant["id"]),
            "candidate_workspace_path": str(workspace_root),
        },
    )

    assert result.success is False
    assert result.error_message == "simulated crash"
    runs = await db_service.provider_run_repository.list_runs_for_root("task-3")
    assert runs[0]["status"] == "failed"
    assert runs[0]["terminal_reason"] == "simulated crash"
    task = await db_service.get_agent_task("task-3")
    assert any(
        entry["metadata"].get("progress_step") == "Running provider turn"
        and entry["metadata"].get("status") == "failed"
        for entry in task.execution_timeline
    )


@pytest.mark.asyncio
async def test_run_provider_task_reports_launch_validation_failure_without_creating_a_run_row(
    tmp_path,
) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    db_service = SQLiteKnowledgeService(tmp_path / "provider_runs.db")
    record = await _store_agent_task(db_service, agent_task_id="task-4")
    service = AgentTaskProviderRunService(
        provider_profile_repository=db_service.provider_profile_repository,
        provider_run_repository=db_service.provider_run_repository,
        provider_interaction_repository=db_service.provider_interaction_repository,
        routing_service=AgentTaskRoutingService(db_service=db_service, websocket_manager=None),
        supervisor_factory=_FakeSupervisor,
    )

    result = await service.run_provider_task(
        agent_task_id="task-4",
        agent_task_record=record,
        provider_target={
            "provider_profile_id": "missing-profile",
            "workspace_grant_id": "missing-grant",
            "candidate_workspace_path": str(workspace_root),
        },
    )

    assert result.success is False
    assert await db_service.provider_run_repository.list_runs_for_root("task-4") == []


@pytest.mark.asyncio
async def test_cancelling_run_provider_task_cancels_the_supervisor_and_marks_the_run_cancelled(
    tmp_path,
) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    db_service = SQLiteKnowledgeService(tmp_path / "provider_runs.db")
    profile, grant = await _seed_profile_and_grant(db_service, workspace_root=str(workspace_root))
    record = await _store_agent_task(db_service, agent_task_id="task-5")
    created_supervisors: list[_FakeSupervisor] = []

    def factory(validated_request, *, client_info, client_capabilities, request_timeout_seconds=5.0):
        supervisor = _FakeSupervisor(
            validated_request,
            client_info=client_info,
            client_capabilities=client_capabilities,
            request_timeout_seconds=request_timeout_seconds,
        )
        supervisor.create_session_event = asyncio.Event()
        created_supervisors.append(supervisor)
        return supervisor

    service = AgentTaskProviderRunService(
        provider_profile_repository=db_service.provider_profile_repository,
        provider_run_repository=db_service.provider_run_repository,
        provider_interaction_repository=db_service.provider_interaction_repository,
        routing_service=AgentTaskRoutingService(db_service=db_service, websocket_manager=None),
        supervisor_factory=factory,
    )

    run_task = asyncio.create_task(
        service.run_provider_task(
            agent_task_id="task-5",
            agent_task_record=record,
            provider_target={
                "provider_profile_id": str(profile["id"]),
                "workspace_grant_id": str(grant["id"]),
                "candidate_workspace_path": str(workspace_root),
            },
        )
    )
    await asyncio.sleep(0.05)
    run_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await run_task

    assert created_supervisors
    assert created_supervisors[0].cancel_called is True
    runs = await db_service.provider_run_repository.list_runs_for_root("task-5")
    assert runs[0]["status"] == "cancelled"


@pytest.mark.asyncio
async def test_shutdown_supervisor_skips_a_supervisor_already_cancelled_by_prompt_cancellation() -> None:
    service = object.__new__(AgentTaskProviderRunService)
    supervisor = SimpleNamespace(
        last_outcome=SimpleNamespace(status=ProviderLaunchOutcomeStatus.CANCELLED),
        cancel=AsyncMock(),
    )

    await service._shutdown_supervisor(supervisor, "run-already-cancelled")

    supervisor.cancel.assert_not_awaited()


@pytest.mark.asyncio
async def test_cancellation_after_initialization_uses_the_persisted_run_revision(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    db_service = SQLiteKnowledgeService(tmp_path / "provider_runs.db")
    profile, grant = await _seed_profile_and_grant(db_service, workspace_root=str(workspace_root))
    record = await _store_agent_task(db_service, agent_task_id="task-5b")
    initialized = asyncio.Event()
    hold_initialization = asyncio.Event()
    original_mark_initialized = db_service.provider_run_repository.mark_run_initialized

    async def mark_initialized_then_wait(**kwargs):
        result = await original_mark_initialized(**kwargs)
        initialized.set()
        await hold_initialization.wait()
        return result

    monkeypatch.setattr(
        db_service.provider_run_repository,
        "mark_run_initialized",
        mark_initialized_then_wait,
    )
    created_supervisors: list[_FakeSupervisor] = []

    def factory(validated_request, *, client_info, client_capabilities, request_timeout_seconds=5.0):
        supervisor = _FakeSupervisor(
            validated_request,
            client_info=client_info,
            client_capabilities=client_capabilities,
            request_timeout_seconds=request_timeout_seconds,
        )
        created_supervisors.append(supervisor)
        return supervisor

    service = AgentTaskProviderRunService(
        provider_profile_repository=db_service.provider_profile_repository,
        provider_run_repository=db_service.provider_run_repository,
        provider_interaction_repository=db_service.provider_interaction_repository,
        routing_service=AgentTaskRoutingService(db_service=db_service, websocket_manager=None),
        supervisor_factory=factory,
    )
    run_task = asyncio.create_task(
        service.run_provider_task(
            agent_task_id="task-5b",
            agent_task_record=record,
            provider_target={
                "provider_profile_id": str(profile["id"]),
                "workspace_grant_id": str(grant["id"]),
                "candidate_workspace_path": str(workspace_root),
            },
        )
    )

    await initialized.wait()
    run_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await run_task

    assert created_supervisors[0].cancel_called is True
    runs = await db_service.provider_run_repository.list_runs_for_root("task-5b")
    assert runs[0]["status"] == "cancelled"


@pytest.mark.asyncio
async def test_unexpected_launch_error_seals_the_run_and_cleans_up_the_supervisor(tmp_path) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    db_service = SQLiteKnowledgeService(tmp_path / "provider_runs.db")
    profile, grant = await _seed_profile_and_grant(db_service, workspace_root=str(workspace_root))
    record = await _store_agent_task(db_service, agent_task_id="task-5c")
    created_supervisors: list[_FakeSupervisor] = []

    class _LaunchErrorSupervisor(_FakeSupervisor):
        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, **kwargs)
            self.client = SimpleNamespace(close=AsyncMock())

        async def launch(self) -> ProviderLaunchOutcome:
            raise OSError("simulated launch failure")

        async def cancel(self) -> ProviderLaunchOutcome:
            raise RuntimeError("launch never reached running")

    def factory(validated_request, *, client_info, client_capabilities, request_timeout_seconds=5.0):
        supervisor = _LaunchErrorSupervisor(
            validated_request,
            client_info=client_info,
            client_capabilities=client_capabilities,
            request_timeout_seconds=request_timeout_seconds,
        )
        created_supervisors.append(supervisor)
        return supervisor

    service = AgentTaskProviderRunService(
        provider_profile_repository=db_service.provider_profile_repository,
        provider_run_repository=db_service.provider_run_repository,
        provider_interaction_repository=db_service.provider_interaction_repository,
        routing_service=AgentTaskRoutingService(db_service=db_service, websocket_manager=None),
        supervisor_factory=factory,
    )

    result = await service.run_provider_task(
        agent_task_id="task-5c",
        agent_task_record=record,
        provider_target={
            "provider_profile_id": str(profile["id"]),
            "workspace_grant_id": str(grant["id"]),
            "candidate_workspace_path": str(workspace_root),
        },
    )

    assert result.success is False
    created_supervisors[0].client.close.assert_awaited_once()
    runs = await db_service.provider_run_repository.list_runs_for_root("task-5c")
    assert runs[0]["status"] == "failed"


@pytest.mark.asyncio
async def test_run_provider_task_defaults_candidate_workspace_path_to_the_grant_root(tmp_path) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    db_service = SQLiteKnowledgeService(tmp_path / "provider_runs.db")
    profile, grant = await _seed_profile_and_grant(db_service, workspace_root=str(workspace_root))
    record = await _store_agent_task(db_service, agent_task_id="task-6")
    captured: dict[str, object] = {}

    def factory(validated_request, *, client_info, client_capabilities, request_timeout_seconds=5.0):
        captured["resolved_workspace_root"] = validated_request.resolved_workspace_root
        return _FakeSupervisor(
            validated_request,
            client_info=client_info,
            client_capabilities=client_capabilities,
            request_timeout_seconds=request_timeout_seconds,
        )

    service = AgentTaskProviderRunService(
        provider_profile_repository=db_service.provider_profile_repository,
        provider_run_repository=db_service.provider_run_repository,
        provider_interaction_repository=db_service.provider_interaction_repository,
        routing_service=AgentTaskRoutingService(db_service=db_service, websocket_manager=None),
        supervisor_factory=factory,
    )

    await service.run_provider_task(
        agent_task_id="task-6",
        agent_task_record=record,
        provider_target={
            "provider_profile_id": str(profile["id"]),
            "workspace_grant_id": str(grant["id"]),
        },
    )

    assert captured["resolved_workspace_root"] == str(workspace_root.resolve())


@pytest.mark.asyncio
async def test_acp_turn_hands_off_to_parent_supervision_with_bounded_evidence(tmp_path) -> None:
    from api.services.agent_processing.lifecycle.delegation.acp_session_controller import (
        AcpDelegatedSessionController,
    )

    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    db_service = SQLiteKnowledgeService(tmp_path / "provider_runs.db")
    profile, grant = await _seed_profile_and_grant(db_service, workspace_root=str(workspace_root))
    await _store_agent_task(db_service, agent_task_id="parent-1", root_task_id="parent-1")
    await db_service.store_agent_task(
        agent_task_id="child-1",
        original_prompt="run provider",
        transcribed_prompt="run provider",
        status="routing",
        root_task_id="parent-1",
    )
    record = await db_service.get_agent_task("child-1")

    await db_service.delegated_agent_repository.reserve_child_agent_task(
        parent_agent_task_id="parent-1",
        root_task_id="parent-1",
        child_agent_task_id="child-1",
        executor_kind="acp_provider",
        strategic_assessment={
            "parallelism_reason": "ACP provider executes the task in its own supervised turn.",
            "independence_rationale": "The provider turn is isolated from the parent workflow.",
            "expected_benefit": "The provider turn is isolated from the parent workflow.",
            "parent_work_can_continue": False,
            "child_cannot_delegate": True,
        },
    )
    await db_service.delegated_agent_repository.admit_reserved_run(
        child_agent_task_id="child-1",
        admitted_scope={"read_only": False},
        evidence_policy={"required": "provider_reported"},
    )

    class _FakePresentationController:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        async def handle_idle_turn(self, *, delegated_agent_run):
            return {**delegated_agent_run, "status": "supervision_due"}

        async def present_acp_turn_to_parent(self, *, delegated_agent_run):
            self.calls.append({"delegated_agent_run": delegated_agent_run})

    class _FakeEvidenceCapture:
        def __init__(self) -> None:
            self.activity_calls: list[dict[str, object]] = []

        async def capture_activity(self, **kwargs):
            self.activity_calls.append(kwargs)

        async def capture_terminal_response(self, **kwargs):
            return None

    class _SupervisionSupervisor(_FakeSupervisor):
        def register_notification_handler(self, method: str, handler) -> None:
            self._notification_handlers = getattr(self, "_notification_handlers", {})
            self._notification_handlers[method] = handler

        async def send_prompt(self, *, session_id: str, prompt):
            handler = getattr(self, "_notification_handlers", {}).get("session/update")
            if handler is not None:
                await handler({
                    "sessionId": session_id,
                    "update": {
                        "sessionUpdate": "agent_message",
                        "messageId": "message-1",
                        "content": {"type": "text", "text": "Provider reported a bounded status update."},
                    },
                })
            return await super().send_prompt(session_id=session_id, prompt=prompt)

    capture = _FakeEvidenceCapture()
    controller = _FakePresentationController()
    acp_sessions = AcpDelegatedSessionController()
    service = AgentTaskProviderRunService(
        provider_profile_repository=db_service.provider_profile_repository,
        provider_run_repository=db_service.provider_run_repository,
        provider_interaction_repository=db_service.provider_interaction_repository,
        routing_service=AgentTaskRoutingService(db_service=db_service, websocket_manager=None),
        delegated_agent_repository=db_service.delegated_agent_repository,
        acp_session_controller=acp_sessions,
        delegated_agent_controller=controller,
        evidence_capture_service=capture,
        supervisor_factory=_SupervisionSupervisor,
    )

    result = await service.run_provider_task(
        agent_task_id="child-1",
        agent_task_record=record,
        provider_target={
            "provider_profile_id": str(profile["id"]),
            "workspace_grant_id": str(grant["id"]),
            "candidate_workspace_path": str(workspace_root),
        },
    )

    assert result.success is True
    assert result.data["outcome_status"] == "awaiting_supervision"
    assert len(controller.calls) == 1
    presented_run = controller.calls[0]["delegated_agent_run"]
    assert presented_run["status"] == "supervision_due"
    import sqlite3

    connection = sqlite3.connect(db_service.db_path)
    try:
        turns = [
            {"id": row[0]}
            for row in connection.execute(
                "SELECT id FROM delegated_agent_turns WHERE delegated_agent_run_id = ? ORDER BY turn_sequence",
                (presented_run["id"],),
            ).fetchall()
        ]
    finally:
        connection.close()
    assert turns
    assert capture.activity_calls
    assert capture.activity_calls[0]["delegated_agent_turn_id"] == turns[0]["id"]
    assert capture.activity_calls[0]["delegated_agent_turn_id"] != presented_run["id"]
