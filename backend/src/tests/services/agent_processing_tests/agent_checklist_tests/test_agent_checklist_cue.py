"""The checklist cue and the empty-checklist review: a run that found a set of records is reminded once, then asked once more before it finishes."""

import pytest
import pytest_asyncio
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from api.core.knowledge.sqlite.sqlite_knowledge_service import SQLiteKnowledgeService
from api.services.agent_processing.lifecycle.execution_graph.agent_loop_checklist_gate import ChecklistGateMiddleware
from api.services.agent_processing.lifecycle.runtime.agent_checklist_gate import ChecklistCompletionGate
from api.services.agent_processing.lifecycle.runtime.agent_checklist_prompt import LEDGER_HINT_MIN_ITEMS
from api.services.agent_processing.lifecycle.runtime.agent_checklist_service import AgentChecklistService

CONTEXT = {"agent_task_id": "root-1", "root_task_id": "root-1", "user_agent_task": "Inbox"}


class _Flags:
    def __init__(self, terminal=False):
        self._terminal = terminal

    def terminal(self):
        return self._terminal


@pytest_asyncio.fixture
async def service(tmp_path, monkeypatch):
    knowledge = SQLiteKnowledgeService(tmp_path / "knowledge.db")
    await knowledge.store_agent_task(agent_task_id="root-1", original_prompt="Inbox", transcribed_prompt="Inbox", status="processing")
    monkeypatch.setattr("api.dependencies.get_sqlite_knowledge_service", lambda: knowledge)
    monkeypatch.setattr(
        "api.services.agent_processing.lifecycle.execution_graph.agent_loop_checklist_gate.get_current_agent_context", lambda: CONTEXT
    )

    async def capture(self, message):
        return None

    monkeypatch.setattr(
        "api.services.agent_processing.lifecycle.submission.agent_task_event_broadcaster.AgentTaskEventBroadcaster.broadcast", capture
    )
    return knowledge


async def _record(knowledge, count):
    await knowledge.agent_work_session_repository.get_or_create_root_session(root_task_id="root-1", goal="g", collection_type="agent_work")
    session = await knowledge.agent_work_session_repository.get_latest_session_for_root("root-1")
    await knowledge.agent_work_item_repository.add_items(session_id=session["id"], items=[{"external_id": f"thread-{n}"} for n in range(count)])
    return session


def _after_tool_result():
    return {"messages": [HumanMessage(content="go"), AIMessage(content="", tool_calls=[{"name": "x", "args": {}, "id": "1"}]), ToolMessage(content="ok", tool_call_id="1")]}


@pytest.mark.asyncio
async def test_no_cue_without_a_session_or_with_too_few_records(service):
    checklist = AgentChecklistService(service)
    assert await checklist.records_without_checklist(CONTEXT) is False
    assert await service.agent_work_session_repository.get_latest_session_for_root("root-1") is None

    await _record(service, LEDGER_HINT_MIN_ITEMS - 1)
    assert await checklist.records_without_checklist(CONTEXT) is False


@pytest.mark.asyncio
async def test_cue_is_sent_once_after_a_tool_result_when_records_exist_and_the_checklist_is_empty(service):
    await _record(service, LEDGER_HINT_MIN_ITEMS)
    middleware = ChecklistGateMiddleware(_Flags())

    first_model_call = await middleware.abefore_model({"messages": [HumanMessage(content="go")]}, None)
    after_tool = await middleware.abefore_model(_after_tool_result(), None)
    again = await middleware.abefore_model(_after_tool_result(), None)

    assert first_model_call is None
    assert after_tool and "checklist add" in after_tool["messages"][0].content
    assert again is None


@pytest.mark.asyncio
async def test_no_cue_once_the_checklist_has_an_item_or_the_run_is_over(service):
    session = await _record(service, LEDGER_HINT_MIN_ITEMS)
    assert await ChecklistGateMiddleware(_Flags(terminal=True)).abefore_model(_after_tool_result(), None) is None

    await service.agent_checklist_repository.add_item(session_id=session["id"], title="Reply to the first email", agent_task_id="root-1")

    assert await AgentChecklistService(service).records_without_checklist(CONTEXT) is False
    assert await ChecklistGateMiddleware(_Flags()).abefore_model(_after_tool_result(), None) is None


@pytest.mark.asyncio
async def test_a_cue_failure_never_stops_the_run(service, monkeypatch):
    async def broken(self, context, *, create):
        raise RuntimeError("database is locked")

    monkeypatch.setattr(AgentChecklistService, "session_for_context", broken)

    assert await AgentChecklistService(service).records_without_checklist(CONTEXT) is False
    assert await ChecklistGateMiddleware(_Flags()).abefore_model(_after_tool_result(), None) is None


@pytest.mark.asyncio
async def test_final_answer_is_sent_back_once_when_records_were_found_but_no_item_was_made(service):
    await _record(service, LEDGER_HINT_MIN_ITEMS)
    gate = ChecklistCompletionGate()

    first = await gate.review_final_answer(CONTEXT)
    second = await gate.review_final_answer(CONTEXT)

    assert first and "asked once" in first and "checklist add" in first
    assert second is None


@pytest.mark.asyncio
async def test_final_answer_is_not_sent_back_for_a_run_with_no_records_or_with_a_checklist(service):
    assert await ChecklistCompletionGate().review_final_answer(CONTEXT) is None

    session = await _record(service, LEDGER_HINT_MIN_ITEMS)
    await service.agent_checklist_repository.add_item(session_id=session["id"], title="Reply", agent_task_id="root-1")

    assert await ChecklistCompletionGate().review_final_answer(CONTEXT) is None
