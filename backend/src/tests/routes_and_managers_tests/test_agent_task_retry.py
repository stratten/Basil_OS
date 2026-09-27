import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from api.routes.agent_tasks import core_routes
from api.services.agent_processing.tools.safety.interactive_approval import (
    InteractiveApprovalManager,
)


@pytest.fixture(autouse=True)
def clear_pending_approvals():
    InteractiveApprovalManager._pending_approvals.clear()
    yield
    InteractiveApprovalManager._pending_approvals.clear()


@pytest.mark.asyncio
async def test_retry_retires_pending_approval_before_returning_task_to_routing() -> None:
    task = SimpleNamespace(
        id="task-1",
        status="awaiting_user_input",
        original_prompt="Find the FaceTime call history.",
        transcribed_prompt="Find the FaceTime call history.",
        result_data={},
        execution_timeline=[],
    )
    approval = {
        "id": "approval-1",
        "agent_task_id": "task-1",
        "revision": 0,
        "status": "pending",
    }
    pending_future = asyncio.get_running_loop().create_future()
    InteractiveApprovalManager._pending_approvals["approval-1"] = pending_future

    agent_task_service = SimpleNamespace(
        get_agent_task=AsyncMock(return_value=task),
        clear_agent_task_execution_timeline=AsyncMock(),
        update_agent_task_status=AsyncMock(),
    )
    approval_repository = SimpleNamespace(
        list_pending_approvals_for_agent_task=AsyncMock(return_value=[approval]),
        cancel_pending_approvals_for_tasks=AsyncMock(),
    )
    knowledge_service = SimpleNamespace(
        agent_task_service=agent_task_service,
        execution_approval_repository=approval_repository,
    )
    submission_service = SimpleNamespace(
        cancel_current_agent_task=AsyncMock(return_value=True),
    )

    response = await core_routes.retry_agent_task(
        "task-1",
        knowledge_service=knowledge_service,
        service=submission_service,
    )

    assert response.success is True
    submission_service.cancel_current_agent_task.assert_awaited_once_with(
        agent_task_id="task-1",
    )
    approval_repository.cancel_pending_approvals_for_tasks.assert_awaited_once_with(
        ["task-1"],
    )
    assert pending_future.cancelled() is True
    assert agent_task_service.update_agent_task_status.await_args_list[0].kwargs["status"] == "failed"
    assert agent_task_service.update_agent_task_status.await_args_list[1].kwargs["status"] == "routing"


@pytest.mark.asyncio
async def test_retry_persists_model_id_override_into_accumulated_artifacts() -> None:
    task = SimpleNamespace(
        id="task-2",
        status="failed",
        original_prompt="Investigate the build script.",
        transcribed_prompt="Investigate the build script.",
        result_data={},
        execution_timeline=[],
        accumulated_artifacts={"model_id": "local-qwen-3.5", "reference_paths": ["/tmp/build.sh"]},
    )
    agent_task_service = SimpleNamespace(
        get_agent_task=AsyncMock(return_value=task),
        clear_agent_task_execution_timeline=AsyncMock(),
        update_agent_task_status=AsyncMock(),
    )
    approval_repository = SimpleNamespace(
        list_pending_approvals_for_agent_task=AsyncMock(return_value=[]),
        cancel_pending_approvals_for_tasks=AsyncMock(),
    )
    knowledge_service = SimpleNamespace(
        agent_task_service=agent_task_service,
        execution_approval_repository=approval_repository,
    )
    submission_service = SimpleNamespace(cancel_current_agent_task=AsyncMock(return_value=True))

    from api.routes.agent_tasks.core_routes import RetryAgentTaskRequest

    response = await core_routes.retry_agent_task(
        "task-2",
        request=RetryAgentTaskRequest(model_id="gpt-5-mini"),
        knowledge_service=knowledge_service,
        service=submission_service,
    )

    assert response.success is True
    routing_call = agent_task_service.update_agent_task_status.await_args_list[-1]
    assert routing_call.kwargs["status"] == "routing"
    assert routing_call.kwargs["accumulated_artifacts"] == {
        "model_id": "gpt-5-mini",
        "reference_paths": ["/tmp/build.sh"],
    }


@pytest.mark.asyncio
async def test_retry_without_model_override_leaves_accumulated_artifacts_untouched() -> None:
    task = SimpleNamespace(
        id="task-3",
        status="failed",
        original_prompt="Investigate the build script.",
        transcribed_prompt="Investigate the build script.",
        result_data={},
        execution_timeline=[],
        accumulated_artifacts={"model_id": "local-qwen-3.5"},
    )
    agent_task_service = SimpleNamespace(
        get_agent_task=AsyncMock(return_value=task),
        clear_agent_task_execution_timeline=AsyncMock(),
        update_agent_task_status=AsyncMock(),
    )
    approval_repository = SimpleNamespace(
        list_pending_approvals_for_agent_task=AsyncMock(return_value=[]),
        cancel_pending_approvals_for_tasks=AsyncMock(),
    )
    knowledge_service = SimpleNamespace(
        agent_task_service=agent_task_service,
        execution_approval_repository=approval_repository,
    )
    submission_service = SimpleNamespace(cancel_current_agent_task=AsyncMock(return_value=True))

    response = await core_routes.retry_agent_task(
        "task-3",
        knowledge_service=knowledge_service,
        service=submission_service,
    )

    assert response.success is True
    routing_call = agent_task_service.update_agent_task_status.await_args_list[-1]
    assert routing_call.kwargs["status"] == "routing"
    assert routing_call.kwargs["accumulated_artifacts"] is None
