"""Generic delegated-child result bridge contract tests."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest

from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.agent_tasks.events import AgentTaskEvent
from api.services.agent_processing.lifecycle.runtime.delegated_agent_result_bridge import DelegatedAgentResultBridge


@dataclass
class _Runs:
    run: dict | None

    async def get_run_for_child(self, child_id: str):
        return dict(self.run) if self.run and self.run["child_agent_task_id"] == child_id else None

    def mark_settled(self) -> None:
        if self.run is not None:
            self.run = {**self.run, "status": "settled"}

    async def list_restart_reconciliation_candidates(self):
        return [self.run] if self.run else []

    async def transition_run(self, **kwargs):
        assert self.run is not None
        assert kwargs["expected_revision"] == self.run["revision"]
        self.run = {**self.run, "status": kwargs["next_status"], "revision": self.run["revision"] + 1}
        return self.run


class _Controller:
    def __init__(self) -> None:
        self.settled: list[dict] = []
        self.cancelled: list[str] = []

    async def settle_run_and_maybe_resume_parent(self, **kwargs):
        self.settled.append(kwargs)
        run = dict(kwargs["delegated_agent_run"])
        run["status"] = {"completed": "settled", "failed": "failed", "cancelled": "cancelled"}[kwargs["child_status"]]
        return run

    async def cancel_parent_runs(self, *, parent_agent_task_id: str):
        self.cancelled.append(parent_agent_task_id)
        return [{"child_agent_task_id": "child-1"}]


def _event(status: str = "completed") -> AgentTaskEvent:
    return AgentTaskEvent(
        agent_task_id="child-1",
        event_type="status_changed",
        new_status=status,
        agent_task_data={"result_data": {"message": "done"}},
    )


def _run(status: str = "running") -> dict:
    return {
        "id": "run-1",
        "child_agent_task_id": "child-1",
        "parent_agent_task_id": "parent-1",
        "root_task_id": "root-1",
        "executor_kind": "internal_agent",
        "status": status,
        "revision": 2,
    }


@pytest.mark.asyncio
async def test_duplicate_terminal_event_is_idempotent() -> None:
    runs = _Runs(_run())
    controller = _Controller()
    bridge = DelegatedAgentResultBridge(delegated_agent_repository=runs, delegated_agent_controller=controller)

    bridge.handle_agent_task_event(_event())
    await asyncio.sleep(0)
    runs.mark_settled()
    bridge.handle_agent_task_event(_event())
    await asyncio.sleep(0)

    assert len(controller.settled) == 1
    assert controller.settled[0]["summary"] == "done"
    assert controller.settled[0]["evidence_state"] == "provider_reported"


@pytest.mark.asyncio
async def test_bridge_uses_unavailable_evidence_for_failed_child() -> None:
    controller = _Controller()
    bridge = DelegatedAgentResultBridge(
        delegated_agent_repository=_Runs(_run()),
        delegated_agent_controller=controller,
    )

    bridge.handle_agent_task_event(_event("failed"))
    await asyncio.sleep(0)

    assert controller.settled[0]["child_status"] == "failed"
    assert controller.settled[0]["evidence_state"] == "unavailable"


@pytest.mark.asyncio
async def test_restart_reconciles_only_acp_children() -> None:
    acp_run = _run("idle")
    acp_run["executor_kind"] = "acp_provider"
    internal_run = _run("running")
    internal_run["id"] = "run-2"
    internal_run["child_agent_task_id"] = "child-2"
    internal_run["executor_kind"] = "internal_agent"

    class MultiRuns(_Runs):
        async def list_restart_reconciliation_candidates(self):
            return [acp_run, internal_run]

    runs = MultiRuns(acp_run)
    controller = _Controller()
    bridge = DelegatedAgentResultBridge(delegated_agent_repository=runs, delegated_agent_controller=controller)

    assert await bridge.reconcile_startup() == 1

    assert len(controller.settled) == 1
    assert controller.settled[0]["delegated_agent_run"]["executor_kind"] == "acp_provider"
    assert controller.settled[0]["child_status"] == "failed"
    assert controller.settled[0]["evidence_state"] == "unavailable"


@pytest.mark.asyncio
async def test_parent_cancellation_routes_only_through_generic_controller() -> None:
    controller = _Controller()
    bridge = DelegatedAgentResultBridge(
        delegated_agent_repository=_Runs(_run()),
        delegated_agent_controller=controller,
    )

    assert await bridge.request_parent_cancellation("parent-1") == "child-1"
    assert controller.cancelled == ["parent-1"]


@pytest.mark.asyncio
async def test_restart_reconciliation_still_fails_unrestorable_acp_session() -> None:
    run = {**_run(status="supervision_due"), "executor_kind": "acp_provider"}
    runs = _Runs(run)
    controller = _Controller()
    bridge = DelegatedAgentResultBridge(delegated_agent_repository=runs, delegated_agent_controller=controller)

    count = await bridge.reconcile_startup()

    assert count == 1
    assert runs.run["status"] == "interrupted"
    assert len(controller.settled) == 1
    assert controller.settled[0]["child_status"] == "failed"
    assert controller.settled[0]["evidence_state"] == "unavailable"
