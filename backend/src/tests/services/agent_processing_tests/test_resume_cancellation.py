import asyncio

import pytest

from api.services.agent_processing.lifecycle.runtime import resume_cancellation
from api.services.agent_processing.lifecycle.runtime.checkpoint_workflow_service import (
    WorkflowCheckpointWorkflowService,
)
from api.services.agent_processing.lifecycle.runtime.resume_cancellation import (
    ResumedRunCanceled,
    run_registered_resume,
)
from api.services.agent_processing.lifecycle.submission.agent_task_processing.agent_task_cancellation import (
    AgentTaskCancellationRegistry,
)
from api.services.agent_processing.shared import agent_run_registry


@pytest.fixture
def registry(monkeypatch):
    registry = AgentTaskCancellationRegistry()
    monkeypatch.setattr(agent_run_registry, "_registry", registry)
    return registry


@pytest.mark.asyncio
async def test_resume_runs_unregistered_without_a_registry(monkeypatch):
    monkeypatch.setattr(agent_run_registry, "_registry", None)

    async def work():
        return "done"

    assert await run_registered_resume("task-1", work()) == "done"


@pytest.mark.asyncio
async def test_stop_cancels_a_registered_resume(registry):
    started = asyncio.Event()

    async def work():
        started.set()
        await asyncio.sleep(30)
        return "never"

    resume = asyncio.create_task(run_registered_resume("task-1", work()))
    await started.wait()
    registry.mark_canceled({"task-1"})
    assert registry.cancel_active_task("task-1") is True

    with pytest.raises(ResumedRunCanceled):
        await resume


@pytest.mark.asyncio
async def test_stop_before_resume_starts_is_honored(registry):
    registry.mark_canceled({"task-1"})

    async def work():
        await asyncio.sleep(30)
        return "never"

    with pytest.raises(ResumedRunCanceled):
        await run_registered_resume("task-1", work())


@pytest.mark.asyncio
async def test_outer_cancellation_is_not_reported_as_a_stop(registry):
    started = asyncio.Event()

    async def work():
        started.set()
        await asyncio.sleep(30)

    resume = asyncio.create_task(run_registered_resume("task-1", work()))
    await started.wait()
    resume.cancel()

    with pytest.raises(asyncio.CancelledError):
        await resume


@pytest.mark.asyncio
async def test_finished_resume_is_deregistered(registry):
    async def work():
        return 3

    assert await run_registered_resume("task-1", work()) == 3
    assert registry.cancel_active_task("task-1") is False


def test_resolve_run_cancel_event_prefers_the_context_signal(registry):
    signal = asyncio.Event()
    assert agent_run_registry.resolve_run_cancel_event({"cancel_event": signal, "agent_task_id": "task-1"}) is signal


def test_resolve_run_cancel_event_falls_back_to_the_registry(registry):
    registry.mark_canceled({"task-1"})
    resolved = agent_run_registry.resolve_run_cancel_event({"agent_task_id": "task-1"})
    assert resolved is registry.get_cancellation_event("task-1")
    assert resolved.is_set() is True


def test_resolve_run_cancel_event_without_registry_or_id(monkeypatch):
    monkeypatch.setattr(agent_run_registry, "_registry", None)
    assert agent_run_registry.resolve_run_cancel_event({"agent_task_id": "task-1"}) is None
    assert agent_run_registry.resolve_run_cancel_event(None) is None


@pytest.mark.asyncio
async def test_settle_canceled_resume_records_canceled_status(monkeypatch):
    updates = []

    class _KnowledgeService:
        async def update_agent_task_status(self, **kwargs):
            updates.append(kwargs)

    monkeypatch.setattr("api.dependencies.get_sqlite_knowledge_service", lambda: _KnowledgeService())

    result = await WorkflowCheckpointWorkflowService()._settle_canceled_resume(
        "task-1",
        {"user_agent_task": "Find paint"},
    )

    assert updates == [{"agent_task_id": "task-1", "status": "canceled"}]
    assert result.overall_success is False
    assert result.error_message == "Run stopped"
    assert result.original_prompt == "Find paint"


def test_resume_cancellation_module_reads_the_shared_registry(registry):
    assert resume_cancellation.process_cancellation_registry() is registry
