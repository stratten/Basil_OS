import sqlite3

import pytest

from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.agent_tasks.delegated_agent_evidence_repository import (
    DelegatedAgentEvidenceRepository,
)
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.agent_tasks.delegated_agent_repository import (
    DelegatedAgentRepository,
)
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.schema_management.agent_tasks.delegated_agent_migrations import (
    migrate_delegated_agent_tables,
)
from api.services.agent_processing.lifecycle.delegation.delegated_agent_evidence_capture_service import (
    DelegatedAgentEvidenceCaptureService,
)

_ASSESSMENT = {
    "parallelism_reason": "fixture parent requires one bounded delegated child",
    "independence_rationale": "the child has no dependency in this persistence test",
    "expected_benefit": "proves durable evidence ownership",
    "parent_work_can_continue": False,
    "child_cannot_delegate": True,
}


def _setup_database(db_path) -> None:
    connection = sqlite3.connect(db_path)
    try:
        connection.execute(
            "CREATE TABLE agent_tasks (id TEXT PRIMARY KEY, root_task_id TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'routing')"
        )
        connection.executemany(
            "INSERT INTO agent_tasks (id, root_task_id) VALUES (?, ?)",
            [("parent", "parent"), ("child", "parent")],
        )
        migrate_delegated_agent_tables(connection)
        connection.commit()
    finally:
        connection.close()


async def _admit_with_turn(db_path):
    runs = DelegatedAgentRepository(str(db_path))
    await runs.reserve_child_agent_task(
        parent_agent_task_id="parent",
        root_task_id="parent",
        child_agent_task_id="child",
        executor_kind="acp_provider",
        strategic_assessment=_ASSESSMENT,
    )
    run = await runs.admit_reserved_run(
        child_agent_task_id="child",
        admitted_scope={"read_only": True, "mutable_paths": []},
        evidence_policy={"required": "provider_reported"},
    )
    turn = await runs.start_turn(
        delegated_agent_run_id=run["id"],
        expected_revision=run["revision"],
        controller_instruction="Capture bounded provider facts.",
    )
    return runs, run, turn


@pytest.mark.asyncio
async def test_capture_activity_appends_message_and_relative_artifact_locator(tmp_path) -> None:
    db_path = tmp_path / "capture.db"
    _setup_database(db_path)
    _runs, run, turn = await _admit_with_turn(db_path)
    repository = DelegatedAgentEvidenceRepository(str(db_path))
    capture = DelegatedAgentEvidenceCaptureService(evidence_repository=repository)

    await capture.capture_activity(
        delegated_agent_run_id=run["id"],
        delegated_agent_turn_id=turn["id"],
        entry={
            "id": "provider-message-1",
            "type": "step",
            "summary": "Provider reported a bounded status update.",
            "metadata": {"provider_activity_kind": "agent_message"},
        },
    )
    await capture.capture_activity(
        delegated_agent_run_id=run["id"],
        delegated_agent_turn_id=turn["id"],
        entry={
            "id": "provider-tool-1",
            "type": "tool_complete",
            "summary": "Provider wrote a file.",
            "metadata": {
                "provider_activity_kind": "tool_call",
                "provider_locations": ["parent_graph_e2e_probe.txt"],
            },
        },
    )

    page = await repository.list_evidence_for_run(delegated_agent_run_id=run["id"])
    kinds = [item["kind"] for item in page["items"]]
    assert kinds == ["agent_message", "tool_call", "artifact_locator"]
    assert all(item["delegated_agent_turn_id"] == turn["id"] for item in page["items"])
    artifact = next(item for item in page["items"] if item["kind"] == "artifact_locator")
    assert artifact["artifact_locator"] == "parent_graph_e2e_probe.txt"


@pytest.mark.asyncio
async def test_capture_activity_accepts_later_tool_state_and_artifact_locator_without_failure(tmp_path) -> None:
    db_path = tmp_path / "capture.db"
    _setup_database(db_path)
    _runs, run, turn = await _admit_with_turn(db_path)
    repository = DelegatedAgentEvidenceRepository(str(db_path))
    capture = DelegatedAgentEvidenceCaptureService(evidence_repository=repository)
    pending_entry = {
        "id": "provider-tool-1",
        "type": "tool_start",
        "summary": "Provider writes the acceptance artifact.",
        "metadata": {
            "provider_activity_kind": "tool_call",
            "tool_kind": "write",
            "tool_status": "pending",
        },
    }
    completed_entry = {
        "id": "provider-tool-1",
        "type": "tool_complete",
        "summary": "Provider writes the acceptance artifact.",
        "metadata": {
            "provider_activity_kind": "tool_call",
            "provider_locations": ["parent_graph_e2e_probe.txt"],
            "tool_kind": "write",
            "tool_status": "completed",
        },
    }

    await capture.capture_activity(
        delegated_agent_run_id=run["id"],
        delegated_agent_turn_id=turn["id"],
        entry=pending_entry,
    )
    await capture.capture_activity(
        delegated_agent_run_id=run["id"],
        delegated_agent_turn_id=turn["id"],
        entry=completed_entry,
    )
    await capture.capture_activity(
        delegated_agent_run_id=run["id"],
        delegated_agent_turn_id=turn["id"],
        entry=completed_entry,
    )

    page = await repository.list_evidence_for_run(delegated_agent_run_id=run["id"])
    assert [item["kind"] for item in page["items"]] == ["tool_call", "tool_call", "artifact_locator"]
    assert [item["structured_data"].get("tool_status") for item in page["items"][:2]] == [
        "pending",
        "completed",
    ]
    assert page["items"][2]["artifact_locator"] == "parent_graph_e2e_probe.txt"
    assert capture.capture_state(delegated_agent_run_id=run["id"]) == "available"


@pytest.mark.asyncio
async def test_capture_activity_appends_distinct_locator_for_the_same_provider_entry(tmp_path) -> None:
    db_path = tmp_path / "capture.db"
    _setup_database(db_path)
    _runs, run, turn = await _admit_with_turn(db_path)
    repository = DelegatedAgentEvidenceRepository(str(db_path))
    capture = DelegatedAgentEvidenceCaptureService(evidence_repository=repository)
    base_entry = {
        "id": "provider-tool-2",
        "type": "tool_complete",
        "summary": "Provider wrote workspace artifacts.",
        "metadata": {
            "provider_activity_kind": "tool_call",
            "tool_kind": "write",
            "tool_status": "completed",
        },
    }
    first_entry = {
        **base_entry,
        "metadata": {**base_entry["metadata"], "provider_locations": ["first.txt"]},
    }
    second_entry = {
        **base_entry,
        "metadata": {**base_entry["metadata"], "provider_locations": ["second.txt"]},
    }

    await capture.capture_activity(
        delegated_agent_run_id=run["id"],
        delegated_agent_turn_id=turn["id"],
        entry=first_entry,
    )
    await capture.capture_activity(
        delegated_agent_run_id=run["id"],
        delegated_agent_turn_id=turn["id"],
        entry=second_entry,
    )

    page = await repository.list_evidence_for_run(delegated_agent_run_id=run["id"])
    assert [item["artifact_locator"] for item in page["items"] if item["kind"] == "artifact_locator"] == [
        "first.txt",
        "second.txt",
    ]
    assert capture.capture_state(delegated_agent_run_id=run["id"]) == "available"


@pytest.mark.asyncio
async def test_raw_detail_and_empty_summary_record_nothing(tmp_path) -> None:
    db_path = tmp_path / "capture.db"
    _setup_database(db_path)
    _runs, run, turn = await _admit_with_turn(db_path)
    repository = DelegatedAgentEvidenceRepository(str(db_path))
    capture = DelegatedAgentEvidenceCaptureService(evidence_repository=repository)

    await capture.capture_activity(
        delegated_agent_run_id=run["id"],
        delegated_agent_turn_id=turn["id"],
        entry={
            "id": "provider-thought-1",
            "type": "thinking",
            "summary": "Hidden reasoning",
            "metadata": {"provider_activity_kind": "agent_thought", "raw_detail": True},
        },
    )
    await capture.capture_activity(
        delegated_agent_run_id=run["id"],
        delegated_agent_turn_id=turn["id"],
        entry={
            "id": "provider-empty-1",
            "type": "step",
            "summary": "   ",
            "metadata": {"provider_activity_kind": "state_update"},
        },
    )

    page = await repository.list_evidence_for_run(delegated_agent_run_id=run["id"])
    assert page["items"] == []


@pytest.mark.asyncio
async def test_capture_terminal_response_stores_only_stop_reason_and_numeric_usage(tmp_path) -> None:
    db_path = tmp_path / "capture.db"
    _setup_database(db_path)
    _runs, run, turn = await _admit_with_turn(db_path)
    repository = DelegatedAgentEvidenceRepository(str(db_path))
    capture = DelegatedAgentEvidenceCaptureService(evidence_repository=repository)

    await capture.capture_terminal_response(
        delegated_agent_run_id=run["id"],
        delegated_agent_turn_id=turn["id"],
        response={
            "stopReason": "end_turn",
            "usage": {"input_tokens": 12, "output_tokens": 4, "raw_payload": "must-not-persist"},
            "text": "full provider transcript must not persist",
        },
    )

    page = await repository.list_evidence_for_run(delegated_agent_run_id=run["id"])
    assert len(page["items"]) == 1
    item = page["items"][0]
    assert item["kind"] == "turn_terminal_response"
    assert item["structured_data"] == {"stop_reason": "end_turn", "usage": {"input_tokens": 12, "output_tokens": 4}}
    assert "text" not in item["structured_data"]
    assert "raw_payload" not in item["structured_data"]


@pytest.mark.asyncio
async def test_repository_exception_records_capture_unavailable_without_raising(tmp_path) -> None:
    class _FailingRepository:
        async def append_evidence(self, **kwargs):
            raise RuntimeError("simulated persistence failure")

    capture = DelegatedAgentEvidenceCaptureService(evidence_repository=_FailingRepository())

    await capture.capture_activity(
        delegated_agent_run_id="run-1",
        delegated_agent_turn_id="turn-1",
        entry={
            "id": "provider-message-1",
            "type": "step",
            "summary": "Provider reported a bounded status update.",
            "metadata": {"provider_activity_kind": "agent_message"},
        },
    )

    assert capture.capture_state(delegated_agent_run_id="run-1") == "unavailable"
