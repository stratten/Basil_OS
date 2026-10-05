"""Work done before a checkpoint pause is saved and shown to the resumed run."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from api.core.knowledge.sqlite.sqlite_knowledge_service import SQLiteKnowledgeService
from api.services.agent_processing.lifecycle.planning.agent_context_assembler import AgentContextAssembler
from api.services.agent_processing.lifecycle.runtime.paused_work_digest import (
    MAX_PAUSED_WORK_STEPS,
    PAUSED_WORK_DIGEST_RESULT_KEY,
    PRIOR_PAUSED_WORK_CONTEXT_KEY,
    build_paused_work_digest,
    load_paused_work_digest,
    paused_work_digest_from_result_data,
)
from api.services.agent_processing.tools.internal_basil_tools.checkpoint_tool import CheckpointRequest


def _captured(tool: str, tool_input: dict, observation) -> dict:
    return {"tool": tool, "tool_input": tool_input, "observation": observation}


def test_digest_skips_control_tools_redacts_secrets_and_clips_results() -> None:
    context = {
        "captured_agent_tool_actions": [
            _captured("list_files", {"path": "/tmp/reports"}, "a.pdf\nb.pdf"),
            _captured("call_api", {"url": "https://example.com", "api_key": "sk-secret"}, "x" * 2000),
            _captured("request_user_input", {"prompt": "Which one?"}, "CheckpointRequest"),
            _captured("finalize_agent_task_result", {}, "done"),
        ]
    }

    digest = build_paused_work_digest(context)

    assert [step["tool"] for step in digest] == ["list_files", "call_api"]
    assert digest[0] == {"tool": "list_files", "input": '{"path": "/tmp/reports"}', "result": "a.pdf\nb.pdf"}
    assert "sk-secret" not in digest[1]["input"]
    assert "[redacted]" in digest[1]["input"]
    assert len(digest[1]["result"]) <= 600
    assert digest[1]["result"].endswith("[truncated]")


def test_digest_appends_to_prior_steps_and_keeps_the_most_recent() -> None:
    prior = [{"tool": f"prior_{index}", "input": "", "result": "ok"} for index in range(MAX_PAUSED_WORK_STEPS)]
    context = {"captured_agent_tool_actions": [_captured("read_file", {"path": "/tmp/a.txt"}, "hello")]}

    digest = build_paused_work_digest(context, prior=prior)

    assert len(digest) == MAX_PAUSED_WORK_STEPS
    assert digest[0]["tool"] == "prior_1"
    assert digest[-1]["tool"] == "read_file"


def test_digest_reads_back_from_result_data_and_ignores_malformed_values() -> None:
    stored = {PAUSED_WORK_DIGEST_RESULT_KEY: [{"tool": "read_file", "input": "{}", "result": "hello"}, "junk", {"tool": ""}]}

    assert paused_work_digest_from_result_data(stored) == [{"tool": "read_file", "input": "{}", "result": "hello"}]
    assert paused_work_digest_from_result_data("{not json") == []
    assert paused_work_digest_from_result_data(None) == []


def test_assembler_shows_work_before_pause_only_when_present() -> None:
    assembler = AgentContextAssembler()
    with_work = assembler.assemble(
        current_request="Continue",
        context={PRIOR_PAUSED_WORK_CONTEXT_KEY: [{"tool": "list_files", "input": '{"path": "/tmp"}', "result": "a.pdf"}]},
    )
    without_work = assembler.assemble(current_request="Continue", context={})

    assert "===== WORK_BEFORE_PAUSE =====" in with_work.user_input
    assert "1. list_files {\"path\": \"/tmp\"}" in with_work.user_input
    assert "Result: a.pdf" in with_work.user_input
    assert "WORK_BEFORE_PAUSE" not in without_work.user_input


@pytest.mark.asyncio
async def test_pause_saves_the_digest_and_resume_can_load_it(monkeypatch, tmp_path) -> None:
    from api.services.agent_processing.lifecycle.finalization import task_state_persistence
    import api.dependencies as dependencies

    service = SQLiteKnowledgeService(tmp_path / "pause.sqlite3")
    await service.store_agent_task(
        agent_task_id="task-pause",
        original_prompt="Summarize the reports",
        transcribed_prompt="Summarize the reports",
        status="processing",
    )
    monkeypatch.setattr(dependencies, "get_sqlite_knowledge_service", lambda: service)
    state = SimpleNamespace(
        context={
            "agent_task_id": "task-pause",
            "captured_agent_tool_actions": [
                _captured("list_files", {"path": "/tmp/reports"}, "a.pdf\nb.pdf"),
                _captured("request_user_input", {"prompt": "Which report?"}, "CheckpointRequest"),
            ],
        },
        user_agent_task="Summarize the reports",
        available_tools=None,
    )

    await task_state_persistence.handle_checkpoint_request(
        CheckpointRequest({"prompt": "Which report?", "input_type": "text"}),
        state,
        SimpleNamespace(_websocket_manager=None),
    )

    refreshed = await service.get_agent_task("task-pause")
    assert refreshed.status == "awaiting_user_input"
    expected = [{"tool": "list_files", "input": '{"path": "/tmp/reports"}', "result": "a.pdf\nb.pdf"}]
    assert refreshed.result_data[PAUSED_WORK_DIGEST_RESULT_KEY] == expected
    assert await load_paused_work_digest(service, "task-pause") == expected
