import asyncio
import sqlite3
from datetime import datetime
from types import SimpleNamespace

import pytest
from starlette.routing import Match

from api.core.knowledge.sqlite.sqlite_knowledge_service import SQLiteKnowledgeService
from api.routes.agent_tasks.core_routes import (
    SaveAgentTaskAsSkillRequest,
    router as agent_task_router,
    save_agent_task_as_skill,
)
from api.routes.agent_tasks.history_routes import _delegated_provider_report_cards, get_agent_task_details
from api.routes.agent_tasks.models import (
    AgentTaskChainItem,
    AgentTaskDetailResponse,
)
from api.routes.agent_tasks.projections.artifact_presentation import (
    build_agent_task_presentation_summary,
    normalize_file_entry,
)
from api.routes.agent_tasks.utils import (
    extract_checkpoint_data,
    extract_result_data,
)
from api.services.skills import skill_service as skill_service_module
from api.services.skills.skill_service import SkillService
from api.services.skills.skill_store import SkillStore


def test_uppercase_agent_task_id_resolves_to_the_get_detail_route():
    task_id = "D1FD4640-8B72-4E33-834D-39252D3EA5F4"
    request_scope = {
        "type": "http",
        "method": "GET",
        "path": f"/api/v1/agent-tasks/{task_id}",
        "headers": [],
    }

    matched_routes = [
        route
        for route in agent_task_router.routes
        if route.matches(request_scope)[0] == Match.FULL
    ]

    assert len(matched_routes) == 1
    assert matched_routes[0].endpoint is get_agent_task_details


def test_detail_and_chain_models_serialize_typed_file_artifact_metadata():
    artifact = {
        "name": "renamed.txt",
        "path": "/tmp/renamed.txt",
        "operation": "rename",
        "source_path": "/tmp/original.txt",
        "kind": "file",
    }
    checkpoint_data = {
        "checkpoint_id": "reporting-period",
        "prompt": "Which reporting period should I use?",
        "input_type": "selection",
        "options": ["This quarter", "Last quarter"],
    }
    timestamp = datetime(2026, 1, 1)
    chain_item = AgentTaskChainItem(
        id="follow-up",
        original_prompt="Rename the file",
        timestamp=timestamp,
        status="completed",
        files=[artifact],
    )
    detail = AgentTaskDetailResponse(
        id="root",
        original_prompt="Rename the file",
        transcribed_prompt="Rename the file",
        timestamp=timestamp,
        status="completed",
        files=[artifact],
        follow_ups=[chain_item],
        checkpoint_data=checkpoint_data,
    )

    response = detail.model_dump()

    expected_legacy_artifact = {**artifact, "artifact": None}
    assert response["files"] == [expected_legacy_artifact]
    assert response["follow_ups"][0]["files"] == [expected_legacy_artifact]
    assert response["checkpoint_data"] == checkpoint_data


def test_extract_result_data_prefers_finalizer_files_and_retains_provenance():
    command = SimpleNamespace(
        status="completed",
        result_data={
            "files": [{"name": "stale.txt", "path": "/tmp/stale.txt"}],
            "finalizer_result": {
                "result_payload": {
                    "files": [{
                        "name": "renamed.txt",
                        "full_path": "/tmp/renamed.txt",
                        "operation": "rename",
                        "source_path": "/tmp/original.txt",
                        "kind": "file",
                    }],
                },
            },
        },
        accumulated_artifacts=None,
        execution_timeline=[],
    )

    _, files, _, _, _ = extract_result_data(command)

    assert len(files) == 1
    file_entry = files[0]
    assert {key: file_entry[key] for key in ("name", "path", "operation", "source_path", "kind")} == {
        "name": "renamed.txt",
        "path": "/tmp/renamed.txt",
        "operation": "rename",
        "source_path": "/tmp/original.txt",
        "kind": "file",
    }
    artifact = file_entry["artifact"]
    assert artifact["artifact_id"].startswith("file-")
    assert artifact["display_name"] == "renamed.txt"
    assert artifact["local_path"] == "/tmp/renamed.txt"
    assert artifact["artifact_kind"] == "file"
    assert artifact["operation"] == "rename"
    assert artifact["lifecycle"] == "ready"
    assert artifact["preview"] == {"capability": "unknown"}
    assert artifact["verification"] == {"status": "unknown"}


def test_detail_route_attaches_the_root_presentation_summary():
    task = SimpleNamespace(
        id="task-detail-summary",
        original_prompt="Create a report",
        transcribed_prompt="Create a report",
        display_prompt_markdown=None,
        title=None,
        origin_type=None,
        origin_id=None,
        timestamp=datetime(2026, 1, 1),
        status="awaiting_user_input",
        result_data={
            "finalizer_result": {
                "result_payload": {
                    "files": [
                        {
                            "artifact_id": "producer-report",
                            "name": "report.md",
                            "full_path": "/tmp/report.md",
                            "operation": "create",
                            "kind": "file",
                        }
                    ],
                    "steps": {"completed": 2, "total": 3},
                },
            },
        },
        app_name=None,
        window_title=None,
        root_task_id=None,
        previous_task_id=None,
        accumulated_artifacts=None,
        execution_timeline=[{"summary": "Created report.md", "metadata": {}}],
        operation_parameters=None,
    )

    class AgentTaskService:
        async def get_agent_task(self, agent_task_id):
            assert agent_task_id == task.id
            return task

        async def get_agent_task_chain(self, agent_task_id):
            assert agent_task_id == task.id
            return [task]

    detail = asyncio.run(
        get_agent_task_details(
            task.id,
            knowledge_service=SimpleNamespace(agent_task_service=AgentTaskService()),
        )
    )

    assert detail.agent_task_presentation_summary is not None
    assert detail.agent_task_presentation_summary.model_dump() == {
        "agent_task_id": task.id,
        "lifecycle": "awaiting_user_input",
        "latest_activity": "Created report.md",
        "workflow": {"total_steps": 3, "completed_steps": 2},
        "artifacts": [
            {
                "artifact_id": "producer-report",
                "display_name": "report.md",
                "local_path": "/tmp/report.md",
                "artifact_kind": "file",
                "operation": "create",
                "lifecycle": "ready",
                "source_timeline_entry_id": None,
                "source_step_id": None,
                "preview": {"capability": "unknown", "kind": None},
                "verification": {"status": "unknown", "summary": None},
                "review": None,
            }
        ],
        "artifact_count": 1,
        "verification_status": "unknown",
        "requires_user_attention": True,
        "delegated_provider_report_cards": {"items": []},
    }


def test_detail_route_attaches_a_distinct_presentation_summary_to_each_follow_up():
    root = SimpleNamespace(
        id="root-summary",
        original_prompt="Create the initial report",
        transcribed_prompt="Create the initial report",
        display_prompt_markdown=None,
        title=None,
        origin_type=None,
        origin_id=None,
        timestamp=datetime(2026, 1, 1),
        status="completed",
        result_data={"files": []},
        app_name=None,
        window_title=None,
        root_task_id=None,
        previous_task_id=None,
        accumulated_artifacts=None,
        execution_timeline=[],
        operation_parameters=None,
    )
    follow_up = SimpleNamespace(
        id="follow-up-summary",
        original_prompt="Read the completed report",
        display_prompt_markdown=None,
        timestamp=datetime(2026, 1, 1),
        status="completed",
        result_data={"files": [{"artifact_id": "follow-up-report", "name": "report.md", "path": "/tmp/report.md", "operation": "read", "kind": "file"}]},
        root_task_id="root-summary",
        previous_task_id="root-summary",
        chain_sequence_number=1,
        accumulated_artifacts=None,
        execution_timeline=[{"summary": "Read report.md", "metadata": {}}],
        operation_parameters=None,
    )

    class AgentTaskService:
        async def get_agent_task(self, agent_task_id):
            assert agent_task_id == root.id
            return root

        async def get_agent_task_chain(self, agent_task_id):
            assert agent_task_id == root.id
            return [root, follow_up]

    detail = asyncio.run(get_agent_task_details(root.id, knowledge_service=SimpleNamespace(agent_task_service=AgentTaskService())))

    assert detail.agent_task_presentation_summary is not None
    assert detail.agent_task_presentation_summary.agent_task_id == "root-summary"
    assert len(detail.follow_ups) == 1
    assert detail.follow_ups[0].agent_task_presentation_summary is not None
    assert detail.follow_ups[0].agent_task_presentation_summary.model_dump() == {
        "agent_task_id": "follow-up-summary",
        "lifecycle": "completed",
        "latest_activity": "Read report.md",
        "workflow": {"total_steps": None, "completed_steps": None},
        "artifacts": [
            {
                "artifact_id": "follow-up-report",
                "display_name": "report.md",
                "local_path": "/tmp/report.md",
                "artifact_kind": "file",
                "operation": "read",
                "lifecycle": "ready",
                "source_timeline_entry_id": None,
                "source_step_id": None,
                "preview": {"capability": "unknown", "kind": None},
                "verification": {"status": "unknown", "summary": None},
                "review": None,
            }
        ],
        "artifact_count": 1,
        "verification_status": "unknown",
        "requires_user_attention": False,
        "delegated_provider_report_cards": {"items": []},
    }


def test_detail_route_returns_each_turns_normalized_reasoning_history():
    root = SimpleNamespace(
        id="root-reasoning",
        original_prompt="Inspect the report",
        transcribed_prompt="Inspect the report",
        display_prompt_markdown=None,
        title=None,
        origin_type=None,
        origin_id=None,
        timestamp=datetime(2026, 1, 1),
        status="completed",
        result_data={
            "thinking_history": [
                {"iteration": 2, "text": "Root final thought", "is_complete": True},
                {"iteration": 1, "text": "Root first thought", "is_complete": True},
                {"iteration": "bad", "text": "Ignored", "is_complete": True},
            ],
        },
        app_name=None,
        window_title=None,
        root_task_id=None,
        previous_task_id=None,
        accumulated_artifacts=None,
        execution_timeline=[],
        operation_parameters=None,
    )
    follow_up = SimpleNamespace(
        id="follow-up-reasoning",
        original_prompt="Explain the finding",
        display_prompt_markdown=None,
        timestamp=datetime(2026, 1, 1),
        status="completed",
        result_data={
            "thinking_history": [
                {"iteration": 1, "text": "Follow-up thought", "is_complete": True},
            ],
        },
        root_task_id="root-reasoning",
        previous_task_id="root-reasoning",
        chain_sequence_number=1,
        accumulated_artifacts=None,
        execution_timeline=[],
        operation_parameters=None,
    )

    class AgentTaskService:
        async def get_agent_task(self, agent_task_id):
            assert agent_task_id == root.id
            return root

        async def get_agent_task_chain(self, agent_task_id):
            assert agent_task_id == root.id
            return [root, follow_up]

    detail = asyncio.run(
        get_agent_task_details(
            root.id,
            knowledge_service=SimpleNamespace(agent_task_service=AgentTaskService()),
        )
    )

    assert detail.thinking_history == [
        {"iteration": 1, "text": "Root first thought", "is_complete": True},
        {"iteration": 2, "text": "Root final thought", "is_complete": True},
    ]
    assert detail.follow_ups[0].thinking_history == [
        {"iteration": 1, "text": "Follow-up thought", "is_complete": True},
    ]
    assert AgentTaskDetailResponse(
        id="missing",
        original_prompt="missing",
        transcribed_prompt="missing",
        timestamp=datetime(2026, 1, 1),
        status="completed",
    ).thinking_history == []


def test_detail_route_exposes_the_model_used_per_attempt():
    root = SimpleNamespace(
        id="root-model",
        original_prompt="Investigate the build script",
        transcribed_prompt="Investigate the build script",
        display_prompt_markdown=None,
        title=None,
        origin_type=None,
        origin_id=None,
        timestamp=datetime(2026, 1, 1),
        status="failed",
        result_data={},
        app_name=None,
        window_title=None,
        root_task_id=None,
        previous_task_id=None,
        accumulated_artifacts={"model_id": "local-qwen-3.5"},
        execution_timeline=[],
        operation_parameters=None,
    )
    follow_up = SimpleNamespace(
        id="follow-up-model",
        original_prompt="Try again with a different model",
        display_prompt_markdown=None,
        timestamp=datetime(2026, 1, 1),
        status="completed",
        result_data={"files": []},
        root_task_id="root-model",
        previous_task_id="root-model",
        chain_sequence_number=1,
        accumulated_artifacts={"model_id": "gpt-5-mini"},
        execution_timeline=[],
        operation_parameters=None,
    )

    class AgentTaskService:
        async def get_agent_task(self, agent_task_id):
            assert agent_task_id == root.id
            return root

        async def get_agent_task_chain(self, agent_task_id):
            assert agent_task_id == root.id
            return [root, follow_up]

    detail = asyncio.run(get_agent_task_details(root.id, knowledge_service=SimpleNamespace(agent_task_service=AgentTaskService())))

    assert detail.model_id == "local-qwen-3.5"
    assert len(detail.follow_ups) == 1
    assert detail.follow_ups[0].model_id == "gpt-5-mini"


def test_detail_route_leaves_model_id_none_when_never_overridden():
    root = SimpleNamespace(
        id="root-no-model",
        original_prompt="Summarize the report",
        transcribed_prompt="Summarize the report",
        display_prompt_markdown=None,
        title=None,
        origin_type=None,
        origin_id=None,
        timestamp=datetime(2026, 1, 1),
        status="completed",
        result_data={"files": []},
        app_name=None,
        window_title=None,
        root_task_id=None,
        previous_task_id=None,
        accumulated_artifacts=None,
        execution_timeline=[],
        operation_parameters=None,
    )

    class AgentTaskService:
        async def get_agent_task(self, agent_task_id):
            return root

        async def get_agent_task_chain(self, agent_task_id):
            return [root]

    detail = asyncio.run(get_agent_task_details(root.id, knowledge_service=SimpleNamespace(agent_task_service=AgentTaskService())))

    assert detail.model_id is None


def test_extract_checkpoint_data_excludes_stale_or_malformed_payloads():
    checkpoint_data = {
        "checkpoint_id": "reporting-period",
        "prompt": "Which reporting period should I use?",
        "input_type": "selection",
    }

    awaiting_record = SimpleNamespace(
        status="awaiting_user_input",
        result_data={"checkpoint_data": checkpoint_data},
    )
    completed_record = SimpleNamespace(
        status="completed",
        result_data={"checkpoint_data": checkpoint_data},
    )
    malformed_awaiting_record = SimpleNamespace(
        status="awaiting_user_input",
        result_data={"checkpoint_data": "not-a-checkpoint"},
    )

    assert extract_checkpoint_data(awaiting_record) == checkpoint_data
    assert extract_checkpoint_data(completed_record) is None
    assert extract_checkpoint_data(malformed_awaiting_record) is None


def test_extract_checkpoint_data_builds_a_durable_clarification_checkpoint():
    clarification_record = SimpleNamespace(
        id="task-clarify",
        status="needs_clarification",
        result_data={},
        operation_parameters={"clarification_message": "Please provide the target date."},
    )

    assert extract_checkpoint_data(clarification_record) == {
        "checkpoint_id": "clarification-task-clarify",
        "prompt": "Please provide the target date.",
        "input_type": "data",
        "metadata": {"source": "clarification"},
    }


def test_normalize_file_entry_does_not_expose_untrusted_verification_or_missing_path_as_ready():
    entry = normalize_file_entry(
        {
            "name": "deleted-report.md",
            "operation": "delete",
            "verification": {
                "status": "verified",
                "summary": "Raw producer claim",
                "receipt": {"token": "must-not-leak"},
            },
            "content": "must-not-leak",
        }
    )

    artifact = entry["artifact"]
    assert artifact["display_name"] == "deleted-report.md"
    assert "local_path" not in artifact
    assert artifact["lifecycle"] == "unavailable"
    assert artifact["preview"] == {"capability": "unsupported"}
    assert artifact["verification"] == {"status": "unknown"}
    assert "content" not in artifact
    assert "receipt" not in artifact


def test_build_agent_task_presentation_summary_bounds_artifacts_and_omits_raw_activity():
    files = [
        normalize_file_entry(
            {
                "name": f"report-{index}.md",
                "full_path": f"/tmp/report-{index}.md",
                "operation": "create",
                "kind": "file",
            }
        )
        for index in range(7)
    ]
    files.append(
        normalize_file_entry(
            {
                "name": "report-0.md",
                "full_path": "/tmp/report-0.md",
                "operation": "write",
                "kind": "file",
            }
        )
    )

    summary = build_agent_task_presentation_summary(
        agent_task_id="task-summary",
        lifecycle="needs_clarification",
        result_data={
            "finalizer_result": {
                "result_payload": {
                    "steps": {"completed": 3, "total": 5},
                },
            },
        },
        execution_timeline=[
            {
                "title": "Sensitive raw shell response",
                "metadata": {"raw_detail": True},
            },
            {
                "summary": "Created the seven requested reports",
                "metadata": {},
            },
        ],
        files=files,
    )

    assert summary["agent_task_id"] == "task-summary"
    assert summary["lifecycle"] == "needs_clarification"
    assert summary["latest_activity"] == "Created the seven requested reports"
    assert summary["workflow"] == {"completed_steps": 3, "total_steps": 5}
    assert summary["artifact_count"] == 7
    assert len(summary["artifacts"]) == 6
    assert [artifact["display_name"] for artifact in summary["artifacts"]] == [
        "report-0.md",
        "report-1.md",
        "report-2.md",
        "report-3.md",
        "report-4.md",
        "report-5.md",
    ]
    assert summary["verification_status"] == "unknown"
    assert summary["requires_user_attention"] is True
    assert summary["delegated_provider_report_cards"] == {"items": []}


def test_build_agent_task_presentation_summary_rejects_malformed_workflow_counts():
    summary = build_agent_task_presentation_summary(
        agent_task_id="task-invalid-steps",
        lifecycle="processing",
        result_data={
            "final_envelope": {
                "result_payload": {
                    "steps": {"completed": "3", "total": -1},
                },
            },
        },
        execution_timeline=[{"body": "Raw body must not be selected", "metadata": {}}],
        files=[],
    )

    assert summary["workflow"] == {}
    assert "latest_activity" not in summary
    assert summary["artifacts"] == []
    assert summary["artifact_count"] == 0
    assert summary["verification_status"] == "unknown"
    assert summary["requires_user_attention"] is False
    assert summary["delegated_provider_report_cards"] == {"items": []}


def test_detail_route_attaches_parent_owned_delegated_provider_report_cards(tmp_path):
    db_path = tmp_path / "route-cards.db"
    from api.core.knowledge.sqlite.sqlite_knowledge_service import SQLiteKnowledgeService

    db_service = SQLiteKnowledgeService(db_path)
    task = SimpleNamespace(
        id="parent-with-cards",
        original_prompt="Delegate work",
        transcribed_prompt="Delegate work",
        display_prompt_markdown=None,
        title=None,
        origin_type=None,
        origin_id=None,
        timestamp=datetime(2026, 1, 1),
        status="processing",
        result_data={"files": []},
        app_name=None,
        window_title=None,
        root_task_id=None,
        previous_task_id=None,
        accumulated_artifacts=None,
        execution_timeline=[],
        operation_parameters=None,
    )

    class AgentTaskService:
        async def get_agent_task(self, agent_task_id):
            return task

        async def get_agent_task_chain(self, agent_task_id):
            return [task]

    async def _seed_cards():
        await db_service.store_agent_task(
            agent_task_id="parent-with-cards",
            original_prompt="Delegate work",
            transcribed_prompt="Delegate work",
            status="processing",
            root_task_id="parent-with-cards",
        )
        await db_service.store_agent_task(
            agent_task_id="child-with-cards",
            original_prompt="Run provider",
            transcribed_prompt="Run provider",
            status="routing",
            root_task_id="parent-with-cards",
        )
        await db_service.delegated_agent_repository.reserve_child_agent_task(
            parent_agent_task_id="parent-with-cards",
            root_task_id="parent-with-cards",
            child_agent_task_id="child-with-cards",
            executor_kind="acp_provider",
            strategic_assessment={
                "parallelism_reason": "fixture",
                "independence_rationale": "fixture",
                "expected_benefit": "fixture",
                "parent_work_can_continue": False,
                "child_cannot_delegate": True,
            },
        )
        run = await db_service.delegated_agent_repository.admit_reserved_run(
            child_agent_task_id="child-with-cards",
            admitted_scope={"read_only": False},
            evidence_policy={"required": "provider_reported"},
        )
        await db_service.delegated_agent_evidence_repository.append_evidence(
            delegated_agent_run_id=run["id"],
            delegated_agent_turn_id=None,
            source_event_key="route-card",
            source="provider_activity",
            kind="message",
            provenance="provider_reported",
            verification_state="not_applicable",
            summary="Provider completed this turn.",
            structured_data={"raw": "must-not-leak"},
            artifact_locator=None,
        )

    asyncio.run(_seed_cards())
    detail = asyncio.run(
        get_agent_task_details(
            task.id,
            knowledge_service=SimpleNamespace(
                agent_task_service=AgentTaskService(),
                delegated_agent_repository=db_service.delegated_agent_repository,
                delegated_agent_evidence_repository=db_service.delegated_agent_evidence_repository,
            ),
        )
    )

    cards = detail.agent_task_presentation_summary.delegated_provider_report_cards.items
    assert len(cards) == 1
    assert cards[0].latest_summary == "Provider completed this turn."
    assert cards[0].evidence_count == 1
    dumped = detail.agent_task_presentation_summary.model_dump()
    assert "structured_data" not in str(dumped)
    assert "claims" not in dumped


def test_delegated_provider_report_card_projection_failure_does_not_hide_task_detail():
    class FailingRuns:
        async def list_runs_for_parent(self, parent_agent_task_id):
            raise RuntimeError(f"unavailable: {parent_agent_task_id}")

    cards = asyncio.run(
        _delegated_provider_report_cards(
            SimpleNamespace(
                delegated_agent_repository=FailingRuns(),
                delegated_agent_evidence_repository=SimpleNamespace(),
            ),
            "parent-with-failed-cards",
        )
    )

    assert cards == []


def test_save_agent_task_as_skill_reuses_the_original_new_skill_on_retry(tmp_path):
    original_service = skill_service_module._skill_service_singleton
    skill_service = SkillService(store=SkillStore(skills_dir=tmp_path / "skills"))
    skill_service_module._skill_service_singleton = skill_service
    task = SimpleNamespace(
        id="completed-task",
        status="completed",
        result_data={},
        title="Inspect PDF",
        original_prompt="Inspect this PDF",
        transcribed_prompt="Inspect this PDF",
        updated_at=datetime(2026, 1, 1),
    )

    class AgentTaskService:
        async def get_agent_task(self, agent_task_id):
            assert agent_task_id == task.id
            return task

    request = SaveAgentTaskAsSkillRequest(
        title="Inspect PDF",
        body=(
            "1. Review the PDF inputs and surrounding context before acting.\n"
            "2. Inspect the document carefully and identify relevant findings.\n"
            "3. Verify each finding against the requested outcome before responding."
        ),
        when_to_use="Use when a PDF requires careful review.",
        triggers=["inspect pdf", "review pdf"],
    )
    try:
        first = asyncio.run(
            save_agent_task_as_skill(
                task.id,
                request,
                knowledge_service=SimpleNamespace(agent_task_service=AgentTaskService()),
            )
        )
        second = asyncio.run(
            save_agent_task_as_skill(
                task.id,
                request,
                knowledge_service=SimpleNamespace(agent_task_service=AgentTaskService()),
            )
        )
    finally:
        skill_service_module._skill_service_singleton = original_service

    assert first.slug == second.slug
    saved_skills = skill_service.list_skills()
    assert len(saved_skills) == 1
    assert saved_skills[0].metadata["creation_origin_key"] == "agent-task:completed-task"


@pytest.mark.asyncio
async def test_recent_conversation_task_summaries_are_origin_scoped_and_follow_latest_leaf(tmp_path):
    database = SQLiteKnowledgeService(tmp_path / "continuation-candidates.db")

    async def store(task_id, *, origin_id, status="completed", root_task_id=None, previous_task_id=None, sequence=0):
        await database.store_agent_task(
            agent_task_id=task_id,
            original_prompt=f"Request {task_id}",
            transcribed_prompt=f"Request {task_id}",
            display_prompt_markdown=f"Request {task_id}",
            status=status,
            root_task_id=root_task_id,
            previous_task_id=previous_task_id,
            chain_sequence_number=sequence,
            origin_type="conversation",
            origin_id=origin_id,
        )

    await store("root-old", origin_id="conversation-1")
    await store("root-middle", origin_id="conversation-1", status="failed")
    await store("root-new", origin_id="conversation-1")
    await store("root-other", origin_id="conversation-2")
    await store("root-extra", origin_id="conversation-1", status="cancelled")
    await store(
        "leaf-new",
        origin_id="conversation-1",
        status="failed",
        root_task_id="root-new",
        previous_task_id="root-new",
        sequence=1,
    )
    with sqlite3.connect(database.db_path) as conn:
        conn.execute("UPDATE agent_tasks SET last_turn_timestamp = '2026-01-01T00:00:00' WHERE id = 'root-old'")
        conn.execute("UPDATE agent_tasks SET last_turn_timestamp = '2026-01-02T00:00:00' WHERE id = 'root-middle'")
        conn.execute("UPDATE agent_tasks SET last_turn_timestamp = '2026-01-03T00:00:00' WHERE id = 'root-extra'")
        conn.execute("UPDATE agent_tasks SET last_turn_timestamp = '2026-01-04T00:00:00' WHERE id = 'root-new'")

    summaries = await database.list_recent_conversation_task_summaries("conversation-1", 3)

    assert [summary["root_task_id"] for summary in summaries] == [
        "root-new",
        "root-extra",
        "root-middle",
    ]
    assert summaries[0]["previous_task_id"] == "leaf-new"
    assert summaries[0]["status"] == "failed"
    with sqlite3.connect(database.db_path) as conn:
        index_names = {row[1] for row in conn.execute("PRAGMA index_list(agent_tasks)")}
    assert "idx_agent_tasks_conversation_roots" in index_names
    with pytest.raises(ValueError, match="conversation_id must not be empty"):
        await database.list_recent_conversation_task_summaries(" ", 3)
    with pytest.raises(ValueError, match="limit must be at least 1"):
        await database.list_recent_conversation_task_summaries("conversation-1", 0)
