"""Cache-break handling, provider usage capture, and optional text-delta streaming."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel, ConfigDict

from api.core.models import model_invocation
from api.core.models.model_invocation import (
    ANALYSIS_CACHE_BREAK,
    call_model_with_schema,
    flatten_cache_break,
    split_cache_break,
)


class _Payload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: str


@pytest.fixture
def profile(monkeypatch):
    def install(handler):
        monkeypatch.setattr(
            model_invocation,
            "resolve_runtime_model_profile",
            lambda _model: SimpleNamespace(model_id="test-model", handler=handler),
        )

    return install


def test_split_and_flatten_handle_presence_and_absence_of_the_marker():
    prompt = f"stable{ANALYSIS_CACHE_BREAK}task"

    assert split_cache_break(prompt) == ("stable", "task")
    assert flatten_cache_break(prompt) == "stable\n\ntask"
    assert split_cache_break("no marker") == ("no marker", None)
    assert flatten_cache_break("no marker") == "no marker"


class _AnthropicStream:
    def __init__(self, texts, final):
        self._texts = texts
        self._final = final

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    @property
    def text_stream(self):
        texts = self._texts

        async def generator():
            for text in texts:
                yield text

        return generator()

    async def get_final_message(self):
        return self._final


def _anthropic_model(captured, texts=(), usage=None):
    final = SimpleNamespace(
        stop_reason="end_turn",
        parsed_output=_Payload(value="anthropic"),
        usage=usage,
    )

    class Messages:
        def stream(self, **kwargs):
            captured.update(kwargs)
            return _AnthropicStream(list(texts), final)

    return SimpleNamespace(
        _async_client=SimpleNamespace(messages=Messages()),
        _client=SimpleNamespace(),
        model_name="claude-test",
        max_output_tokens=100,
        temperature=0.1,
        _get_base_model_id=lambda: "claude-test",
        _apply_thinking_to_api_params=lambda _params: None,
    )


@pytest.mark.asyncio
async def test_anthropic_receives_an_explicit_cache_breakpoint_at_the_marker(profile):
    profile("anthropic_api")
    captured = {}

    await call_model_with_schema(
        _anthropic_model(captured),
        prompt=f"stable prefix{ANALYSIS_CACHE_BREAK}task suffix",
        response_model=_Payload,
        max_tokens=100,
    )

    assert captured["messages"] == [
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": "stable prefix",
                    "cache_control": {"type": "ephemeral"},
                },
                {"type": "text", "text": "task suffix"},
            ],
        }
    ]


@pytest.mark.asyncio
async def test_anthropic_prompt_without_a_marker_is_sent_unchanged(profile):
    profile("anthropic_api")
    captured = {}

    await call_model_with_schema(
        _anthropic_model(captured),
        prompt="plain prompt",
        response_model=_Payload,
        max_tokens=100,
    )

    assert captured["messages"] == [{"role": "user", "content": "plain prompt"}]


@pytest.mark.asyncio
async def test_openai_chat_never_sees_the_marker(profile):
    profile("openai_api")
    captured = {}

    class Completions:
        async def parse(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        finish_reason="stop",
                        message=SimpleNamespace(parsed=_Payload(value="chat")),
                    )
                ]
            )

    model = SimpleNamespace(
        _async_client=SimpleNamespace(chat=SimpleNamespace(completions=Completions())),
        model_name="gpt-test",
        max_output_tokens=100,
        _requires_responses_api=lambda: False,
    )

    await call_model_with_schema(
        model,
        prompt=f"stable{ANALYSIS_CACHE_BREAK}task",
        response_model=_Payload,
        max_tokens=100,
    )

    user_message = captured["messages"][1]["content"]
    assert user_message == "stable\n\ntask"
    assert "BASIL_CACHE_BREAK" not in user_message


@pytest.mark.asyncio
async def test_strict_fallback_never_sees_the_marker(profile):
    profile(None)
    seen = {}

    class Model:
        model_name = "unknown-structured-test"

        async def generate_response(self, **kwargs):
            seen.update(kwargs)
            return '{"value":"ok"}'

    await call_model_with_schema(
        Model(),
        prompt=f"stable{ANALYSIS_CACHE_BREAK}task",
        response_model=_Payload,
        max_tokens=100,
    )

    assert "BASIL_CACHE_BREAK" not in str(seen)


@pytest.mark.asyncio
async def test_anthropic_usage_is_captured_as_integers(profile):
    profile("anthropic_api")
    usage = SimpleNamespace(
        input_tokens=100,
        output_tokens=20,
        cache_read_input_tokens=80,
        cache_creation_input_tokens=0,
    )

    result = await call_model_with_schema(
        _anthropic_model({}, usage=usage),
        prompt="prompt",
        response_model=_Payload,
        max_tokens=100,
    )

    assert result.usage == {
        "input_tokens": 100,
        "output_tokens": 20,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 80,
    }


@pytest.mark.asyncio
async def test_unusable_usage_objects_are_ignored(profile):
    profile("anthropic_api")

    result = await call_model_with_schema(
        _anthropic_model({}, usage=MagicMock()),
        prompt="prompt",
        response_model=_Payload,
        max_tokens=100,
    )

    assert result.usage is None


@pytest.mark.asyncio
async def test_openai_chat_usage_includes_cached_tokens(profile):
    profile("openai_api")

    class Completions:
        async def parse(self, **_kwargs):
            return SimpleNamespace(
                usage=SimpleNamespace(
                    prompt_tokens=50,
                    completion_tokens=5,
                    prompt_tokens_details=SimpleNamespace(cached_tokens=32),
                ),
                choices=[
                    SimpleNamespace(
                        finish_reason="stop",
                        message=SimpleNamespace(parsed=_Payload(value="chat")),
                    )
                ],
            )

    model = SimpleNamespace(
        _async_client=SimpleNamespace(chat=SimpleNamespace(completions=Completions())),
        model_name="gpt-test",
        max_output_tokens=100,
        _requires_responses_api=lambda: False,
    )

    result = await call_model_with_schema(
        model, prompt="prompt", response_model=_Payload, max_tokens=100
    )

    assert result.usage == {
        "prompt_tokens": 50,
        "completion_tokens": 5,
        "cached_tokens": 32,
    }


@pytest.mark.asyncio
async def test_anthropic_text_deltas_stream_before_the_final_message(profile):
    profile("anthropic_api")
    deltas = []

    async def consume(text):
        deltas.append(text)

    result = await call_model_with_schema(
        _anthropic_model({}, texts=['{"val', 'ue":"x"}']),
        prompt="prompt",
        response_model=_Payload,
        max_tokens=100,
        on_text_delta=consume,
    )

    assert deltas == ['{"val', 'ue":"x"}']
    assert result.value.value == "anthropic"


@pytest.mark.asyncio
async def test_a_failing_delta_consumer_never_fails_the_model_call(profile):
    profile("anthropic_api")
    seen = []

    async def consume(text):
        seen.append(text)
        if len(seen) == 1:
            raise RuntimeError("consumer bug")

    result = await call_model_with_schema(
        _anthropic_model({}, texts=["a", "b", "c"]),
        prompt="prompt",
        response_model=_Payload,
        max_tokens=100,
        on_text_delta=consume,
    )

    assert seen == ["a", "b", "c"]
    assert result.value.value == "anthropic"


@pytest.mark.asyncio
async def test_stream_object_without_text_stream_works_when_no_consumer_is_given(profile):
    profile("anthropic_api")

    class BareStream:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def get_final_message(self):
            return SimpleNamespace(
                stop_reason="end_turn", parsed_output=_Payload(value="bare")
            )

    class Messages:
        def stream(self, **_kwargs):
            return BareStream()

    model = SimpleNamespace(
        _async_client=SimpleNamespace(messages=Messages()),
        _client=SimpleNamespace(),
        model_name="claude-test",
        max_output_tokens=100,
        temperature=0.1,
        _get_base_model_id=lambda: "claude-test",
        _apply_thinking_to_api_params=lambda _params: None,
    )

    result = await call_model_with_schema(
        model, prompt="prompt", response_model=_Payload, max_tokens=100
    )

    assert result.value.value == "bare"


class _EventStream:
    def __init__(self, events, final_name, final):
        self._events = events
        setattr(self, final_name, self._make_final(final))

    @staticmethod
    def _make_final(final):
        async def get_final():
            return final

        return get_final

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    def __aiter__(self):
        events = self._events

        async def generator():
            for event in events:
                yield event

        return generator()


@pytest.mark.asyncio
async def test_openai_chat_streams_content_deltas_and_still_returns_a_typed_value(profile):
    profile("openai_api")
    deltas = []

    async def consume(text):
        deltas.append(text)

    completion = SimpleNamespace(
        choices=[
            SimpleNamespace(
                finish_reason="stop",
                message=SimpleNamespace(parsed=_Payload(value="streamed-chat")),
            )
        ]
    )

    class Completions:
        def stream(self, **kwargs):
            assert kwargs["response_format"] is _Payload
            return _EventStream(
                [
                    SimpleNamespace(type="content.delta", delta='{"value"'),
                    SimpleNamespace(type="content.delta", delta=':"x"}'),
                    SimpleNamespace(type="content.done"),
                ],
                "get_final_completion",
                completion,
            )

    model = SimpleNamespace(
        _async_client=SimpleNamespace(chat=SimpleNamespace(completions=Completions())),
        model_name="gpt-test",
        max_output_tokens=100,
        _requires_responses_api=lambda: False,
    )

    result = await call_model_with_schema(
        model,
        prompt="prompt",
        response_model=_Payload,
        max_tokens=100,
        on_text_delta=consume,
    )

    assert deltas == ['{"value"', ':"x"}']
    assert result.value.value == "streamed-chat"
    assert result.enforcement == "openai_chat_parse"


@pytest.mark.asyncio
async def test_openai_responses_streams_output_text_deltas(profile):
    profile("openai_api")
    deltas = []

    async def consume(text):
        deltas.append(text)

    final = SimpleNamespace(
        status="completed", output_parsed=_Payload(value="streamed-responses")
    )

    class Responses:
        def stream(self, **kwargs):
            assert kwargs["text_format"] is _Payload
            return _EventStream(
                [
                    SimpleNamespace(type="response.created"),
                    SimpleNamespace(type="response.output_text.delta", delta="abc"),
                ],
                "get_final_response",
                final,
            )

    model = SimpleNamespace(
        _async_client=SimpleNamespace(responses=Responses()),
        model_name="gpt-test",
        max_output_tokens=100,
        _requires_responses_api=lambda: True,
        _get_reasoning_effort=lambda: None,
    )

    result = await call_model_with_schema(
        model,
        prompt="prompt",
        response_model=_Payload,
        max_tokens=100,
        on_text_delta=consume,
    )

    assert deltas == ["abc"]
    assert result.value.value == "streamed-responses"
    assert result.enforcement == "openai_responses_parse"
