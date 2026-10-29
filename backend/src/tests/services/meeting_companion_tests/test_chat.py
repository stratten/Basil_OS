import asyncio

import pytest

from api.core.models.reasoning.streaming_contract import StreamEvent, terminal_from_error, terminal_from_provider_reason
from api.services.meeting_companion.chat import (
    RESEARCH_SENTINEL,
    ChatRequest,
    CompanionChatService,
    SentinelFilter,
    build_chat_prompt,
    resolve_citation_markers,
)
from api.services.meeting_companion.context_pack import ContextExcerpt, ContextPack
from api.services.meeting_companion.models import ChatMessage, CompanionTurn


def make_pack():
    return ContextPack(excerpts=[ContextExcerpt("c1", "r1", "proj/retry.py", 3, 9, "def backoff(attempt): pass", 5.0)])


def make_request(**overrides):
    turn = CompanionTurn(id="t-00001", source_meeting_id="m", role="other", speaker="Zoom", start=10.0, end=13.0, text="How does the retry policy work")
    values = dict(
        user_text="What did they just ask?",
        meeting_time=14.0,
        window_turns=[turn],
        conversation_state="Retries are discussed.",
        history=[
            ChatMessage(id="m1", role="user", text="Earlier question", meeting_time=5.0),
            ChatMessage(id="m2", role="assistant", text="Earlier answer", meeting_time=6.0),
        ],
        pack=make_pack(),
        has_roots=True,
    )
    values.update(overrides)
    return ChatRequest(**values)


def test_prompt_sections_and_history_labels():
    prompt = build_chat_prompt(make_request())
    for expected in (
        "You are read-only",
        "CONVERSATION SO FAR\nRetries are discussed.",
        "CHAT SO FAR\nUser: Earlier question\nCompanion: Earlier answer",
        '<excerpt id="c1" path="proj/retry.py"',
        "[t-00001 @ 00:10] Zoom: How does the retry policy work",
        "USER QUESTION\nWhat did they just ask?",
    ):
        assert expected in prompt


def test_prompt_states_missing_context():
    assert "(no files are attached)" in build_chat_prompt(make_request(has_roots=False, pack=None))
    assert "nothing relevant was found" in build_chat_prompt(make_request(pack=ContextPack()))
    assert "(no earlier messages)" in build_chat_prompt(make_request(history=[]))


def test_resolve_markers_rewrites_known_and_removes_unknown():
    text = "It caps backoff [c1] and retries forever [c9] ."
    assert resolve_citation_markers(text, make_pack()) == "It caps backoff [proj/retry.py:3-9] and retries forever."
    assert resolve_citation_markers("No markers here.", None) == "No markers here."
    assert resolve_citation_markers("Nothing [c1].", None) == "Nothing."


class StreamingModel:
    def __init__(self, events):
        self.events = events
        self.messages = None

    async def stream_chat_completion(self, messages, budget=None):
        self.messages = messages
        for event in self.events:
            yield event


def make_service(model, **overrides):
    async def provider(model_id):
        return model

    return CompanionChatService(model_provider=provider, budget_resolver=lambda m: None, **overrides)


@pytest.mark.asyncio
async def test_streams_deltas_and_resolves_markers():
    received = []

    async def on_delta(text):
        received.append(text)

    model = StreamingModel(
        [StreamEvent(text="Backoff is capped "), StreamEvent(text="at thirty seconds [c1]."), StreamEvent(terminal=terminal_from_provider_reason("end_turn"))]
    )
    result = await make_service(model).stream_answer(make_request(), on_delta)
    assert received == ["Backoff is capped ", "at thirty seconds [c1]."]
    assert result.text == "Backoff is capped at thirty seconds [proj/retry.py:3-9]." and result.status == "complete"
    assert result.truncated is False and result.error is None
    assert model.messages[0]["role"] == "user" and "USER QUESTION" in model.messages[0]["content"]


@pytest.mark.asyncio
async def test_truncated_terminal_is_flagged_but_complete():
    async def on_delta(text):
        pass

    model = StreamingModel([StreamEvent(text="Partial answer"), StreamEvent(terminal=terminal_from_provider_reason("max_tokens"))])
    result = await make_service(model).stream_answer(make_request(), on_delta)
    assert result.truncated is True and result.status == "complete" and result.text == "Partial answer"


@pytest.mark.asyncio
async def test_error_and_safety_terminals_set_error_status():
    async def on_delta(text):
        pass

    errored = StreamingModel([StreamEvent(text="Half"), StreamEvent(terminal=terminal_from_error(RuntimeError("boom")))])
    result = await make_service(errored).stream_answer(make_request(), on_delta)
    assert result.status == "error" and result.truncated is True and result.error == "boom" and result.text == "Half"
    blocked = StreamingModel([StreamEvent(terminal=terminal_from_provider_reason("safety"))])
    result = await make_service(blocked).stream_answer(make_request(), on_delta)
    assert result.status == "error" and result.display_text() == "I couldn't answer that right now."


@pytest.mark.asyncio
async def test_delta_callback_failure_does_not_abort_generation():
    async def on_delta(text):
        raise RuntimeError("socket closed")

    model = StreamingModel([StreamEvent(text="Still answered."), StreamEvent(terminal=terminal_from_provider_reason("end_turn"))])
    result = await make_service(model).stream_answer(make_request(), on_delta)
    assert result.text == "Still answered." and result.error is None


class OneShotModel:
    pass


@pytest.mark.asyncio
async def test_model_without_streaming_uses_one_shot_prompt_call():
    received = []
    seen = {}

    async def on_delta(text):
        received.append(text)

    async def prompt_caller(model, *, prompt, max_tokens, purpose):
        seen.update(prompt=prompt, max_tokens=max_tokens, purpose=purpose)
        return "One shot answer [c1]."

    result = await make_service(OneShotModel(), prompt_caller=prompt_caller).stream_answer(make_request(), on_delta)
    assert received == ["One shot answer [c1]."] and result.text == "One shot answer [proj/retry.py:3-9]."
    assert seen["max_tokens"] == 1200 and "USER QUESTION" in seen["prompt"]


@pytest.mark.asyncio
async def test_model_unavailable_and_exception_are_returned():
    async def on_delta(text):
        pass

    async def failing_provider(model_id):
        raise RuntimeError("no model")

    unavailable = CompanionChatService(model_provider=failing_provider, budget_resolver=lambda m: None)
    assert (await unavailable.stream_answer(make_request(), on_delta)).error.startswith("model_unavailable")

    async def prompt_caller(model, *, prompt, max_tokens, purpose):
        raise ValueError("kaboom")

    result = await make_service(OneShotModel(), prompt_caller=prompt_caller).stream_answer(make_request(), on_delta)
    assert result.error == "chat_failed: kaboom" and result.status == "error"


@pytest.mark.asyncio
async def test_timeout_keeps_partial_text_and_marks_truncated():
    async def on_delta(text):
        pass

    class SlowModel:
        async def stream_chat_completion(self, messages, budget=None):
            yield StreamEvent(text="Beginning")
            await asyncio.sleep(1)
            yield StreamEvent(text=" never reached")

    result = await make_service(SlowModel(), timeout_seconds=0.05).stream_answer(make_request(), on_delta)
    assert result.error == "timeout" and result.truncated is True and result.text == "Beginning"


def test_focus_section_appears_only_when_the_user_set_one():
    assert "USER FOCUS" not in build_chat_prompt(make_request())
    assert "USER FOCUS" not in build_chat_prompt(make_request(focus="   "))
    prompt = build_chat_prompt(make_request(focus="  Pricing and the renewal date  "))
    assert "USER FOCUS" in prompt
    assert "Pricing and the renewal date" in prompt
    assert prompt.index("USER FOCUS") < prompt.index("CONVERSATION SO FAR")


def test_the_research_rule_is_in_the_prompt_only_when_research_is_on():
    assert RESEARCH_SENTINEL not in build_chat_prompt(make_request())
    prompt = build_chat_prompt(make_request(research_enabled=True))
    assert prompt.count(RESEARCH_SENTINEL) == 1 and "6. If you could not answer" in prompt


def test_sentinel_filter_removes_a_whole_sentinel_and_reports_it():
    sentinel = SentinelFilter()
    assert sentinel.feed(f"Not in the files.\n{RESEARCH_SENTINEL}") == "Not in the files.\n"
    assert sentinel.seen is True and sentinel.flush() == ""


def test_sentinel_filter_never_shows_a_sentinel_split_across_pieces():
    sentinel = SentinelFilter()
    shown = [sentinel.feed(piece) for piece in ("Not here.\n<<NEEDS", "_RESEA", "RCH>>")]
    assert "".join(shown) == "Not here.\n" and sentinel.seen is True
    assert all("<<" not in piece for piece in shown)


def test_sentinel_filter_releases_a_held_prefix_that_turns_out_to_be_ordinary_text():
    sentinel = SentinelFilter()
    assert sentinel.feed("Use a <") == "Use a "
    assert sentinel.feed("b> tag") == "<b> tag"
    assert sentinel.seen is False and sentinel.flush() == ""


def test_sentinel_filter_flush_keeps_a_short_held_character_and_drops_a_long_unfinished_sentinel():
    short = SentinelFilter()
    assert short.feed("a <") == "a "
    assert short.flush() == "<"
    unfinished = SentinelFilter()
    assert unfinished.feed("Not here.<<NEEDS_RESE") == "Not here."
    assert unfinished.flush() == "" and unfinished.seen is False


@pytest.mark.asyncio
async def test_a_sentinel_is_stripped_from_the_text_and_the_deltas_and_flagged():
    events = [StreamEvent(text="The files do not say.\n<<NEEDS_"), StreamEvent(text="RESEARCH>>", terminal=terminal_from_provider_reason("stop"))]
    seen = []

    async def on_delta(piece):
        seen.append(piece)

    result = await make_service(StreamingModel(events)).stream_answer(make_request(research_enabled=True), on_delta)
    assert result.text == "The files do not say." and result.needs_research is True and result.error is None
    assert RESEARCH_SENTINEL not in "".join(seen) and RESEARCH_SENTINEL not in "".join(result.deltas)


@pytest.mark.asyncio
async def test_no_sentinel_means_no_research_and_an_error_never_requests_it():
    async def on_delta(piece):
        return None

    plain = await make_service(StreamingModel([StreamEvent(text="Five attempts.", terminal=terminal_from_provider_reason("stop"))])).stream_answer(make_request(), on_delta)
    assert plain.needs_research is False
    failed = await make_service(
        StreamingModel([StreamEvent(text=f"Partial {RESEARCH_SENTINEL}", terminal=terminal_from_error("boom"))])
    ).stream_answer(make_request(), on_delta)
    assert failed.error and failed.needs_research is False and RESEARCH_SENTINEL not in failed.text
