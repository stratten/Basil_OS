from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from api.services.agent_processing.lifecycle.planning.agent_context_assembler import AgentContextAssembler
from api.services.agent_processing.lifecycle.planning.request_analyzer import RequestAnalyzer
from api.services.agent_processing.lifecycle.submission import AgentTaskSubmissionService


class FakeAgentTask:
    def __init__(
        self,
        *,
        task_id: str,
        text: str,
        sequence: int,
        root_task_id: str | None = None,
        previous_task_id: str | None = None,
        result_data: dict | None = None,
        operation_parameters: dict | None = None,
        accumulated_artifacts: dict | None = None,
    ):
        self.id = task_id
        self.root_task_id = root_task_id
        self.previous_task_id = previous_task_id
        self.chain_sequence_number = sequence
        self.transcribed_prompt = text
        self.timestamp = datetime(2026, 4, 30, 12, sequence, 0)
        self.status = "completed"
        self.result_data = result_data
        self.operation_parameters = operation_parameters
        self.accumulated_artifacts = accumulated_artifacts


class FakeDbService:
    def __init__(self, chain):
        self.chain = chain

    async def get_agent_task(self, root_task_id):
        return self.chain[0]

    async def get_agent_task_chain(self, root_task_id):
        return self.chain


@pytest.mark.asyncio
async def test_build_chain_context_emits_chain_agentTasks():
    chain = [
        FakeAgentTask(task_id="root", text="Create a report", sequence=0),
        FakeAgentTask(
            task_id="follow-up",
            text="Make it shorter",
            sequence=1,
            root_task_id="root",
            previous_task_id="root",
            result_data={"message": "Shortened report"},
            operation_parameters={"operation": "multi_step_workflow"},
            accumulated_artifacts={
                "chain_agentTasks": [{"id": "stale", "text": "do not keep"}],
                "reference_paths": ["/tmp/reference.md"],
            },
        ),
    ]
    service = SimpleNamespace(db_service=FakeDbService(chain))

    context = await AgentTaskSubmissionService._build_chain_context(service, "root")

    artifacts = context["accumulated_artifacts"]
    assert "chain_agentTasks" in artifacts
    assert "chain_instructions" not in artifacts
    assert [item["id"] for item in artifacts["chain_agentTasks"]] == ["root", "follow-up"]
    assert artifacts["reference_paths"] == ["/tmp/reference.md"]


def test_context_assembler_formats_chain_agentTasks():
    rendered = AgentContextAssembler()._format_chain_context({
        "chain_agentTasks": [
            {
                "sequence": 0,
                "text": "Create a report",
                "status": "completed",
                "result": {"message": "Report created"},
            }
        ]
    })

    assert "User: Create a report" in rendered
    assert "You: Report created" in rendered
    assert "AgentTask #0" not in rendered


def test_context_assembler_prefers_workflow_agent_output_over_boilerplate_message():
    """Tool-enhanced workflow envelopes should surface the agent_output
    narrative to chain follow-ups rather than the prompt-echo boilerplate
    that lives in data.message."""
    narrative = (
        "STEP_COMPLETE: Retrieved 71 unread Slack messages across 15 conversations.\n\n"
        "**Key channels with unread messages:**\n- #verificationcodes (15 unread)\n"
        "- #altbanq-baobab (15 unread)"
    )
    rendered = AgentContextAssembler()._format_chain_context({
        "chain_agentTasks": [
            {
                "sequence": 0,
                "text": "Can you give me a report of my unread Slack messages?",
                "status": "completed",
                "result": {
                    "success": True,
                    "operation_type": "multi_step_workflow",
                    "data": {
                        "success": False,
                        "workflow_result": "Enhanced workflow completed successfully",
                        "message": (
                            "Enhanced workflow processed: Can you give me a "
                            "report of my unread Slack messages?"
                        ),
                        "todos_completed": 1,
                        "workflow_details": {
                            "results": [
                                {
                                    "execution_method": "dynamic_langchain_agent",
                                    "agent_output": narrative,
                                }
                            ]
                        },
                    },
                },
            }
        ]
    })

    assert "STEP_COMPLETE: Retrieved 71 unread Slack messages" in rendered
    assert "#altbanq-baobab" in rendered
    assert "Enhanced workflow processed:" not in rendered


def test_context_assembler_falls_back_when_no_workflow_details_present():
    """Non-workflow result payloads should keep using the existing
    message/summary_text fallback without any change in behavior."""
    rendered = AgentContextAssembler()._format_chain_context({
        "chain_agentTasks": [
            {
                "sequence": 0,
                "text": "Summarize the document",
                "status": "completed",
                "result": {"message": "Document summarized into three bullets."},
            }
        ]
    })

    assert "Document summarized into three bullets." in rendered


def test_context_assembler_returns_boilerplate_only_when_no_richer_candidate():
    """If every candidate is the prompt-echo boilerplate, fall back to it
    rather than dropping the result summary entirely."""
    rendered = AgentContextAssembler()._format_chain_context({
        "chain_agentTasks": [
            {
                "sequence": 0,
                "text": "Do the thing",
                "status": "completed",
                "result": {
                    "data": {
                        "message": "Enhanced workflow processed: Do the thing",
                    }
                },
            }
        ]
    })

    assert "Enhanced workflow processed: Do the thing" in rendered


def test_context_assembler_prefers_finalizer_summary_over_noisy_agent_output():
    """Real payload shape (agent task BE770EA9): finalizer_result.summary_text
    must win over a step-log-prefixed agent_output in the same result."""
    rendered = AgentContextAssembler()._format_chain_context({
        "chain_agentTasks": [
            {
                "sequence": 0,
                "text": "Do you have history access?",
                "status": "completed",
                "result": {
                    "data": {
                        "workflow_details": {
                            "results": [{
                                "agent_output": (
                                    "STEP_START: Using recall_agent_tasks tool\n"
                                    "STEP_COMPLETE: recall_agent_tasks completed successfully\n\n"
                                    "[raw tool observation noise]"
                                ),
                            }],
                        },
                    },
                    "finalizer_result": {
                        "summary_text": "Yes -- confirmed, and I just used it.",
                    },
                },
            }
        ]
    })

    assert "You: Yes -- confirmed, and I just used it." in rendered
    assert "STEP_START" not in rendered
    assert "STEP_COMPLETE" not in rendered


def test_step_log_stripper_leaves_unrelated_step_complete_prose_alone():
    """A lone line that happens to start with 'STEP_COMPLETE:' but has no
    preceding STEP_START (i.e. it's real prose, not telemetry) must survive."""
    assembler = AgentContextAssembler()
    text = "STEP_COMPLETE: Retrieved 71 unread Slack messages across 15 conversations."
    assert assembler._strip_step_log_lines(text) == text


def test_step_log_stripper_removes_paired_lines():
    assembler = AgentContextAssembler()
    text = (
        "STEP_START: Using shell_service_execute_command tool\n"
        "STEP_COMPLETE: Successfully created file 'a.py' at '/tmp/a.py'\n"
        "STEP_START: Using load_tool_family tool\n"
        "STEP_COMPLETE: load_tool_family completed successfully\n"
        "Here is the real answer."
    )
    assert assembler._strip_step_log_lines(text) == "Here is the real answer."


def test_context_assembler_renders_failed_turn_as_narrator_note():
    """Real payload shape (chain 8b342927...): a crash-interrupted follow-up
    must not be put in the assistant's voice."""
    rendered = AgentContextAssembler()._format_chain_context({
        "chain_agentTasks": [
            {
                "sequence": 1,
                "text": "Try now?",
                "status": "failed",
                "result": {
                    "failure_info": {
                        "error": "Task interrupted by application restart",
                        "previous_status": "processing",
                    },
                },
            }
        ]
    })

    assert "User: Try now?" in rendered
    assert "This attempt failed: Task interrupted by application restart" in rendered
    assert "You: Try now?" not in rendered


def test_context_assembler_renders_awaiting_user_input_turn():
    rendered = AgentContextAssembler()._format_chain_context({
        "chain_agentTasks": [
            {
                "sequence": 2,
                "text": "Clean up the folder",
                "status": "awaiting_user_input",
                "result": {"checkpoint_data": {"prompt": "Should I delete the .DS_Store files too?"}},
            }
        ]
    })

    assert "You asked: Should I delete the .DS_Store files too?" in rendered


def test_context_assembler_elides_turns_beyond_the_inline_cap():
    chain_agentTasks = [
        {"sequence": i, "text": f"Turn {i}", "status": "completed", "result": {"message": f"Done {i}"}}
        for i in range(15)
    ]
    rendered = AgentContextAssembler()._format_chain_context({"chain_agentTasks": chain_agentTasks})

    assert "3 earlier turns not shown" in rendered
    assert "recall_agent_tasks(scope='detail')" in rendered
    assert "Turn 0" not in rendered
    assert "Turn 14" in rendered


class FakeLlm:
    def __init__(self):
        self.prompt = ""

    async def generate_response(self, prompt, max_tokens=500):
        self.prompt = prompt
        return """
        {
            "interpreted_agent_task": "Make the previous report shorter",
            "interpretation_notes": ["Resolved previous report reference"],
            "success_criteria": ["Shortened report is produced"]
        }
        """


@pytest.mark.asyncio
async def test_request_analyzer_interpretation_is_disabled_no_op():
    """The blocking interpretation LLM call was removed from the critical path
    (2026-07-23): its output was never consumed downstream and it was a silent
    no-op ~76% of the time (see backend/scripts/analyzer_retrospective.py).

    analyze_request must therefore return the cheap metrics with interpretation
    at its no-op defaults, and must NOT invoke the model even when chain context
    is present.
    """
    llm = FakeLlm()
    analyzer = RequestAnalyzer(llm_model=llm)

    analysis = await analyzer.analyze_request(
        "make it shorter",
        {
            "chain_context": {
                "chain_agentTasks": [
                    {"sequence": 0, "text": "Create a report", "result": {"message": "Report created"}}
                ]
            }
        },
    )

    # Interpretation stays at its no-op defaults.
    assert analysis.interpreted_agent_task is None
    assert analysis.interpretation_applied is False
    assert analysis.interpretation_notes == []
    assert analysis.success_criteria == []
    # Cheap metrics are still produced.
    assert analysis.word_count == 3
    # The model was never called (no blocking round-trip on the critical path).
    assert llm.prompt == ""


@pytest.mark.asyncio
async def test_handle_discussion_followup_uses_shared_conversation_renderer():
    """Guards against the fast lane regressing to its own divergent,
    unfiltered User:/Assistant: extraction, and against the historical
    AttributeError bug (AgentTaskOrchestrator has no _llm_model)."""
    chain = [
        FakeAgentTask(
            task_id="root", text="Do you have history access?", sequence=0,
            result_data={
                "data": {
                    "workflow_details": {"results": [{"agent_output": "STEP_START: Using recall_agent_tasks tool\nSTEP_COMPLETE: recall_agent_tasks completed successfully\n\nnoise"}]},
                },
                "finalizer_result": {"summary_text": "Yes, confirmed."},
            },
        ),
    ]
    service = AgentTaskSubmissionService(
        agent_task_orchestrator=SimpleNamespace(websocket_manager=None),
        db_service=FakeDbService(chain),
    )
    service.db_service.store_agent_task = AsyncMock()
    service.db_service.update_agent_task_status = AsyncMock()
    service.broadcast = AsyncMock()

    captured_messages = {}

    class FakeModel:
        async def chat_completion(self, messages):
            captured_messages["value"] = messages
            return {"content": "ok"}

    service._resolve_fast_lane_model = AsyncMock(return_value=FakeModel())

    await service.handle_discussion_followup(
        "So can you use it right now?", root_task_id="root",
    )

    rendered = captured_messages["value"][1]["content"]
    assert "You: Yes, confirmed." in rendered
    assert "STEP_START" not in rendered


@pytest.mark.asyncio
async def test_handle_discussion_followup_includes_work_ledger_handoff_when_present():
    """The fast lane must surface the durable work ledger's handoff (written by
    full multi_step_workflow turns earlier in the same chain), not just the
    conversational chain history -- otherwise a discussion follow-up asking
    about verified/discovered state falls back to a prior turn's self-reported
    prose instead of the ledger's structured record (see the continuation plan's
    motivating failure mode: a claimed-but-unverified outcome)."""
    chain = [FakeAgentTask(task_id="root", text="Find my invoices", sequence=0)]
    service = AgentTaskSubmissionService(
        agent_task_orchestrator=SimpleNamespace(websocket_manager=None),
        db_service=FakeDbService(chain),
    )
    service.db_service.store_agent_task = AsyncMock()
    service.db_service.update_agent_task_status = AsyncMock()
    service.broadcast = AsyncMock()

    captured_messages = {}

    class FakeModel:
        async def chat_completion(self, messages):
            captured_messages["value"] = messages
            return {"content": "ok"}

    service._resolve_fast_lane_model = AsyncMock(return_value=FakeModel())

    fake_ledger_instance = SimpleNamespace(
        handoff=AsyncMock(return_value="3 invoices discovered; 1 receipt unverified."),
    )

    with patch(
        "api.services.agent_processing.lifecycle.runtime.agent_work_ledger_service.AgentWorkLedgerService",
        return_value=fake_ledger_instance,
    ):
        await service.handle_discussion_followup(
            "Did we verify all of those?", root_task_id="root",
        )

    rendered = captured_messages["value"][1]["content"]
    assert "===== WORK_LEDGER =====" in rendered
    assert "3 invoices discovered; 1 receipt unverified." in rendered
    # Ledger section must precede the conversational history, mirroring the
    # full pipeline's WORK LEDGER(priority 25) < FOLLOW UP CONTEXT(priority 30)
    # section ordering in agent_context_assembler.py.
    assert rendered.index("WORK_LEDGER") < rendered.index("Find my invoices")


@pytest.mark.asyncio
async def test_handle_discussion_followup_tolerates_work_ledger_failure():
    """A work-ledger lookup failure (e.g. no session repository wired up) must
    not break the fast lane -- it is a best-effort read, exactly like the full
    pipeline's own ensure_session/handoff try/except in
    agent_task_workflow_result_service.py."""
    chain = [FakeAgentTask(task_id="root", text="Find my invoices", sequence=0)]
    service = AgentTaskSubmissionService(
        agent_task_orchestrator=SimpleNamespace(websocket_manager=None),
        db_service=FakeDbService(chain),
    )
    service.db_service.store_agent_task = AsyncMock()
    service.db_service.update_agent_task_status = AsyncMock()
    service.broadcast = AsyncMock()

    captured_messages = {}

    class FakeModel:
        async def chat_completion(self, messages):
            captured_messages["value"] = messages
            return {"content": "ok"}

    service._resolve_fast_lane_model = AsyncMock(return_value=FakeModel())

    with patch(
        "api.services.agent_processing.lifecycle.runtime.agent_work_ledger_service.AgentWorkLedgerService",
        side_effect=RuntimeError("no repository configured"),
    ):
        result = await service.handle_discussion_followup(
            "Did we verify all of those?", root_task_id="root",
        )

    assert result["success"] is True
    rendered = captured_messages["value"][1]["content"]
    assert "WORK_LEDGER" not in rendered


@pytest.mark.asyncio
async def test_handle_discussion_followup_persists_success_outcome_on_the_happy_path():
    """The fast lane's finalizer_result.result_payload must carry `outcome`
    like the full pipeline's does (result_finalizer_tool.py's contract), so
    list/detail views that read `outcome` render consistently regardless of
    which lane answered the turn."""
    chain = [FakeAgentTask(task_id="root", text="Do you have history access?", sequence=0)]
    service = AgentTaskSubmissionService(
        agent_task_orchestrator=SimpleNamespace(websocket_manager=None),
        db_service=FakeDbService(chain),
    )
    service.db_service.store_agent_task = AsyncMock()
    service.db_service.update_agent_task_status = AsyncMock()
    service.broadcast = AsyncMock()

    class FakeModel:
        async def chat_completion(self, messages):
            return {"content": "Yes, confirmed."}

    service._resolve_fast_lane_model = AsyncMock(return_value=FakeModel())

    result = await service.handle_discussion_followup(
        "So can you use it right now?", root_task_id="root",
    )

    assert result["success"] is True
    persisted = service.db_service.update_agent_task_status.call_args.kwargs["result_data"]
    payload = persisted["finalizer_result"]["result_payload"]
    assert payload["outcome"] == "success"
    assert payload["outcome_reason"] is None
    broadcasted = service.broadcast.call_args.args[0]
    assert broadcasted["success"] is True


@pytest.mark.asyncio
async def test_handle_discussion_followup_persists_failure_outcome_when_generation_fails():
    """When no model is available (or generation otherwise produces no text),
    the fallback apology message must NOT be persisted/broadcast as a
    success -- callers reading `outcome`/`success` need to see the failure."""
    chain = [FakeAgentTask(task_id="root", text="Do you have history access?", sequence=0)]
    service = AgentTaskSubmissionService(
        agent_task_orchestrator=SimpleNamespace(websocket_manager=None),
        db_service=FakeDbService(chain),
    )
    service.db_service.store_agent_task = AsyncMock()
    service.db_service.update_agent_task_status = AsyncMock()
    service.broadcast = AsyncMock()
    service._resolve_fast_lane_model = AsyncMock(return_value=None)

    result = await service.handle_discussion_followup(
        "So can you use it right now?", root_task_id="root",
    )

    assert result["success"] is False
    assert "wasn't able to generate" in result["message"]
    persisted = service.db_service.update_agent_task_status.call_args.kwargs["result_data"]
    payload = persisted["finalizer_result"]["result_payload"]
    assert payload["outcome"] == "failure"
    assert payload["outcome_reason"]
    broadcasted = service.broadcast.call_args.args[0]
    assert broadcasted["success"] is False
