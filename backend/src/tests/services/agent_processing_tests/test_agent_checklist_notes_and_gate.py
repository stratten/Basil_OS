"""Working notes, the grounding check, and the capped completion gate for the task checklist."""

import json

import pytest
import pytest_asyncio

from api.core.knowledge.sqlite.sqlite_knowledge_service import SQLiteKnowledgeService
from api.services.agent_processing.lifecycle.execution_graph.agent_loop_checklist_gate import ChecklistGateMiddleware
from api.services.agent_processing.lifecycle.execution_graph.service_tooling.tool_family_catalog import CORE_TOOL_NAMES
from api.services.agent_processing.lifecycle.runtime.agent_checklist_gate import (
    GATE_FOOTER_MARKER,
    ChecklistCompletionGate,
    build_not_completed_footer,
    with_not_completed_footer,
)
from api.services.agent_processing.lifecycle.runtime.agent_checklist_notes_grounding import claimed_tool_outcomes
from api.services.agent_processing.tools.internal_basil_tools.checklist_notes_tool import create_checklist_notes_tool
from api.services.agent_processing.tools.internal_basil_tools.checklist_tool import create_checklist_tool

CONTEXT = {"agent_task_id": "root-1", "root_task_id": "root-1", "user_agent_task": "Inbox"}


@pytest_asyncio.fixture
async def wired(tmp_path, monkeypatch):
    service = SQLiteKnowledgeService(tmp_path / "knowledge.db")
    await service.store_agent_task(agent_task_id="root-1", original_prompt="Inbox", transcribed_prompt="Inbox", status="processing")
    monkeypatch.setattr("api.dependencies.get_sqlite_knowledge_service", lambda: service)

    async def capture(self, message):
        return None

    monkeypatch.setattr(
        "api.services.agent_processing.lifecycle.submission.agent_task_event_broadcaster.AgentTaskEventBroadcaster.broadcast", capture
    )
    monkeypatch.setattr("api.services.agent_processing.shared.get_current_agent_context", lambda: CONTEXT)
    return service


async def _call(tool, **arguments):
    return json.loads(await tool.ainvoke(arguments))


async def _add(**fields):
    return (await _call(create_checklist_tool(), action="add", **fields))["item"]


async def _record_receipt(service, method="send_email"):
    await service.agent_work_session_repository.get_or_create_root_session(root_task_id="root-1", goal="g", collection_type="agent_work")
    session = await service.agent_work_session_repository.get_latest_session_for_root("root-1")
    await service.agent_work_item_repository.add_items(session_id=session["id"], items=[{"external_id": "thread-3"}])
    captured = (await service.agent_work_item_repository.get_items(session_id=session["id"]))[0]
    await service.agent_work_receipt_repository.add_receipt(
        session_id=session["id"], item_id=captured["id"], agent_task_id="root-1", service="gmail_service", method=method,
        execution_state="succeeded", verification_status="verified", requested_effect={"material_write": True}, evidence={"message_id": "m-1"},
    )


def test_notes_tool_is_a_core_tool_with_a_slim_variant():
    class Slim:
        tool_rendering = "slim_schema"

    assert "checklist_notes" in CORE_TOOL_NAMES
    assert create_checklist_notes_tool().name == "checklist_notes"
    assert len(create_checklist_notes_tool(profile=Slim()).description) <= len(create_checklist_notes_tool().description)


@pytest.mark.asyncio
async def test_reading_empty_notes_creates_no_session(wired):
    result = await _call(create_checklist_notes_tool(), action="read")

    assert result["success"] and result["content"] == "" and result["revision"] == 0
    assert await wired.agent_work_session_repository.get_latest_session_for_root("root-1") is None


@pytest.mark.asyncio
async def test_append_and_edit_round_trip_with_revisions(wired):
    tool = create_checklist_notes_tool()

    first = await _call(tool, action="append", text="Clinic replies on Fridays.")
    second = await _call(tool, action="edit", find="Fridays", replace="Thursdays")
    read = await _call(tool, action="read")

    assert first["success"] and first["revision"] == 1
    assert second["success"] and second["revision"] == 2
    assert read["content"] == "Clinic replies on Thursdays." and read["characters_used"] == len(read["content"])


@pytest.mark.asyncio
async def test_edit_errors_are_corrections_not_exceptions(wired):
    tool = create_checklist_notes_tool()
    await _call(tool, action="append", text="alpha alpha")

    missing = await _call(tool, action="edit", find="beta", replace="x")
    duplicate = await _call(tool, action="edit", find="alpha", replace="x")
    no_find = await _call(tool, action="edit", replace="x")
    no_text = await _call(tool, action="append", text="  ")

    assert not missing["success"] and "not found" in missing["error"]
    assert not duplicate["success"] and "2 times" in duplicate["error"]
    assert not no_find["success"] and "find is required" in no_find["error"]
    assert not no_text["success"] and "text is required" in no_text["error"]


@pytest.mark.asyncio
async def test_over_limit_is_refused_and_near_limit_gets_a_hint(wired):
    tool = create_checklist_notes_tool()

    near = await _call(tool, action="append", text="n" * 3400)
    over = await _call(tool, action="append", text="m" * 700)

    assert near["success"] and "close to the limit" in near["hint"]
    assert not over["success"] and "ondense" in over["error"]
    assert (await _call(tool, action="read"))["characters_used"] == 3400


def test_only_tool_references_beside_an_outcome_word_count_as_claims():
    claims = claimed_tool_outcomes(
        "gmail_service.send_email was sent. Next I will call calendar_service_create_event.\n"
        "I emailed the clinic. The gmail_service_send_email call succeeded again."
    )

    assert claims == [("gmail_service", "send_email")]


@pytest.mark.asyncio
async def test_an_ungrounded_outcome_is_refused_and_a_grounded_one_is_allowed(wired):
    tool = create_checklist_notes_tool()

    refused = await _call(tool, action="append", text="gmail_service.send_email succeeded for the clinic.")
    plain = await _call(tool, action="append", text="Draft is ready, not sent.")
    await _record_receipt(wired)
    allowed = await _call(tool, action="append", text="gmail_service.send_email succeeded for the clinic.")
    other_method = await _call(tool, action="append", text="gmail_service.delete_message completed.")

    assert not refused["success"] and "gmail_service.send_email" in refused["error"]
    assert plain["success"] and allowed["success"]
    assert not other_method["success"] and "gmail_service.delete_message" in other_method["error"]


@pytest.mark.asyncio
async def test_gate_asks_for_work_twice_for_actionable_required_items_then_lets_go(wired):
    await _add(title="Book the visit", required=True)
    gate = ChecklistCompletionGate()

    first = await gate.review_final_answer(CONTEXT)
    second = await gate.review_final_answer(CONTEXT)
    third = await gate.review_final_answer(CONTEXT)

    assert first and "Book the visit" in first and "not started" in first
    assert second == first and third is None and gate.rejections == 2


@pytest.mark.asyncio
async def test_gate_ignores_optional_waiting_done_and_missing_checklists(wired):
    gate = ChecklistCompletionGate()
    assert await gate.review_final_answer(CONTEXT) is None
    assert await wired.agent_work_session_repository.get_latest_session_for_root("root-1") is None

    await _add(title="Optional thing")
    waiting = await _add(title="Needs the user", required=True)
    finished = await _add(title="Already done", required=True)
    await _call(create_checklist_tool(), action="update", item=waiting["id"], status="waiting_user", waiting_on="Pick a slot")
    await _call(create_checklist_tool(), action="update", item=finished["id"], status="done")

    assert await gate.review_final_answer(CONTEXT) is None and gate.rejections == 0


@pytest.mark.asyncio
async def test_footer_lists_every_open_required_item_including_waiting_ones(wired):
    await _add(title="Optional thing")
    await _add(title="Book the visit", required=True)
    waiting = await _add(title="Choose a time", required=True)
    await _call(create_checklist_tool(), action="update", item=waiting["id"], status="waiting_user", waiting_on="Pick a slot")

    text = await with_not_completed_footer("All sorted.", CONTEXT)
    again = await with_not_completed_footer(text, CONTEXT)

    assert text.startswith("All sorted.\n\n" + GATE_FOOTER_MARKER)
    assert "- Book the visit (not started)" in text and "- Choose a time (needs your input: Pick a slot)" in text
    assert "Optional thing" not in text and again == text


@pytest.mark.asyncio
async def test_footer_is_absent_without_open_required_items_and_never_fails_the_run(wired, monkeypatch):
    assert await with_not_completed_footer("Done.", CONTEXT) == "Done."
    await _add(title="Book the visit", required=True)

    def broken():
        raise RuntimeError("database offline")

    monkeypatch.setattr("api.dependencies.get_sqlite_knowledge_service", broken)

    assert await with_not_completed_footer("Done.", CONTEXT) == "Done."


def test_footer_caps_a_long_list():
    items = [{"id": f"{n:08d}", "title": f"Item {n}", "status": "pending"} for n in range(14)]

    footer = build_not_completed_footer(items)

    assert footer.count("\n- ") == 11 and footer.endswith("- and 4 more")


class _Flags:
    def __init__(self, terminal=False):
        self._terminal = terminal

    def terminal(self):
        return self._terminal


@pytest.mark.asyncio
async def test_middleware_jumps_back_to_the_model_only_for_a_final_answer(wired, monkeypatch):
    from langchain_core.messages import AIMessage

    monkeypatch.setattr(
        "api.services.agent_processing.lifecycle.execution_graph.agent_loop_checklist_gate.get_current_agent_context", lambda: CONTEXT
    )
    await _add(title="Book the visit", required=True)
    middleware = ChecklistGateMiddleware(_Flags())
    tool_turn = {"messages": [AIMessage(content="", tool_calls=[{"name": "x", "args": {}, "id": "1"}])]}
    final_turn = {"messages": [AIMessage(content="All done.")]}

    assert await middleware.aafter_model(tool_turn, None) is None
    outcome = await middleware.aafter_model(final_turn, None)
    stopped = await ChecklistGateMiddleware(_Flags(terminal=True)).aafter_model(final_turn, None)

    assert outcome["jump_to"] == "model" and "Book the visit" in outcome["messages"][0].content
    assert stopped is None


def test_finalizer_evidence_is_read_only_and_names_the_empty_case():
    from api.services.agent_processing.lifecycle.runtime.agent_checklist_evidence import build_checklist_evidence

    empty = build_checklist_evidence([], {"total": 0})

    assert "empty" in empty and "Do not change the outcome" in empty and "none of them were tracked" in empty


def test_finalizer_evidence_lists_states_and_caps_a_long_list():
    from api.services.agent_processing.lifecycle.runtime.agent_checklist_evidence import EVIDENCE_MAX_CHARS, build_checklist_evidence

    items = [{"id": f"{n:08d}", "title": "Reply to a very long subject " * 10, "status": "waiting_user", "required": n == 0, "waiting_on": "Approve the reply"} for n in range(60)]
    counts = {"total": 60, "done": 0, "waiting_user": 60, "waiting_external": 0, "required_open": 1}

    text = build_checklist_evidence(items, counts)

    assert "0 of 60 done, 60 waiting on the user" in text and "(required)" in text and "waiting on: Approve the reply" in text
    assert "more items" in text and text.rstrip().endswith("which are missing.") and len(text) <= EVIDENCE_MAX_CHARS


@pytest.mark.asyncio
async def test_finalizer_block_reads_the_chain_without_creating_a_session_and_never_raises(wired, monkeypatch):
    from api.services.agent_processing.lifecycle.runtime.agent_checklist_evidence import finalizer_checklist_block

    before = await finalizer_checklist_block(CONTEXT)
    await _add(title="Book the visit", required=True)
    done = await _add(title="Send the form")
    await _call(create_checklist_tool(), action="update", item=done["id"], status="done")
    after = await finalizer_checklist_block(CONTEXT)

    assert "empty" in before and "1 of 2 done" in after and "[pending] Book the visit (required)" in after and "[done] Send the form" in after

    def broken():
        raise RuntimeError("database offline")

    monkeypatch.setattr("api.dependencies.get_sqlite_knowledge_service", broken)
    assert await finalizer_checklist_block(CONTEXT) == ""


def test_the_evaluation_prompt_carries_the_checklist_evidence():
    from api.services.agent_processing.lifecycle.finalization.evaluation import build_evaluation_prompt
    from api.services.agent_processing.lifecycle.runtime.agent_checklist_evidence import build_checklist_evidence

    prompt = build_evaluation_prompt(
        original_prompt="Triage my five newest emails", self_assessment=None, full_agent_output="Five summaries.", max_output_chars=5000,
        steps=[], tool_error_history=None, evaluation_context=build_checklist_evidence([], {"total": 0}),
    )

    assert "TASK CHECKLIST (empty" in prompt and "FOLLOW-UP / CHAIN CONTEXT" in prompt
