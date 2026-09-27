"""The synthesis prompt must bound oversized source material."""

from api.services.zettel.narrative.prompt import CONTEXT_MAX_CHARS, build_prompt


def test_oversized_context_is_truncated():
    entry = {"source_kind": "agent_task", "title": "Big task", "occurred_at": "now"}
    context = {"result_data": "x" * 100000}
    prompt = build_prompt(entry, context)
    assert "[truncated]" in prompt
    # Two bounded blocks (header + material) plus fixed instruction text.
    assert len(prompt) < 2 * CONTEXT_MAX_CHARS + 4000


def test_prompt_states_the_output_contract():
    prompt = build_prompt({"source_kind": "conversation", "title": "Chat"}, {"messages": []})
    assert '"narrative"' in prompt
    assert '"is_open"' not in prompt
    assert '"open_note"' not in prompt


def test_prompt_includes_the_title_and_kind_hint():
    prompt = build_prompt({"source_kind": "agent_task", "title": "Refactor the parser"}, {})
    assert "Refactor the parser" in prompt
    assert "agent task" in prompt


def test_prompt_allows_recorded_request_without_claiming_completion():
    prompt = build_prompt(
        {
            "source_kind": "transcription",
            "title": "Review the contract",
            "occurred_at": "2026-07-28T09:00:00+00:00",
            "source_status": "completed",
            "summary": "Can you review the contract?",
            "payload": {},
        },
        {"transcription_text": "Can you review the contract?"},
    )

    assert "such as a request, question, decision, or stated intent" in prompt
    assert "Do not claim that a requested action was completed" in prompt


def test_prompt_treats_source_lifecycle_as_terminal_authority():
    prompt = build_prompt(
        {
            "source_kind": "transcription",
            "title": "Standup",
            "occurred_at": "2025-02-25T16:58:12+00:00",
            "source_status": "completed",
            "summary": "s",
            "payload": {},
        },
        {"text": "We should decide on the modal later."},
    )

    assert "terminal memory event" in prompt
    assert "do not decide whether it remains open" in prompt
    assert "completed" in prompt


def test_prompt_excludes_retired_open_state_fields():
    prompt = build_prompt(
        {
            "source_kind": "agent_task",
            "title": "t",
            "occurred_at": "2026-01-01T00:00:00+00:00",
            "source_status": "completed",
            "summary": "s",
            "payload": {},
        },
        {},
    )

    assert '"is_open"' not in prompt
    assert '"open_note"' not in prompt
