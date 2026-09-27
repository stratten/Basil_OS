from types import SimpleNamespace
from datetime import datetime
import json

import pytest

from api.core.knowledge.sqlite.sqlite_knowledge_service import SQLiteKnowledgeService
from api.routes.agent_tasks.utils import derive_result_severity, extract_result_data, extract_result_outcome
from api.services.agent_processing.lifecycle.finalization.execution_result_processing import (
    _merge_execution_timelines,
    _summarize_intermediate_steps,
)
from api.services.agent_processing.lifecycle.execution_graph.service_tools import ServiceToolFactory
from api.services.agent_processing.lifecycle.execution_graph.system_prompts import AGENT_SYSTEM_PROMPT_TEMPLATE
from api.services.agent_processing.lifecycle.finalization.summary_payload import normalize_outcome_after_content
from api.services.agent_processing.lifecycle.submission.agent_task_processing.agent_task_orchestrator import (
    AgentTaskOrchestrator,
)
from api.services.agent_processing.service_capabilities.service_execution_engine import ExecutionResult
from api.services.agent_processing.service_capabilities.service_execution_engine import (
    ServiceExecutionEngine,
)
from api.services.agent_processing.tools.direct_application_interactions.email_integration.email_models import (
    EmailDataList,
    EmailSearchCriteria,
)
from api.services.agent_processing.tools.direct_application_interactions.email_integration.mail_app.parsing import (
    MailAppParser,
)
from api.services.agent_processing.tools.direct_application_interactions.email_integration.mail_app.script_generators import (
    MailAppScriptGenerator,
)
from api.services.agent_processing.tools.direct_application_interactions.email_integration.outlook import (
    OutlookAppleScriptService,
)
from api.services.agent_processing.tools.direct_application_interactions.email_integration.outlook.parsing import (
    OutlookEmailParser,
)
from api.services.agent_processing.tools.internal_basil_tools.iterative_work_tool import create_iterative_work_tool
from api.services.agent_processing.shared.agent_runtime_context import (
    reset_current_agent_context,
    set_current_agent_context,
)
from api.services.agent_processing.lifecycle.runtime.agent_work_ledger_service import (
    AgentWorkLedgerService,
)
from pydantic import BaseModel


def test_failed_workflow_merges_operation_data_and_derives_non_null_error():
    orchestrator = object.__new__(AgentTaskOrchestrator)
    operation_result = SimpleNamespace(
        error_message=None,
        user_feedback=None,
        data={
            "workflow_result": "Drafted 3 replies before one email timed out.",
            "final_envelope": {
                "success": False,
                "summary_text": "Partial result: drafted 3 replies.",
                "result_payload": {"draft_count": 3},
            },
            "workflow_details": {
                "results": [{"tool": "email_service.get_email_metadata", "success": True}]
            },
        },
    )

    merged = orchestrator._merge_result_data({"agent_output": "live partial"}, operation_result.data)
    error = orchestrator._derive_failure_error_message(operation_result)

    assert merged["agent_output"] == "live partial"
    assert merged["final_envelope"]["result_payload"]["draft_count"] == 3
    assert error == "Partial result: drafted 3 replies."


def test_agent_trace_summaries_are_json_safe_without_raw_actions():
    class FakeToolAction:
        def __init__(self):
            self.tool = "email_service_create_reply_email_draft"
            self.tool_input = {"reference_email_id": "167535"}
            self.log = "Invoking reply draft tool"

    summaries = _summarize_intermediate_steps(
        [(FakeToolAction(), {"success": True, "draft_id": "draft-1"})]
    )

    json.dumps(summaries)
    assert summaries[0]["tool"] == "email_service_create_reply_email_draft"
    assert summaries[0]["action_type"] == "FakeToolAction"
    assert summaries[0]["tool_input"]["reference_email_id"] == "167535"


def test_successful_finalizer_result_is_not_downgraded_by_later_errors():
    orchestrator = object.__new__(AgentTaskOrchestrator)

    assert orchestrator._has_successful_finalizer_result({
        "finalizer_result": {
            "success": True,
            "summary_text": "Drafted replies to 7 emails.",
        }
    })
    assert orchestrator._has_successful_finalizer_result({
        "data": {
            "final_envelope": {
                "success": True,
                "summary_text": "Created the requested files.",
            }
        }
    })


@pytest.mark.asyncio
async def test_agent_task_status_persistence_serializes_action_like_objects(tmp_path):
    class FakeToolAction:
        def __init__(self):
            self.tool = "email_service_get_email_metadata"
            self.tool_input = {"folder": "inbox"}

    service = SQLiteKnowledgeService(tmp_path / "knowledge.db")
    await service.store_agent_task(
        agent_task_id="task-json-safe",
        original_prompt="Draft email replies",
        transcribed_prompt="Draft email replies",
        status="processing",
    )
    await service.update_agent_task_status(
        agent_task_id="task-json-safe",
        status="completed",
        result_data={
            "workflow_result": "Done",
            "workflow_details": {
                "results": [{"intermediate_steps": [(FakeToolAction(), "ok")]}],
            },
        },
    )

    task = await service.get_agent_task("task-json-safe")

    assert task.status == "completed"
    assert task.result_data["workflow_result"] == "Done"
    json.dumps(task.result_data)


def test_extract_result_data_returns_failed_partial_after_rehydration():
    command = SimpleNamespace(
        status="failed",
        result_data={
            "failure_info": {"error": "Drafted 3 replies before retrieval timed out."},
            "workflow_details": {"results": []},
        },
        accumulated_artifacts=None,
        execution_timeline=[],
    )

    result_msg, files, ref_paths, err_msg, timeline = extract_result_data(command)

    assert result_msg == "Drafted 3 replies before retrieval timed out."
    assert err_msg == "Drafted 3 replies before retrieval timed out."
    assert files == []
    assert ref_paths == []
    assert timeline == []


def test_extract_result_data_returns_success_final_envelope_after_rehydration():
    command = SimpleNamespace(
        status="completed",
        result_data={
            "success": True,
            "workflow_result": "Workflow completed",
            "final_envelope": {
                "success": True,
                "summary_text": "Drafted replies to 7 emails from the past 3 days.",
                "result_payload": {"draft_count": 7},
            },
        },
        accumulated_artifacts=None,
        execution_timeline=[
            {"type": "step", "content": "Reading screen context", "detail_kind": "step_note"}
        ],
    )

    result_msg, files, ref_paths, err_msg, timeline = extract_result_data(command)

    assert result_msg == "Drafted replies to 7 emails from the past 3 days."
    assert err_msg is None
    assert files == []
    assert ref_paths == []
    assert timeline[0]["content"] == "Reading screen context"


def test_finalization_timeline_merge_preserves_live_persisted_steps():
    merged = _merge_execution_timelines(
        [
            {"id": "progress_reading", "content": "Reading screen context"},
            {"id": "dynamic_email_fetch", "content": "Retrieving emails from inbox", "type": "tool_start"},
        ],
        [
            {"id": "dynamic_email_fetch", "content": "Completed: Retrieving emails from inbox", "type": "tool_complete"},
            {"id": "final_summary", "content": "Final result summary"},
        ],
    )

    assert [entry["id"] for entry in merged] == [
        "progress_reading",
        "dynamic_email_fetch",
        "final_summary",
    ]
    assert merged[1]["content"] == "Completed: Retrieving emails from inbox"
    assert merged[1]["type"] == "tool_complete"


@pytest.mark.asyncio
async def test_agent_work_session_repository_lifecycle(tmp_path):
    service = SQLiteKnowledgeService(tmp_path / "knowledge.db")
    session_repository = service.agent_work_session_repository
    item_repository = service.agent_work_item_repository

    session = await session_repository.create_session(
        agent_task_id="task-not-yet-persisted",
        goal="Draft replies to selected emails",
        collection_type="email",
        strategy={"batch_size": 2},
        cursor={"date_from": "2026-04-30"},
    )
    await item_repository.add_items(
        session_id=session["id"],
        items=[
            {"external_id": "email-1", "metadata": {"subject": "One"}},
            {"external_id": "email-2", "metadata": {"subject": "Two"}},
        ],
    )
    claimed = await item_repository.claim_next(session_id=session["id"], limit=1)
    await item_repository.update_items(
        session_id=session["id"],
        updates=[{"id": claimed[0]["id"], "status": "drafted", "decision": {"reason": "needs reply"}}],
    )
    await session_repository.update_strategy(
        session_id=session["id"],
        strategy={"batch_size": 1},
        summary_so_far="One reply drafted.",
    )
    summary = await session_repository.summarize(session["id"])
    finished = await session_repository.finish(
        session_id=session["id"],
        summary_so_far="Covered one candidate; one remains.",
        status="partial",
    )

    assert claimed[0]["status"] == "in_progress"
    assert session["agent_task_id"] is None
    assert summary["item_counts"]["drafted"] == 1
    assert summary["item_counts"]["discovered"] == 1
    assert finished["status"] == "partial"
    assert finished["summary_so_far"] == "Covered one candidate; one remains."


@pytest.mark.asyncio
async def test_agent_work_session_finish_completed_rejects_unresolved_claimable_items(tmp_path):
    service = SQLiteKnowledgeService(tmp_path / "knowledge.db")
    session_repository = service.agent_work_session_repository
    item_repository = service.agent_work_item_repository

    session = await session_repository.create_session(
        goal="Review a discovered collection",
        collection_type="generic",
    )
    await item_repository.add_items(
        session_id=session["id"],
        items=[
            {"id": "external-item-1", "metadata": {"label": "One"}},
            {"id": "external-item-2", "status": "acted_on", "metadata": {"label": "Two"}},
        ],
    )

    finished = await session_repository.finish(
        session_id=session["id"],
        summary_so_far="All done.",
        status="completed",
    )
    summary = await session_repository.summarize(session["id"])

    assert finished["success"] is False
    assert finished["reason"] == "incomplete_coverage"
    assert finished["unresolved_counts"] == {"discovered": 1}
    assert summary["session"]["status"] == "active"


@pytest.mark.asyncio
async def test_agent_work_session_item_id_becomes_durable_external_id(tmp_path):
    service = SQLiteKnowledgeService(tmp_path / "knowledge.db")
    session_repository = service.agent_work_session_repository
    item_repository = service.agent_work_item_repository

    session = await session_repository.create_session(goal="Review ids", collection_type="generic")
    await item_repository.add_items(
        session_id=session["id"],
        items=[{"id": "model-provided-item-id", "metadata": {"label": "One"}}],
    )
    claimed = await item_repository.claim_next(session_id=session["id"], limit=1)
    update_result = await item_repository.update_items(
        session_id=session["id"],
        updates=[{"id": "model-provided-item-id", "status": "acted_on"}],
    )
    summary = await session_repository.summarize(session["id"])

    assert claimed[0]["external_id"] == "model-provided-item-id"
    assert claimed[0]["id"] != "model-provided-item-id"
    assert update_result["updated"] == 1
    assert summary["item_counts"]["acted_on"] == 1


@pytest.mark.asyncio
async def test_iterative_work_tool_attaches_runtime_agent_task_id(tmp_path, monkeypatch):
    service = SQLiteKnowledgeService(tmp_path / "knowledge.db")
    await service.store_agent_task(
        agent_task_id="runtime-task-1",
        original_prompt="Review a collection",
        transcribed_prompt="Review a collection",
        status="processing",
    )
    monkeypatch.setattr(
        "api.dependencies.get_sqlite_knowledge_service",
        lambda: service,
    )

    tool = create_iterative_work_tool()
    token = set_current_agent_context({"agent_task_id": "runtime-task-1"})
    try:
        raw_result = await tool.ainvoke({
            "action": "start",
            "goal": "Review runtime context",
            "collection_type": "generic",
        })
    finally:
        reset_current_agent_context(token)

    result = json.loads(raw_result)

    assert result["success"] is True
    assert result["session"]["agent_task_id"] == "runtime-task-1"


@pytest.mark.asyncio
async def test_work_ledger_captures_structured_results_and_renders_handoff(tmp_path):
    service = SQLiteKnowledgeService(tmp_path / "knowledge.db")
    await service.store_agent_task(
        agent_task_id="root-ledger-task",
        original_prompt="Review messages",
        transcribed_prompt="Review messages",
        status="processing",
    )
    ledger = AgentWorkLedgerService(service)
    context = {"agent_task_id": "root-ledger-task", "root_task_id": "root-ledger-task"}

    captured = await ledger.capture_tool_result(
        context=context,
        service="email_service",
        method="get_email_metadata",
        parameters={"folder": "inbox"},
        result={
            "success": True,
            "result": {
                "items": [{"id": "message-1", "subject": "One", "body": "do not persist"}],
                "coverage_metadata": {"coverage_complete": "false"},
            },
        },
    )
    handoff = await ledger.handoff(context=context)
    items = await service.agent_work_item_repository.get_items(
        session_id=captured["session"]["id"],
    )

    assert captured["receipt"]["execution_state"] == "succeeded"
    assert items[0]["external_id"] == "message-1"
    assert "body" not in items[0]["metadata"]
    assert "WORK LEDGER:" in handoff
    assert "root-ledger-task" in handoff
    assert '"coverage_complete": "false"' in handoff


@pytest.mark.asyncio
async def test_iterative_work_tool_rejects_sessions_from_another_task_chain(tmp_path, monkeypatch):
    service = SQLiteKnowledgeService(tmp_path / "knowledge.db")
    await service.store_agent_task(
        agent_task_id="ledger-owner",
        original_prompt="Owner task",
        transcribed_prompt="Owner task",
        status="processing",
    )
    await service.store_agent_task(
        agent_task_id="ledger-other",
        original_prompt="Other task",
        transcribed_prompt="Other task",
        status="processing",
    )
    owner_session = await AgentWorkLedgerService(service).ensure_session(
        context={"agent_task_id": "ledger-owner", "root_task_id": "ledger-owner"},
    )
    monkeypatch.setattr("api.dependencies.get_sqlite_knowledge_service", lambda: service)
    tool = create_iterative_work_tool()
    token = set_current_agent_context(
        {"agent_task_id": "ledger-other", "root_task_id": "ledger-other"},
    )
    try:
        result = json.loads(await tool.ainvoke({
            "action": "summarize", "session_id": owner_session["id"],
        }))
    finally:
        reset_current_agent_context(token)

    assert result["success"] is False
    assert "not accessible" in result["error"]


def test_extract_result_outcome_and_warning_severity_from_finalizer_payload():
    result_data = {
        "finalizer_result": {
            "result_payload": {
                "outcome": "partial",
                "message": "Processed 20 of 65 items.",
            }
        }
    }

    assert extract_result_outcome(result_data) == "partial"
    assert derive_result_severity("failed", result_data) == "warning"


def test_legacy_completed_with_warnings_projects_as_success():
    result_data = {
        "finalizer_result": {
            "result_payload": {
                "outcome": "completed_with_warnings",
                "message": "The requested work was delivered.",
            }
        }
    }

    assert derive_result_severity("completed", result_data) == "success"


def test_system_prompt_describes_strategy_promotion_without_forcing_batches():
    assert "start with a simple bounded first pass" in AGENT_SYSTEM_PROMPT_TEMPLATE
    assert "Do not force batching for small jobs" in AGENT_SYSTEM_PROMPT_TEMPLATE
    assert "iterative_work" in AGENT_SYSTEM_PROMPT_TEMPLATE
    assert "ledger every discovered item" in AGENT_SYSTEM_PROMPT_TEMPLATE
    assert "not hardcoded string matching" in AGENT_SYSTEM_PROMPT_TEMPLATE
    assert "discovered, reviewed, expanded, acted_on, skipped, failed, and unresolved" in AGENT_SYSTEM_PROMPT_TEMPLATE


def test_iterative_work_tool_exposes_compact_action_interface():
    tool = create_iterative_work_tool()

    assert tool.name == "iterative_work"
    assert "action" in tool.args_schema.model_fields
    assert "session_id" in tool.args_schema.model_fields
    assert "items" in tool.args_schema.model_fields
    assert "model-driven status" in tool.args_schema.model_fields["updates"].description
    assert "hardcoded string matching" in tool.description


def test_mail_metadata_script_uses_date_predicate_and_reports_candidate_count():
    generator = MailAppScriptGenerator()

    script = generator.get_email_metadata_script(
        folder="inbox",
        limit=50,
        search_criteria=EmailSearchCriteria(
            date_from=datetime(2026, 5, 7),
            date_to=datetime(2026, 5, 14),
        ),
    )

    assert "BASIL_MAIL_METADATA_COVERAGE" in script
    assert 'set candidateScope to "window_size=" & windowSize' in script
    assert "whose" not in script
    assert "((date received of aMessage) >= date" in script
    assert "messages windowStart thru windowEnd of inbox" in script
    assert "content of aMessage" not in script


@pytest.mark.parametrize(
    ("criteria", "expected_predicate"),
    [
        (EmailSearchCriteria(date_from=datetime(2026, 5, 7)), "((date received of aMessage) >= date"),
        (EmailSearchCriteria(date_to=datetime(2026, 5, 14)), "((date received of aMessage) <= date"),
    ],
)
def test_mail_metadata_single_date_bounds_use_received_date(
    criteria,
    expected_predicate,
):
    script = MailAppScriptGenerator().get_email_metadata_script("inbox", 50, criteria)

    assert expected_predicate in script
    assert "whose" not in script


def test_get_folders_script_is_account_aware_and_newline_delimited():
    script = MailAppScriptGenerator().get_folders_script()
    assert 'set end of folderList to "Inbox"' in script
    assert "mailboxes of anAccount" in script
    assert 'accountName & " / " & (name of aMailbox)' in script
    assert "text item delimiters to linefeed" in script
    assert "text item delimiters to \",\"" not in script


def test_metadata_script_account_qualified_folder_targets_account_mailbox():
    script = MailAppScriptGenerator().get_email_metadata_script("Work / INBOX", 10)
    assert 'mailbox "INBOX" of account "Work"' in script
    assert "whose" not in script


def test_metadata_script_unified_inbox_token_unchanged():
    script = MailAppScriptGenerator().get_email_metadata_script("inbox", 10)
    assert "messages windowStart thru windowEnd of inbox" in script


def test_parse_folders_newline_multi_account_dedupes_preserving_order():
    parser = MailAppParser()
    raw = "Inbox\nWork / INBOX\nWork / Sent\ninbox\nArchive"
    assert parser.parse_folders_from_applescript(raw) == [
        "Inbox",
        "Work / INBOX",
        "Work / Sent",
        "Archive",
    ]


def test_parse_folders_comma_fallback_preserves_outlook():
    parser = MailAppParser()
    raw = "Inbox (Index: 1), Sent (Index: 2), Archive (Index: 3)"
    assert parser.parse_folders_from_applescript(raw) == [
        "Inbox (Index: 1)",
        "Sent (Index: 2)",
        "Archive (Index: 3)",
    ]


def test_mail_parser_preserves_empty_result_coverage_metadata():
    parser = MailAppParser()

    emails = parser.parse_emails_from_applescript(
        "BASIL_MAIL_METADATA_COVERAGE: folder=inbox; limit=50; "
        "candidate_limit=1000; mailbox_count=2500; scanned=1000; returned=0; "
        "skipped=2; coverage_complete=false; coverage_reason=candidate_window_limited",
        "Mail",
    )

    assert isinstance(emails, EmailDataList)
    assert emails == []
    assert emails.coverage_metadata["coverage_complete"] == "false"
    assert emails.coverage_metadata["coverage_reason"] == "candidate_window_limited"


@pytest.mark.asyncio
async def test_service_tool_logs_failed_execution_result_and_timeout_kind():
    class FakeEngine:
        async def execute_service_method(self, service_name, method_name, kwargs):
            return ExecutionResult(
                success=False,
                error="RuntimeError: AppleScript execution failed: Timeout after 90 seconds",
                service=service_name,
                method=method_name,
            )

    class EmptyArgs(BaseModel):
        pass

    factory = ServiceToolFactory(FakeEngine(), capability_analyzer=None)
    tool = factory._create_tool_function(
        "email_service_get_email_metadata",
        "Get email metadata",
        EmptyArgs,
        "email_service",
        "get_email_metadata",
        {},
    )

    raw_result = await tool.ainvoke({})
    parsed = json.loads(raw_result)

    assert parsed["success"] is False
    assert factory.tool_error_log[0]["tool"] == "email_service.get_email_metadata"
    assert factory.tool_error_log[0]["type"] == "timeout"


@pytest.mark.asyncio
async def test_service_tool_captures_raw_result_in_work_ledger(monkeypatch, tmp_path):
    class EmailService:
        async def get_email_metadata(self):
            return {"items": [{"id": "raw-message-1", "subject": "Stored"}]}

    class EmptyArgs(BaseModel):
        pass

    captured = []

    async def capture_tool_result(self, **kwargs):
        captured.append(kwargs)
        return None

    monkeypatch.setattr(
        AgentWorkLedgerService,
        "capture_tool_result",
        capture_tool_result,
    )
    knowledge_service = SQLiteKnowledgeService(tmp_path / "knowledge.db")
    monkeypatch.setattr(
        "api.dependencies.get_sqlite_knowledge_service",
        lambda: knowledge_service,
    )
    engine = ServiceExecutionEngine()
    engine.register_service("email_service", EmailService())
    factory = ServiceToolFactory(engine, capability_analyzer=None)
    tool = factory._create_tool_function(
        "email_service_get_email_metadata",
        "Get email metadata",
        EmptyArgs,
        "email_service",
        "get_email_metadata",
        {},
    )
    token = set_current_agent_context({"agent_task_id": "ledger-tool-task"})
    try:
        await tool.ainvoke({})
    finally:
        reset_current_agent_context(token)

    assert captured[0]["service"] == "email_service"
    assert captured[0]["method"] == "get_email_metadata"
    assert captured[0]["result"].result["items"][0]["id"] == "raw-message-1"


@pytest.mark.asyncio
async def test_engine_capture_failure_preserves_failed_service_result(monkeypatch):
    class EmailService:
        async def get_email_metadata(self):
            return {"success": False, "error": "mail unavailable"}

    async def capture_tool_result(self, **kwargs):
        raise RuntimeError("ledger unavailable")

    monkeypatch.setattr(
        AgentWorkLedgerService,
        "capture_tool_result",
        capture_tool_result,
    )
    engine = ServiceExecutionEngine()
    engine.register_service("email_service", EmailService())
    token = set_current_agent_context({"agent_task_id": "capture-failure-task"})
    try:
        result = await engine.execute_service_method(
            "email_service",
            "get_email_metadata",
            {},
        )
    finally:
        reset_current_agent_context(token)

    assert result.success is False
    assert result.error == "mail unavailable"
    assert result.service == "email_service"
    assert result.method == "get_email_metadata"


def test_successful_finalization_is_not_downgraded_by_recovered_tool_errors():
    outcome, reason = normalize_outcome_after_content(
        outcome="success",
        success=True,
        has_tool_errors=True,
        has_failed_steps=True,
        content_available=True,
        outcome_reason="",
    )

    assert outcome == "success"
    assert reason == ""


def test_system_prompt_describes_adaptive_email_recovery_without_fixed_batching():
    assert "iterative_work` is a durable ledger, not the strategy itself" in AGENT_SYSTEM_PROMPT_TEMPLATE
    assert "Do not blindly walk backwards from today" in AGENT_SYSTEM_PROMPT_TEMPLATE
    assert "coverage is ambiguous or unresolved" in AGENT_SYSTEM_PROMPT_TEMPLATE
    assert "do not treat an unverified empty result as clean success" in AGENT_SYSTEM_PROMPT_TEMPLATE


def test_outlook_fallback_metadata_uses_real_inbox_discovery_not_global_inbox():
    service = OutlookAppleScriptService()
    script = service.get_email_metadata_script(
        "inbox",
        10,
        EmailSearchCriteria(date_from=datetime(2026, 5, 13), date_to=datetime(2026, 5, 14)),
    )

    assert 'folderName is "Inbox"' in script
    assert 'folderName is "INBOX"' in script
    assert 'folderName contains "Inbox"' in script
    assert "set targetFolder to inbox" not in script
    assert "BASIL_OUTLOOK_METADATA_COVERAGE" in script
    assert "selected_folder_index=" in script


def test_outlook_discovered_metadata_includes_coverage_variables():
    service = OutlookAppleScriptService()
    service.discovered_accounts = {
        "inbox_148": {
            "folder_index": 148,
            "folder_name": "Inbox",
            "message_count": 265,
            "account_name": "unknown",
            "account_email": "unknown",
        }
    }

    script = service.get_email_metadata_script(
        "inbox",
        10,
        EmailSearchCriteria(date_from=datetime(2026, 5, 13), date_to=datetime(2026, 5, 14)),
    )

    assert "set selectedFolderIndex" in script
    assert "set selectedFolderName" in script
    assert "set scannedCount to 0" in script
    assert "set skippedCount to 0" in script
    assert "BASIL_OUTLOOK_METADATA_COVERAGE" in script


def test_outlook_parser_preserves_coverage_and_splits_newline_records():
    raw_output = (
        "BASIL_OUTLOOK_METADATA_COVERAGE: folder=inbox; limit=10; "
        "selected_folder_index=148; selected_folder_name=Inbox; mailbox_count=267; "
        "candidate_count=35; scanned=2; returned=2; skipped=0; "
        "coverage_complete=false; coverage_reason=result_limit_reached\n"
        "216296|||One|||Sender One <one@example.com>|||Thursday, May 14, 2026 at 1:32:19 PM"
        "||||||false|||||||||thread-1|||not flagged\n"
        "216295|||Two|||Sender Two <two@example.com>|||Thursday, May 14, 2026 at 1:31:00 PM"
        "||||||true|||||||||thread-2|||not flagged"
    )

    emails = OutlookEmailParser().parse_emails_from_applescript(raw_output)

    assert isinstance(emails, EmailDataList)
    assert len(emails) == 2
    assert emails.coverage_metadata["selected_folder_index"] == "148"
    assert emails.coverage_metadata["coverage_complete"] == "false"
    assert emails[0].subject == "One"
    assert emails[1].subject == "Two"
