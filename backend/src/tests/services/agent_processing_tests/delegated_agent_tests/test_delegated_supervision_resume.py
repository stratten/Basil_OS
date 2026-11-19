"""Focused checkpoint-resume contract coverage for ACP parent supervision."""

from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from api.services.agent_processing.lifecycle.runtime import resume_terminal_finalizer
from api.services.agent_processing.lifecycle.runtime.checkpoint_workflow_service import (
    WorkflowCheckpointWorkflowService,
)


class _Db:
    def __init__(self, record: SimpleNamespace) -> None:
        self.record = record
        self.updates: list[dict[str, object]] = []

    async def get_agent_task(self, agent_task_id: str):
        return self.record if self.record.id == agent_task_id else None

    async def update_agent_task_status(self, **kwargs):
        self.updates.append(kwargs)


class _FakeApp:
    def __init__(self, checkpoint_values: dict, invoke_result: dict) -> None:
        self._checkpoint_values = checkpoint_values
        self._invoke_result = invoke_result
        self.invoked_with: dict | None = None

    async def aget_state(self, _config):
        return SimpleNamespace(values=dict(self._checkpoint_values))

    async def ainvoke(self, state, config=None):
        self.invoked_with = state
        return self._invoke_result


def _open(app: _FakeApp):
    @asynccontextmanager
    async def _ctx():
        yield app

    return _ctx()


def _nonterminal_record() -> SimpleNamespace:
    return SimpleNamespace(id="parent-1", status="awaiting_delegated_agents")


def _run() -> dict:
    return {
        "id": "delegated-run-1",
        "parent_agent_task_id": "parent-1",
        "executor_kind": "acp_provider",
        "status": "supervision_due",
        "revision": 4,
    }


def _report_card() -> dict:
    return {
        "delegated_agent_run_id": "delegated-run-1",
        "run_status": "supervision_due",
        "run_revision": 4,
        "capture_state": "available",
        "evidence_count": 2,
        "latest_summary": "Read the README and reported its summary.",
        "claims": [
            {
                "evidence_id": "evidence-1",
                "kind": "agent_message",
                "provenance": "provider_reported",
                "verification_state": "not_applicable",
                "summary": "Read the README and reported its summary.",
            }
        ],
        "artifacts": [
            {
                "evidence_id": "evidence-2",
                "kind": "artifact_locator",
                "provenance": "provider_reported",
                "verification_state": "pending",
            }
        ],
        "next_after_sequence": 3,
    }


@pytest.mark.asyncio
async def test_supervision_resume_injects_only_bounded_evidence(monkeypatch) -> None:
    from api.services.agent_processing.lifecycle.execution_graph import agent_graph_runtime
    import api.dependencies as deps

    db = _Db(_nonterminal_record())
    app = _FakeApp(
        checkpoint_values={"user_agent_task": "Review the delegated OpenCode turn.", "context": {}},
        invoke_result={
            "tool_execution_results": [{"success": True}],
            "final_envelope": {"success": True, "summary_text": "Supervision loop finished."},
        },
    )

    async def _fake_finalize(*_args):
        return None

    monkeypatch.setattr(agent_graph_runtime, "_open_tool_enhanced_graph", lambda: _open(app))
    monkeypatch.setattr(agent_graph_runtime, "_derive_thread_id", lambda *_a, **_k: "thread-1")
    monkeypatch.setattr(deps, "get_sqlite_knowledge_service", lambda: db)
    monkeypatch.setattr(resume_terminal_finalizer, "finalize_resumed_workflow", _fake_finalize)

    handler = WorkflowCheckpointWorkflowService()
    await handler.resume_workflow_for_delegated_supervision(
        parent_agent_task_id="parent-1",
        delegated_agent_run=_run(),
        report_card=_report_card(),
    )

    continuation = app.invoked_with["user_agent_task"]
    assert "[ACP SUPERVISION REQUIRED]" in continuation
    assert "delegated_agent_run_id: delegated-run-1" in continuation
    assert "executor_kind: acp_provider" in continuation
    assert "evidence_capture_state: available" in continuation
    assert "evidence_count: 2" in continuation
    assert "latest_summary: Read the README and reported its summary." in continuation
    assert "evidence_id': 'evidence-1'" in continuation or "'evidence_id': 'evidence-1'" in continuation
    assert "parent_graph_e2e_probe.txt" not in continuation
    assert "turn_response:" not in continuation
    assert "raw-payload-sentinel-should-not-leak" not in continuation
    assert app.invoked_with["context"]["delegated_supervision"] == {
        "delegated_agent_run_id": "delegated-run-1"
    }


@pytest.mark.asyncio
async def test_supervision_wait_does_not_terminally_finalize_parent(monkeypatch) -> None:
    from api.services.agent_processing.lifecycle.execution_graph import agent_graph_runtime
    import api.dependencies as deps

    db = _Db(_nonterminal_record())
    app = _FakeApp(
        checkpoint_values={"user_agent_task": "Review the delegated OpenCode turn.", "context": {}},
        invoke_result={
            "tool_execution_results": [
                {
                    "status": "awaiting_delegated_agents",
                    "needs_provider_delegation": True,
                    "delegation_id": "delegation-2",
                    "child_agent_task_id": "child-2",
                }
            ],
        },
    )
    finalize_calls: list[str] = []

    async def _spy_finalize(agent_task_id, *_args):
        finalize_calls.append(agent_task_id)

    monkeypatch.setattr(agent_graph_runtime, "_open_tool_enhanced_graph", lambda: _open(app))
    monkeypatch.setattr(agent_graph_runtime, "_derive_thread_id", lambda *_a, **_k: "thread-1")
    monkeypatch.setattr(deps, "get_sqlite_knowledge_service", lambda: db)
    monkeypatch.setattr(resume_terminal_finalizer, "finalize_resumed_workflow", _spy_finalize)

    handler = WorkflowCheckpointWorkflowService()
    await handler.resume_workflow_for_delegated_supervision(
        parent_agent_task_id="parent-1",
        delegated_agent_run=_run(),
        report_card=_report_card(),
    )

    assert finalize_calls == []
    assert db.updates == [
        {"agent_task_id": "parent-1", "status": "processing"},
        {"agent_task_id": "parent-1", "status": "awaiting_delegated_agents"},
    ]


@pytest.mark.asyncio
async def test_supervision_completion_finalizes_once(monkeypatch) -> None:
    from api.services.agent_processing.lifecycle.execution_graph import agent_graph_runtime
    import api.dependencies as deps

    db = _Db(_nonterminal_record())
    app = _FakeApp(
        checkpoint_values={"user_agent_task": "Review the delegated OpenCode turn.", "context": {}},
        invoke_result={
            "tool_execution_results": [{"success": True}],
            "final_envelope": {"success": True, "summary_text": "Supervision loop finished."},
        },
    )
    finalize_calls: list[str] = []

    async def _spy_finalize(agent_task_id, *_args):
        finalize_calls.append(agent_task_id)

    monkeypatch.setattr(agent_graph_runtime, "_open_tool_enhanced_graph", lambda: _open(app))
    monkeypatch.setattr(agent_graph_runtime, "_derive_thread_id", lambda *_a, **_k: "thread-1")
    monkeypatch.setattr(deps, "get_sqlite_knowledge_service", lambda: db)
    monkeypatch.setattr(resume_terminal_finalizer, "finalize_resumed_workflow", _spy_finalize)

    handler = WorkflowCheckpointWorkflowService()
    await handler.resume_workflow_for_delegated_supervision(
        parent_agent_task_id="parent-1",
        delegated_agent_run=_run(),
        report_card=_report_card(),
    )

    assert finalize_calls == ["parent-1"]
    assert db.updates == [{"agent_task_id": "parent-1", "status": "processing"}]
