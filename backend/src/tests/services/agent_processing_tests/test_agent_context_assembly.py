"""Tests for follow-up context assembly and trimming robustness.

Covers the fixes for the "agent lost context in a follow-up" issue:
- trim_oldest_context now searches using the same underscored marker format
  ContextSection.render() actually produces (e.g. "FOLLOW_UP_CONTEXT"), not
  the raw space-separated section name. Previously every section search
  missed, silently falling through to the crude "wipe everything before
  Current request:" fallback on any reactive token-limit trim.
- The input budget scales with the model's context window instead of being
  capped at a flat 48k chars regardless of model size.
- FOLLOW UP CONTEXT is trimmed after SCREEN/RETRY/REFERENCE MATERIALS, since
  it carries the prior turn's resolved file/reference identity.
- A PINNED CONTEXT section survives even when a reactive token-limit trim
  removes FOLLOW UP CONTEXT entirely.
"""

from __future__ import annotations

import logging

from api.services.agent_processing.lifecycle.planning.agent_context_assembler import (
    AgentContextAssembler,
)
from api.services.agent_processing.shared.prompt_context_trimming import (
    trim_oldest_context,
)

_TRIM_LOGGER = logging.getLogger("test_agent_context_assembly")


def test_derive_budget_chars_scales_up_for_large_context_window():
    assembler = AgentContextAssembler()
    budget = assembler._derive_budget_chars({"context_window": 200_000})
    assert budget > assembler.DEFAULT_INPUT_BUDGET_CHARS
    assert budget <= assembler.MAX_INPUT_BUDGET_CHARS


def test_derive_budget_chars_floors_at_default_when_window_unknown():
    assembler = AgentContextAssembler()
    assert assembler._derive_budget_chars({}) == assembler.DEFAULT_INPUT_BUDGET_CHARS


def test_derive_budget_chars_floors_at_default_for_small_context_window():
    assembler = AgentContextAssembler()
    budget = assembler._derive_budget_chars({"context_window": 8_000})
    assert budget == assembler.DEFAULT_INPUT_BUDGET_CHARS


def test_derive_budget_chars_caps_at_max_for_very_large_context_window():
    assembler = AgentContextAssembler()
    budget = assembler._derive_budget_chars({"context_window": 10_000_000})
    assert budget == assembler.MAX_INPUT_BUDGET_CHARS


def test_retry_context_excludes_persisted_reasoning_history():
    assembler = AgentContextAssembler()

    assembled = assembler.assemble(
        current_request="Retry the task.",
        context={
            "retry_context": {
                "previous_status": "failed",
                "thinking_history": [
                    {"iteration": 1, "text": "Private reasoning must stay explicit-only.", "is_complete": True},
                ],
            },
        },
    )

    assert "Private reasoning must stay explicit-only." not in assembled.user_input


def test_trim_oldest_context_finds_the_actual_underscored_marker():
    # ContextSection.render() emits "===== SCREEN_CONTEXT =====" (underscore),
    # not "===== SCREEN CONTEXT =====" (space). This is a regression guard for
    # that exact mismatch: before the fix, this search always missed and fell
    # through to the "remove everything before Current request:" fallback,
    # which would show up here as the FOLLOW_UP_CONTEXT body being wiped too.
    user_input = (
        "===== SCREEN_CONTEXT =====\n"
        + ("s" * 500)
        + "\n===== END SCREEN_CONTEXT =====\n\n"
        "===== FOLLOW_UP_CONTEXT =====\n"
        + ("f" * 500)
        + "\n===== END FOLLOW_UP_CONTEXT =====\n\n"
        "Current request: do the thing"
    )
    trimmed = trim_oldest_context(user_input, 100, _TRIM_LOGGER)
    assert trimmed is not None
    assert "screen context truncated by 100 chars" in trimmed
    assert "===== FOLLOW_UP_CONTEXT =====\n" + ("f" * 500) in trimmed


def test_trim_oldest_context_exhausts_screen_before_touching_follow_up():
    # SCREEN_CONTEXT's rendered section is exactly 108 chars; FOLLOW_UP_CONTEXT's
    # is 564. Removing 300 chars must fully consume SCREEN_CONTEXT (108) and only
    # partially truncate FOLLOW_UP_CONTEXT with the remaining 192 -- proving
    # SCREEN_CONTEXT is exhausted before FOLLOW_UP_CONTEXT is touched at all,
    # per the reordered trimmable_sections.
    user_input = (
        "===== SCREEN_CONTEXT =====\n"
        + ("s" * 50)
        + "\n===== END SCREEN_CONTEXT =====\n\n"
        "===== FOLLOW_UP_CONTEXT =====\n"
        + ("f" * 500)
        + "\n===== END FOLLOW_UP_CONTEXT =====\n\n"
        "Current request: do the thing"
    )
    trimmed = trim_oldest_context(user_input, 300, _TRIM_LOGGER)
    assert trimmed is not None
    assert "Screen Context removed to fit token limit" in trimmed
    assert "===== SCREEN_CONTEXT =====" not in trimmed
    assert "follow up context truncated by 192 chars" in trimmed
    # Most of the FOLLOW_UP_CONTEXT body should still be present -- it was
    # only partially trimmed, not wiped out like SCREEN_CONTEXT was.
    assert trimmed.count("f") >= 300


def test_format_pinned_context_included_in_assembly():
    assembler = AgentContextAssembler()
    chain_context = {
        "chain_agentTasks": [
            {
                "sequence": 2,
                "text": "use that file",
                "status": "completed",
                "result": {
                    "message": "Copied best_candidate.docx to Downloads.",
                    "files": [{"name": "best_candidate.docx", "full_path": "/Users/me/Documents/best_candidate.docx"}],
                },
            },
        ],
    }

    assembled = assembler.assemble(
        current_request="put a copy in my downloads folder",
        context={"chain_context": chain_context},
    )

    pinned = next((s for s in assembled.sections if s.name == "PINNED CONTEXT"), None)
    assert pinned is not None
    assert "best_candidate.docx" in pinned.body


def test_pinned_context_survives_a_trim_that_fully_removes_follow_up_context():
    assembler = AgentContextAssembler()
    chain_context = {
        "chain_agentTasks": [
            {
                "sequence": 2,
                "text": "use that file",
                "status": "completed",
                "result": {
                    "message": "Copied best_candidate.docx to Downloads.",
                    "files": [{"name": "best_candidate.docx", "full_path": "/Users/me/Documents/best_candidate.docx"}],
                },
            },
        ],
    }
    assembled = assembler.assemble(
        current_request="put a copy in my downloads folder",
        context={"chain_context": chain_context},
    )
    follow_up_len = next(
        len(section.render())
        for section in assembled.sections
        if section.name == "FOLLOW UP CONTEXT"
    )
    rendered = "\n\n".join(section.render() for section in assembled.sections)
    full_prompt = f"{rendered}\n\nCurrent request: put a copy in my downloads folder"

    # Remove exactly the FOLLOW UP CONTEXT section's own length so the trimmer
    # fully consumes it (it is not in the excluded-from-trimming set). The size
    # is measured rather than hardcoded because the conversational rendering
    # rewrite changes this section's byte length; a fixed count would silently
    # stop exercising the full-removal branch. PINNED CONTEXT is never in
    # trimmable_sections and must retain its file reference regardless.
    trimmed = trim_oldest_context(full_prompt, follow_up_len, _TRIM_LOGGER)
    assert trimmed is not None
    assert "best_candidate.docx" in trimmed
    assert "Follow Up Context removed to fit token limit" in trimmed


def test_format_pinned_context_absent_when_chain_has_no_result_data():
    assembler = AgentContextAssembler()
    chain_context = {
        "chain_agentTasks": [
            {"sequence": 1, "text": "hello", "status": "completed", "result": None},
        ],
    }
    assembled = assembler.assemble(
        current_request="follow up",
        context={"chain_context": chain_context},
    )
    assert not any(s.name == "PINNED CONTEXT" for s in assembled.sections)


def test_todo_worker_handoff_renders_bounded_redacted_direct_recall_provenance():
    assembler = AgentContextAssembler()
    source_ids = [f"source-{index}" for index in range(12)]
    reference_paths = ["/tmp/reference.md"]

    assembled = assembler.assemble(
        current_request="Complete the To-Do.",
        context={
            "reference_paths": reference_paths,
            "todo_worker_context": {
                "source_agent_task_ids": source_ids,
                "source_excerpts": {
                    "source-0": {
                        "summary": "The source task established the required implementation.",
                        "authorization": "secret-value",
                    },
                },
                "reference_paths": reference_paths,
            },
        },
    )

    worker_handoff = next(
        section for section in assembled.sections if section.name == "TODO WORKER HANDOFF"
    )
    assert "standalone To-Do worker task, not a follow-up chain" in worker_handoff.body
    assert "recall_agent_tasks(scope='detail', task_id='<source id>')" in worker_handoff.body
    assert "source-0" in worker_handoff.body
    assert "source-9" in worker_handoff.body
    assert "source-10" not in worker_handoff.body
    assert "secret-value" not in worker_handoff.body
    assert "[redacted]" in worker_handoff.body
    assert "Attached reference paths:" not in worker_handoff.body
    assert [section.name for section in assembled.sections] == [
        "TODO WORKER HANDOFF",
        "REFERENCE MATERIALS",
    ]


def test_empty_or_malformed_todo_worker_handoff_is_omitted():
    assembler = AgentContextAssembler()

    empty = assembler.assemble(
        current_request="Complete the To-Do.",
        context={"todo_worker_context": {"source_agent_task_ids": [], "source_excerpts": {}}},
    )
    malformed = assembler.assemble(
        current_request="Complete the To-Do.",
        context={"todo_worker_context": {"source_agent_task_ids": "not-a-list"}},
    )

    assert not any(section.name == "TODO WORKER HANDOFF" for section in empty.sections)
    assert not any(section.name == "TODO WORKER HANDOFF" for section in malformed.sections)
