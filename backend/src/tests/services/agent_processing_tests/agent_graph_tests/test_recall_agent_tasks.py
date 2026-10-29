"""Tests for recall_agent_tasks tool (agent-task chain/history recall)."""

from __future__ import annotations

import json
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from api.services.agent_processing.tools.internal_basil_tools.recall.recall_tools import (
    create_recall_tools,
)


def _finalizer_result_data(message, files=None):
    """Canonical finalizer-envelope shape as persisted for a completed task.

    Mirrors what api/routes/agent_tasks/utils.py::extract_result_data reads:
    result_data["finalizer_result"]["result_payload"] holding the message and
    the files list. This is the real storage shape, NOT result_data["files"].
    """
    payload = {"message": message, "outcome": "success"}
    if files is not None:
        payload["files"] = files
    return {"finalizer_result": {"result_payload": payload}}


def _make_chain_tasks():
    return [
        SimpleNamespace(
            id="root-1",
            chain_sequence_number=0,
            timestamp=datetime(2026, 7, 20, 10, 0, 0),
            title="Find best candidate",
            original_prompt="Find the best example doc in Drive",
            status="completed",
            result_data=_finalizer_result_data(
                "Identified best_candidate.docx as the top pick.",
                files=[{"name": "best_candidate.docx", "full_path": "/Users/me/Drive/best_candidate.docx", "operation": "read"}],
            ),
            accumulated_artifacts=None,
            execution_timeline=None,
        ),
        SimpleNamespace(
            id="child-1",
            chain_sequence_number=1,
            timestamp=datetime(2026, 7, 20, 10, 5, 0),
            title="Copy to Downloads",
            original_prompt="Copy that file to Downloads",
            status="completed",
            result_data=_finalizer_result_data("Copied best_candidate.docx to Downloads."),
            accumulated_artifacts=None,
            execution_timeline=None,
        ),
    ]


def _five_turn_chain():
    return [
        SimpleNamespace(
            id=f"turn-{i}",
            chain_sequence_number=i,
            timestamp=datetime(2026, 7, 20, 10, i, 0),
            title=f"Turn {i}",
            original_prompt=f"Prompt {i}",
            status="completed",
            result_data=_finalizer_result_data(f"Result {i}"),
            accumulated_artifacts=None,
            execution_timeline=None,
        )
        for i in range(5)
    ]


class FakeAgentTaskService:
    def __init__(self):
        self.last_search: dict | None = None

    async def search_agent_task_summaries(
        self,
        query=None,
        start_date=None,
        end_date=None,
        status=None,
        app_name=None,
        limit=50,
        offset=0,
    ):
        self.last_search = {
            "query": query,
            "start_date": start_date,
            "end_date": end_date,
            "limit": limit,
        }
        return [
            {
                "id": "hist-1",
                "original_prompt": "Write a proposal for the client",
                "title": "Client proposal",
                "result_preview": "Draft proposal completed.",
                "timestamp": datetime(2026, 7, 19, 14, 0, 0),
                "status": "completed",
                "file_count": 1,
                "follow_up_count": 0,
            }
        ]


class FakeKnowledgeService:
    def __init__(self, chain_tasks=None):
        self.agent_task_service = FakeAgentTaskService()
        self._chain_tasks = chain_tasks if chain_tasks is not None else _make_chain_tasks()
        self.last_chain_root: str | None = None
        self._by_id = {task.id: task for task in self._chain_tasks}

    async def get_agent_task_chain(self, root_task_id: str):
        self.last_chain_root = root_task_id
        return list(self._chain_tasks)

    async def get_agent_task(self, task_id: str):
        return self._by_id.get(task_id)


@pytest.mark.asyncio
async def test_recall_current_chain_returns_prior_turns_with_files():
    fake = FakeKnowledgeService()
    tools = create_recall_tools(root_task_id="root-1")
    assert len(tools) == 1
    assert tools[0].name == "recall_agent_tasks"

    with patch("api.dependencies.get_sqlite_knowledge_service", return_value=fake):
        raw = await tools[0].ainvoke({})
    payload = json.loads(raw)

    assert payload["success"] is True
    assert payload["scope"] == "current_chain"
    assert payload["root_task_id"] == "root-1"
    assert payload["count"] == 2
    assert fake.last_chain_root == "root-1"
    first_turn = payload["results"][0]
    assert first_turn["chain_sequence_number"] == 0
    assert "/Users/me/Drive/best_candidate.docx" in first_turn["files"]
    # The clean finalizer message is surfaced, not a JSON dump of the envelope.
    assert first_turn["result"] == "Identified best_candidate.docx as the top pick."
    assert "finalizer_result" not in first_turn["result"]


@pytest.mark.asyncio
async def test_closure_captured_root_takes_precedence_over_param():
    fake = FakeKnowledgeService()
    tools = create_recall_tools(root_task_id="root-1")

    with patch("api.dependencies.get_sqlite_knowledge_service", return_value=fake):
        raw = await tools[0].ainvoke({"root_task_id": "other-root"})
    payload = json.loads(raw)

    assert payload["success"] is True
    assert payload["root_task_id"] == "root-1"
    assert fake.last_chain_root == "root-1"


@pytest.mark.asyncio
async def test_param_root_used_when_closure_absent():
    fake = FakeKnowledgeService()
    tools = create_recall_tools(root_task_id=None)

    with patch("api.dependencies.get_sqlite_knowledge_service", return_value=fake):
        raw = await tools[0].ainvoke({"root_task_id": "root-1"})
    payload = json.loads(raw)

    assert payload["success"] is True
    assert payload["root_task_id"] == "root-1"


@pytest.mark.asyncio
async def test_current_chain_without_root_returns_error():
    tools = create_recall_tools(root_task_id=None)
    raw = await tools[0].ainvoke({})
    payload = json.loads(raw)

    assert payload["success"] is False
    assert payload["scope"] == "current_chain"
    assert "No current task chain" in payload["error"]


@pytest.mark.asyncio
async def test_history_search_passes_parsed_dates_and_returns_results():
    fake = FakeKnowledgeService()
    tools = create_recall_tools(root_task_id="root-1")

    with patch("api.dependencies.get_sqlite_knowledge_service", return_value=fake):
        raw = await tools[0].ainvoke({
            "scope": "history",
            "query": "proposal",
            "start_time": "yesterday",
        })
    payload = json.loads(raw)

    assert payload["success"] is True
    assert payload["scope"] == "history"
    assert payload["count"] == 1
    assert fake.agent_task_service.last_search is not None
    assert fake.agent_task_service.last_search["query"] == "proposal"
    assert fake.agent_task_service.last_search["start_date"] is not None
    assert hasattr(fake.agent_task_service.last_search["start_date"], "isoformat")
    assert payload["results"][0]["title"] == "Client proposal"


@pytest.mark.asyncio
async def test_limit_clamped_to_100_on_history():
    fake = FakeKnowledgeService()
    tools = create_recall_tools(root_task_id="root-1")

    with patch("api.dependencies.get_sqlite_knowledge_service", return_value=fake):
        await tools[0].ainvoke({"scope": "history", "limit": 500})

    assert fake.agent_task_service.last_search["limit"] == 100


@pytest.mark.asyncio
async def test_limit_keeps_most_recent_chain_turns():
    fake = FakeKnowledgeService(chain_tasks=_five_turn_chain())
    tools = create_recall_tools(root_task_id="root-1")

    with patch("api.dependencies.get_sqlite_knowledge_service", return_value=fake):
        raw = await tools[0].ainvoke({"limit": 2})
    payload = json.loads(raw)

    assert payload["count"] == 2
    assert payload["results"][0]["id"] == "turn-3"
    assert payload["results"][1]["id"] == "turn-4"


def _long_result(prefix: str, total_len: int = 2500) -> str:
    filler = "x" * max(0, total_len - len(prefix))
    return prefix + filler


@pytest.mark.asyncio
async def test_current_chain_marks_long_results_truncated():
    long_message = _long_result("The best fit document is Crown Care NY. ")
    chain_tasks = [
        SimpleNamespace(
            id="root-long",
            chain_sequence_number=0,
            timestamp=datetime(2026, 7, 20, 10, 0, 0),
            title="Pick best doc",
            original_prompt="Find the best document",
            status="completed",
            result_data=_finalizer_result_data(long_message),
            accumulated_artifacts=None,
            execution_timeline=None,
        ),
    ]
    fake = FakeKnowledgeService(chain_tasks=chain_tasks)
    tools = create_recall_tools(root_task_id="root-long")

    with patch("api.dependencies.get_sqlite_knowledge_service", return_value=fake):
        raw = await tools[0].ainvoke({})
    payload = json.loads(raw)

    first_turn = payload["results"][0]
    assert first_turn["result_truncated"] is True
    assert first_turn["result"].endswith("\u2026")
    assert len(first_turn["result"]) <= 2000


@pytest.mark.asyncio
async def test_detail_scope_returns_full_result_and_files():
    # Deliberately far larger than any list-view budget to prove detail never
    # truncates the result -- this is the lossless escape hatch.
    long_message = _long_result("The best fit document is Crown Care NY. ", total_len=12000)
    chain_tasks = [
        SimpleNamespace(
            id="root-detail",
            chain_sequence_number=0,
            timestamp=datetime(2026, 7, 20, 10, 0, 0),
            title="Pick best doc",
            original_prompt="Find the best document",
            status="completed",
            result_data=_finalizer_result_data(
                long_message,
                files=[{"name": "Crown Care NY.docx", "full_path": "/Users/me/Drive/Crown Care NY.docx", "operation": "read"}],
            ),
            accumulated_artifacts=None,
            execution_timeline=None,
            root_task_id="root-detail",
            previous_task_id=None,
        ),
    ]
    fake = FakeKnowledgeService(chain_tasks=chain_tasks)
    tools = create_recall_tools(root_task_id="root-detail")

    with patch("api.dependencies.get_sqlite_knowledge_service", return_value=fake):
        raw = await tools[0].ainvoke({"scope": "detail", "task_id": "root-detail"})
    payload = json.loads(raw)

    assert payload["success"] is True
    assert payload["scope"] == "detail"
    # Full, untruncated result -- no ellipsis, exact length preserved.
    assert payload["task"]["result"] == long_message
    assert not payload["task"]["result"].endswith("\u2026")
    assert "/Users/me/Drive/Crown Care NY.docx" in payload["task"]["files"]
    assert payload["task"]["files_truncated"] is False
    assert payload["task"]["total_file_count"] == 1


@pytest.mark.asyncio
async def test_detail_scope_flags_and_counts_truncated_files():
    many_files = [
        {"name": f"doc_{i}.docx", "full_path": f"/Users/me/Drive/doc_{i}.docx", "operation": "read"}
        for i in range(50)
    ]
    chain_tasks = [
        SimpleNamespace(
            id="root-files",
            chain_sequence_number=0,
            timestamp=datetime(2026, 7, 20, 10, 0, 0),
            title="Touch many files",
            original_prompt="Process the whole folder",
            status="completed",
            result_data=_finalizer_result_data("Processed 50 files.", files=many_files),
            accumulated_artifacts=None,
            execution_timeline=None,
            root_task_id="root-files",
            previous_task_id=None,
        ),
    ]
    fake = FakeKnowledgeService(chain_tasks=chain_tasks)
    tools = create_recall_tools(root_task_id="root-files")

    with patch("api.dependencies.get_sqlite_knowledge_service", return_value=fake):
        raw = await tools[0].ainvoke({"scope": "detail", "task_id": "root-files"})
    payload = json.loads(raw)

    task = payload["task"]
    assert task["files_truncated"] is True
    assert task["total_file_count"] == 50
    assert len(task["files"]) == 40


@pytest.mark.asyncio
async def test_detail_scope_without_task_id_returns_error():
    tools = create_recall_tools(root_task_id="root-1")
    raw = await tools[0].ainvoke({"scope": "detail"})
    payload = json.loads(raw)

    assert payload["success"] is False
    assert payload["scope"] == "detail"
    assert "task_id" in payload["error"]


@pytest.mark.asyncio
async def test_detail_scope_unknown_task_id_returns_error():
    fake = FakeKnowledgeService()
    tools = create_recall_tools(root_task_id="root-1")

    with patch("api.dependencies.get_sqlite_knowledge_service", return_value=fake):
        raw = await tools[0].ainvoke({"scope": "detail", "task_id": "missing-id"})
    payload = json.loads(raw)

    assert payload["success"] is False
    assert payload["scope"] == "detail"
    assert "missing-id" in payload["error"]


def _timeline_task(task_id: str, timeline, status: str = "completed"):
    return SimpleNamespace(
        id=task_id,
        chain_sequence_number=0,
        timestamp=datetime(2026, 9, 15, 12, 58, 37),
        title="Client Update Summary Draft",
        original_prompt="Draft the client update",
        status=status,
        result_data=None,
        accumulated_artifacts=None,
        execution_timeline=timeline,
        root_task_id=task_id,
        previous_task_id=None,
    )


def _draft_transcript_timeline(reply_body: str):
    """Mirror the real execution_timeline shape: a tool_input carrying the
    composed body plus a paired tool_result, matched by correlation_id."""
    return [
        {
            "detail_kind": "tool_input",
            "correlation_id": "dynamic_load",
            "timestamp": "2026-09-15T12:59:00",
            "metadata": {"tool_name": "load_tool_family"},
            "body": '{\n  "family_names": ["email"]\n}',
        },
        {
            "detail_kind": "tool_result",
            "correlation_id": "dynamic_load",
            "timestamp": "2026-09-15T12:59:01",
            "metadata": {},
            "body": '{"success": true, "loaded_families": ["email"]}',
        },
        {
            "detail_kind": "tool_input",
            "correlation_id": "dynamic_draft",
            "timestamp": "2026-09-15T13:05:00",
            "metadata": {"tool_name": "email_service_create_reply_email_draft"},
            "body": json.dumps({"reference_email_id": "271526", "reply_body": reply_body}),
        },
        {
            "detail_kind": "tool_result",
            "correlation_id": "dynamic_draft",
            "timestamp": "2026-09-15T13:05:50",
            "metadata": {},
            "content": '{"success": true, "result": true}',
        },
    ]


@pytest.mark.asyncio
async def test_transcript_scope_lists_paired_tool_calls():
    reply_body = "Isaac and David,\n\n" + _long_result("Following up from our call. ", total_len=1500)
    task = _timeline_task("root-tx", _draft_transcript_timeline(reply_body), status="failed")
    fake = FakeKnowledgeService(chain_tasks=[task])
    tools = create_recall_tools(root_task_id="root-tx")

    with patch("api.dependencies.get_sqlite_knowledge_service", return_value=fake):
        raw = await tools[0].ainvoke({"scope": "transcript", "task_id": "root-tx"})
    payload = json.loads(raw)

    assert payload["success"] is True
    assert payload["scope"] == "transcript"
    assert payload["total_entries"] == 2
    assert payload["has_more"] is False
    entries = payload["entries"]
    assert entries[0]["tool_name"] == "load_tool_family"
    draft_entry = entries[1]
    assert draft_entry["tool_name"] == "email_service_create_reply_email_draft"
    # The paired result is attached to the same entry, not a separate one.
    assert '"success": true' in draft_entry["result"]
    # The composed body is long, so the list view previews and flags it.
    assert draft_entry["arguments_truncated"] is True
    assert len(draft_entry["arguments"]) <= 300


@pytest.mark.asyncio
async def test_transcript_scope_without_task_id_returns_error():
    tools = create_recall_tools(root_task_id="root-1")
    raw = await tools[0].ainvoke({"scope": "transcript"})
    payload = json.loads(raw)

    assert payload["success"] is False
    assert payload["scope"] == "transcript"
    assert "task_id" in payload["error"]


@pytest.mark.asyncio
async def test_transcript_scope_unknown_task_id_returns_error():
    fake = FakeKnowledgeService()
    tools = create_recall_tools(root_task_id="root-1")

    with patch("api.dependencies.get_sqlite_knowledge_service", return_value=fake):
        raw = await tools[0].ainvoke({"scope": "transcript", "task_id": "missing-id"})
    payload = json.loads(raw)

    assert payload["success"] is False
    assert payload["scope"] == "transcript"
    assert "missing-id" in payload["error"]


@pytest.mark.asyncio
async def test_transcript_pagination_offset_and_has_more():
    task = _timeline_task("root-tx4", _draft_transcript_timeline("short body"))
    fake = FakeKnowledgeService(chain_tasks=[task])
    tools = create_recall_tools(root_task_id="root-tx4")

    with patch("api.dependencies.get_sqlite_knowledge_service", return_value=fake):
        raw = await tools[0].ainvoke({"scope": "transcript", "task_id": "root-tx4", "limit": 1, "offset": 0})
    payload = json.loads(raw)

    assert payload["total_entries"] == 2
    assert payload["returned"] == 1
    assert payload["offset"] == 0
    assert payload["has_more"] is True
    assert payload["entries"][0]["tool_name"] == "load_tool_family"


def _full_content_task(task_id: str, full_content: str, status: str = "failed"):
    return SimpleNamespace(
        id=task_id,
        chain_sequence_number=0,
        timestamp=datetime(2026, 9, 15, 12, 58, 37),
        title="Client Update Summary Draft",
        original_prompt="Draft the client update",
        status=status,
        result_data={"full_content": full_content},
        accumulated_artifacts=None,
        execution_timeline=None,
        root_task_id=task_id,
        previous_task_id=None,
    )


@pytest.mark.asyncio
async def test_transcript_text_contains_returns_full_body():
    # Natural-language filler (not a homogeneous base64-charset run) so the
    # denoiser's signature-blob collapse does not itself eat the test body.
    filler = "the detailed research paragraph keeps going on and on here " * 40
    reply_body = "Following up from our call. " + filler + " Best,\nStratten"
    full_content = (
        "STEP_START: Using recall_agent_tasks tool\n"
        "STEP_COMPLETE: recall_agent_tasks completed successfully\n"
        f"Invoking: `email_service_create_reply_email_draft` with `{{'reply_body': '{reply_body}'}}`\n"
    )
    task = _full_content_task("root-text1", full_content)
    fake = FakeKnowledgeService(chain_tasks=[task])
    tools = create_recall_tools(root_task_id="root-text1")

    with patch("api.dependencies.get_sqlite_knowledge_service", return_value=fake):
        raw = await tools[0].ainvoke({
            "scope": "transcript_text",
            "task_id": "root-text1",
            "contains": "Following up from our call",
        })
    payload = json.loads(raw)

    assert payload["success"] is True
    assert payload["scope"] == "transcript_text"
    assert payload["available"] is True
    assert payload["match_count"] == 1
    # The full composed body, including its closing signoff, is present in one window.
    assert "Best," in payload["text"] and "Stratten" in payload["text"]
    assert filler in payload["text"]


@pytest.mark.asyncio
async def test_transcript_text_denoises_step_and_signature():
    base64_blob = "A" * 250
    full_content = (
        "STEP_START: Using email_service tool\n"
        "STEP_COMPLETE: email_service completed successfully\n"
        f"'signature': '{base64_blob}'\n"
        "Some real composed prose here."
    )
    task = _full_content_task("root-text2", full_content)
    fake = FakeKnowledgeService(chain_tasks=[task])
    tools = create_recall_tools(root_task_id="root-text2")

    with patch("api.dependencies.get_sqlite_knowledge_service", return_value=fake):
        raw = await tools[0].ainvoke({"scope": "transcript_text", "task_id": "root-text2"})
    payload = json.loads(raw)

    assert "STEP_START" not in payload["text"]
    assert "STEP_COMPLETE" not in payload["text"]
    assert base64_blob not in payload["text"]
    assert "[omitted 250-char blob]" in payload["text"]
    assert "Some real composed prose here." in payload["text"]


@pytest.mark.asyncio
async def test_transcript_text_redacts_secrets():
    full_content = 'Invoking: `http_request` with `{"api_key": "sk-live-123456"}`\nDone.'
    task = _full_content_task("root-text3", full_content)
    fake = FakeKnowledgeService(chain_tasks=[task])
    tools = create_recall_tools(root_task_id="root-text3")

    with patch("api.dependencies.get_sqlite_knowledge_service", return_value=fake):
        raw = await tools[0].ainvoke({"scope": "transcript_text", "task_id": "root-text3"})
    payload = json.loads(raw)

    assert "sk-live-123456" not in payload["text"]
    assert "[redacted]" in payload["text"]


@pytest.mark.asyncio
async def test_transcript_text_paginates():
    # Natural-language filler, not a homogeneous base64-charset run (see note
    # on test_transcript_text_contains_returns_full_body above).
    filler = "padding text keeps the log long enough to require pagination here now " * 100
    full_content = filler + "MARKER_END"
    task = _full_content_task("root-text4", full_content)
    fake = FakeKnowledgeService(chain_tasks=[task])
    tools = create_recall_tools(root_task_id="root-text4")

    with patch("api.dependencies.get_sqlite_knowledge_service", return_value=fake):
        raw_first = await tools[0].ainvoke({"scope": "transcript_text", "task_id": "root-text4", "offset": 0})
    first = json.loads(raw_first)
    assert first["has_more"] is True
    assert "MARKER_END" not in first["text"]

    with patch("api.dependencies.get_sqlite_knowledge_service", return_value=fake):
        raw_next = await tools[0].ainvoke({
            "scope": "transcript_text",
            "task_id": "root-text4",
            "offset": first["offset"] + first["returned"],
        })
    second = json.loads(raw_next)
    assert second["has_more"] is False
    assert "MARKER_END" in second["text"]


@pytest.mark.asyncio
async def test_transcript_text_missing_content_graceful():
    task = SimpleNamespace(
        id="root-text5",
        chain_sequence_number=0,
        timestamp=datetime(2026, 9, 15, 12, 58, 37),
        title="Untitled",
        original_prompt="Do something",
        status="failed",
        result_data=None,
        accumulated_artifacts=None,
        execution_timeline=None,
        root_task_id="root-text5",
        previous_task_id=None,
    )
    fake = FakeKnowledgeService(chain_tasks=[task])
    tools = create_recall_tools(root_task_id="root-text5")

    with patch("api.dependencies.get_sqlite_knowledge_service", return_value=fake):
        raw = await tools[0].ainvoke({"scope": "transcript_text", "task_id": "root-text5"})
    payload = json.loads(raw)

    assert payload["success"] is True
    assert payload["available"] is False
    assert payload["total_length"] == 0
    assert "note" in payload


@pytest.mark.asyncio
async def test_transcript_text_requires_task_id():
    tools = create_recall_tools(root_task_id="root-1")
    raw = await tools[0].ainvoke({"scope": "transcript_text"})
    payload = json.loads(raw)

    assert payload["success"] is False
    assert payload["scope"] == "transcript_text"
    assert "task_id" in payload["error"]


@pytest.mark.asyncio
async def test_transcript_text_unknown_task_id():
    fake = FakeKnowledgeService()
    tools = create_recall_tools(root_task_id="root-1")

    with patch("api.dependencies.get_sqlite_knowledge_service", return_value=fake):
        raw = await tools[0].ainvoke({"scope": "transcript_text", "task_id": "missing-id"})
    payload = json.loads(raw)

    assert payload["success"] is False
    assert payload["scope"] == "transcript_text"
    assert "missing-id" in payload["error"]


def _reasoning_task(task_id: str, thinking_history):
    return SimpleNamespace(
        id=task_id,
        chain_sequence_number=0,
        timestamp=datetime(2026, 9, 15, 12, 58, 37),
        title="Reasoning trace task",
        original_prompt="Explain the decision",
        status="completed",
        result_data={"thinking_history": thinking_history},
        accumulated_artifacts=None,
        execution_timeline=None,
        root_task_id=task_id,
        previous_task_id=None,
    )


@pytest.mark.asyncio
async def test_reasoning_scope_paginates_filters_and_redacts():
    task = _reasoning_task(
        "reasoning-1",
        [
            {"iteration": 1, "text": "Review the report first.", "is_complete": True},
            {"iteration": 2, "text": 'Use api_key="secret-token" for the request.', "is_complete": True},
            {"iteration": 3, "text": "Explain the final decision.", "is_complete": True},
        ],
    )
    fake = FakeKnowledgeService(chain_tasks=[task])
    tools = create_recall_tools(root_task_id="reasoning-1")

    with patch("api.dependencies.get_sqlite_knowledge_service", return_value=fake):
        raw = await tools[0].ainvoke({"scope": "reasoning", "task_id": "reasoning-1", "limit": 2, "offset": 1})
    payload = json.loads(raw)

    assert payload["success"] is True
    assert payload["scope"] == "reasoning"
    assert payload["total_segments"] == 3
    assert payload["returned"] == 2
    assert payload["has_more"] is False
    assert [segment["iteration"] for segment in payload["segments"]] == [2, 3]
    assert "secret-token" not in payload["segments"][0]["text"]
    assert "[redacted]" in payload["segments"][0]["text"]

    with patch("api.dependencies.get_sqlite_knowledge_service", return_value=fake):
        filtered_raw = await tools[0].ainvoke({
            "scope": "reasoning",
            "task_id": "reasoning-1",
            "contains": "FINAL DECISION",
        })
    filtered = json.loads(filtered_raw)
    assert filtered["total_segments"] == 1
    assert filtered["segments"][0]["iteration"] == 3


@pytest.mark.asyncio
async def test_reasoning_scope_handles_missing_trace_and_task_without_leaking_it_elsewhere():
    traced = _reasoning_task(
        "reasoning-present",
        [{"iteration": 1, "text": "Only the reasoning scope can return this.", "is_complete": True}],
    )
    missing = _reasoning_task("reasoning-empty", [])
    fake = FakeKnowledgeService(chain_tasks=[traced, missing])
    tools = create_recall_tools(root_task_id="reasoning-present")

    with patch("api.dependencies.get_sqlite_knowledge_service", return_value=fake):
        empty_raw = await tools[0].ainvoke({"scope": "reasoning", "task_id": "reasoning-empty"})
        detail_raw = await tools[0].ainvoke({"scope": "detail", "task_id": "reasoning-present"})
        chain_raw = await tools[0].ainvoke({"scope": "current_chain"})
        missing_raw = await tools[0].ainvoke({"scope": "reasoning", "task_id": "does-not-exist"})

    assert json.loads(empty_raw)["total_segments"] == 0
    assert "thinking_history" not in json.loads(detail_raw)["task"]
    assert "Only the reasoning scope" not in chain_raw
    missing_payload = json.loads(missing_raw)
    assert missing_payload["success"] is False
    assert missing_payload["scope"] == "reasoning"


@pytest.mark.asyncio
async def test_screen_scope_returns_ready_text_for_current_task():
    task = SimpleNamespace(
        id="cur-1",
        app_name="Mail",
        window_title="Re: Q3 contract",
        screen_text="From: alice@example.com\nSubject: Re: Q3 contract\nBody...",
        chain_sequence_number=0,
        timestamp=datetime(2026, 7, 20, 10, 0, 0),
        title="Reply",
        original_prompt="Draft a reply to this email",
        status="routing",
        result_data=None,
        accumulated_artifacts=None,
        execution_timeline=None,
    )
    fake = FakeKnowledgeService(chain_tasks=[task])
    tools = create_recall_tools(current_agent_task_id="cur-1")

    with patch("api.dependencies.get_sqlite_knowledge_service", return_value=fake):
        raw = await tools[0].ainvoke({"scope": "screen"})
    payload = json.loads(raw)

    assert payload["success"] is True
    assert payload["scope"] == "screen"
    assert payload["screen"]["screen_text_status"] == "ready"
    assert "alice@example.com" in payload["screen"]["screen_text"]
    assert payload["screen"]["app_name"] == "Mail"


@pytest.mark.asyncio
async def test_screen_scope_pending_when_capture_not_finished():
    task = SimpleNamespace(
        id="cur-2",
        app_name=None,
        window_title=None,
        screen_text=None,  # NULL => background OCR has not written yet
        chain_sequence_number=0,
        timestamp=datetime(2026, 7, 20, 10, 0, 0),
        title="Reply",
        original_prompt="Draft a reply to this email",
        status="routing",
        result_data=None,
        accumulated_artifacts=None,
        execution_timeline=None,
    )
    fake = FakeKnowledgeService(chain_tasks=[task])
    tools = create_recall_tools(current_agent_task_id="cur-2")

    with patch("api.dependencies.get_sqlite_knowledge_service", return_value=fake):
        raw = await tools[0].ainvoke({"scope": "screen"})
    payload = json.loads(raw)

    assert payload["success"] is True
    assert payload["screen"]["screen_text_status"] == "pending"
    assert payload["screen"]["screen_text"] == ""


@pytest.mark.asyncio
async def test_screen_scope_errors_without_current_task_id():
    fake = FakeKnowledgeService()
    tools = create_recall_tools()  # no current_agent_task_id captured

    with patch("api.dependencies.get_sqlite_knowledge_service", return_value=fake):
        raw = await tools[0].ainvoke({"scope": "screen"})
    payload = json.loads(raw)

    assert payload["success"] is False
    assert payload["scope"] == "screen"
