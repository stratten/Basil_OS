from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from api.routes.agent_tasks.execution_models import ContinueSessionRequest
from api.routes.agent_tasks import session_control_routes


class _AgentTask:
    def __init__(self, status: str) -> None:
        self.status = status


class _AuthorizedProviderDelegationSubmissionService:
    async def submit_authorized_provider_delegation(self, **_kwargs):
        return {"success": True, "status": "routing"}


class _Coordinator:
    instances: list[_Coordinator] = []

    def __init__(
        self,
        *,
        websocket_manager,
        agent_task_submission_service=None,
    ) -> None:
        self.websocket_manager = websocket_manager
        self.agent_task_submission_service = agent_task_submission_service
        self.resume_calls: list[tuple[str, str]] = []
        self.__class__.instances.append(self)

    async def resume_workflow(self, *, agent_task_id: str, user_response: str):
        self.resume_calls.append((agent_task_id, user_response))
        return SimpleNamespace(
            execution_results=[],
            final_envelope=None,
            todos_completed=1,
            overall_success=True,
            error_message=None,
        )


@pytest.mark.asyncio
async def test_continue_session_passes_orchestrator_authorized_delegation_owner(
    monkeypatch,
) -> None:
    authorized_owner = _AuthorizedProviderDelegationSubmissionService()
    submission_service = SimpleNamespace(
        agent_task_orchestrator=SimpleNamespace(
            authorized_provider_delegation_submission_service=authorized_owner
        )
    )
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(agent_task_submission_service=submission_service)
        )
    )
    _Coordinator.instances = []
    monkeypatch.setattr(session_control_routes, "WorkflowCoordinator", _Coordinator)
    monkeypatch.setattr(
        session_control_routes,
        "_get_agent_task_or_raise",
        AsyncMock(return_value=_AgentTask("awaiting_user_input")),
    )

    response = await session_control_routes.continue_session(
        agent_task_id="parent-1",
        request=request,
        body=ContinueSessionRequest(
            agent_task_id="parent-1",
            user_input="target-choice-1",
            response_type="selection",
        ),
    )

    assert response.success is True
    assert len(_Coordinator.instances) == 1
    coordinator = _Coordinator.instances[0]
    assert coordinator.websocket_manager is submission_service
    assert coordinator.agent_task_submission_service is authorized_owner
    assert callable(
        getattr(
            coordinator.agent_task_submission_service,
            "submit_authorized_provider_delegation",
            None,
        )
    )
    assert coordinator.resume_calls == [("parent-1", "target-choice-1")]


@pytest.mark.asyncio
async def test_continue_session_keeps_ordinary_continuation_available_without_owner(
    monkeypatch,
) -> None:
    submission_service = SimpleNamespace(agent_task_orchestrator=None)
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(agent_task_submission_service=submission_service)
        )
    )
    _Coordinator.instances = []
    monkeypatch.setattr(session_control_routes, "WorkflowCoordinator", _Coordinator)
    monkeypatch.setattr(
        session_control_routes,
        "_get_agent_task_or_raise",
        AsyncMock(return_value=_AgentTask("awaiting_user_input")),
    )

    response = await session_control_routes.continue_session(
        agent_task_id="ordinary-parent-1",
        request=request,
        body=ContinueSessionRequest(
            agent_task_id="ordinary-parent-1",
            user_response="continue normally",
        ),
    )

    assert response.success is True
    assert len(_Coordinator.instances) == 1
    coordinator = _Coordinator.instances[0]
    assert coordinator.websocket_manager is submission_service
    assert coordinator.agent_task_submission_service is None
    assert coordinator.resume_calls == [("ordinary-parent-1", "continue normally")]
