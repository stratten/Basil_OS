from types import SimpleNamespace

import pytest
from pydantic import BaseModel, ConfigDict

from api.core.models import model_invocation
from api.core.models.model_invocation import (
    StructuredModelOutputError,
    _classify_provider_exception,
    _reject_incomplete_finish_reason,
    call_model_with_schema,
)


class _Payload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: str


class _FallbackModel:
    model_name = "unknown-structured-test"

    def __init__(self, raw):
        self.raw = raw
        self.calls = 0

    async def generate_response(self, **_kwargs):
        self.calls += 1
        return self.raw


@pytest.fixture
def profile(monkeypatch):
    def install(handler):
        monkeypatch.setattr(
            model_invocation,
            "resolve_runtime_model_profile",
            lambda _model: SimpleNamespace(
                model_id="test-model",
                handler=handler,
            ),
        )

    return install


@pytest.mark.asyncio
async def test_strict_fallback_accepts_exact_json(profile):
    profile(None)
    result = await call_model_with_schema(
        _FallbackModel('{"value":"ok"}'),
        prompt="prompt",
        response_model=_Payload,
        max_tokens=100,
    )
    assert result.value == _Payload(value="ok")
    assert result.enforcement == "strict_json_fallback"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "raw",
    [
        '```json\n{"value":"ok"}\n```',
        'Result: {"value":"ok"}',
        '{"value":',
        '{"value":"ok","extra":true}',
    ],
)
async def test_strict_fallback_rejects_non_exact_or_invalid_json(profile, raw):
    profile(None)
    with pytest.raises(StructuredModelOutputError):
        await call_model_with_schema(
            _FallbackModel(raw),
            prompt="prompt",
            response_model=_Payload,
            max_tokens=100,
        )


@pytest.mark.asyncio
async def test_llama_cpp_passes_schema_and_rejects_length(profile):
    profile("llama_cpp")
    captured = {}

    class Llm:
        def create_chat_completion(self, **kwargs):
            captured.update(kwargs)
            return {
                "choices": [{
                    "finish_reason": "length",
                    "message": {"content": '{"value":"partial"}'},
                }]
            }

    model = SimpleNamespace(llm=Llm(), top_p=0.9)
    with pytest.raises(StructuredModelOutputError, match="incompletely") as exc_info:
        await call_model_with_schema(
            model,
            prompt="prompt",
            response_model=_Payload,
            max_tokens=100,
        )
    assert captured["response_format"]["schema"] == _Payload.model_json_schema()
    assert exc_info.value.category == "output_limit"
    assert exc_info.value.retryable is False


def test_reject_incomplete_finish_reason_classifies_max_tokens_as_output_limit():
    with pytest.raises(StructuredModelOutputError) as exc_info:
        _reject_incomplete_finish_reason(
            "max_tokens",
            enforcement="anthropic_output_format",
        )

    assert exc_info.value.category == "output_limit"
    assert exc_info.value.retryable is False


def test_reject_incomplete_finish_reason_rejects_unknown_reason_as_provider():
    with pytest.raises(StructuredModelOutputError) as exc_info:
        _reject_incomplete_finish_reason(
            "unexpected_status",
            enforcement="anthropic_output_format",
        )

    assert exc_info.value.category == "provider"
    assert exc_info.value.retryable is False


def test_classify_provider_exception_marks_timeout_as_transient():
    category, retryable = _classify_provider_exception(TimeoutError("timed out"))
    assert category == "transient"
    assert retryable is True


def test_classify_provider_exception_marks_empty_structured_output_as_transient():
    error = RuntimeError(
        "Invalid JSON: EOF while parsing a value at line 1 column 0 "
        "[type=json_invalid, input_value='', input_type=str]"
    )

    category, retryable = _classify_provider_exception(error)

    assert category == "transient"
    assert retryable is True


def test_classify_provider_exception_marks_401_as_authentication():
    class AuthError(Exception):
        status_code = 401

    category, retryable = _classify_provider_exception(AuthError("unauthorized"))
    assert category == "authentication"
    assert retryable is False


@pytest.mark.asyncio
async def test_generic_provider_exception_uses_classification(profile):
    profile(None)

    class TimeoutModel:
        model_name = "timeout-test"

        async def generate_response(self, **_kwargs):
            raise TimeoutError("request timed out")

    with pytest.raises(StructuredModelOutputError) as exc_info:
        await call_model_with_schema(
            TimeoutModel(),
            prompt="prompt",
            response_model=_Payload,
            max_tokens=100,
        )

    assert exc_info.value.category == "transient"
    assert exc_info.value.retryable is True


@pytest.mark.asyncio
async def test_native_failure_never_calls_text_fallback(profile):
    profile("llama_cpp")

    class Model:
        llm = SimpleNamespace(
            create_chat_completion=lambda **_kwargs: (_ for _ in ()).throw(
                RuntimeError("native failed")
            )
        )
        top_p = 0.9

        def __init__(self):
            self.text_calls = 0

        async def generate_response(self, **_kwargs):
            self.text_calls += 1
            return '{"value":"fallback"}'

    model = Model()
    with pytest.raises(StructuredModelOutputError, match="native failed"):
        await call_model_with_schema(
            model,
            prompt="prompt",
            response_model=_Payload,
            max_tokens=100,
        )
    assert model.text_calls == 0


@pytest.mark.asyncio
async def test_openai_responses_parse_returns_typed_value(profile):
    profile("openai_api")

    class Responses:
        async def parse(self, **kwargs):
            assert kwargs["text_format"] is _Payload
            return SimpleNamespace(
                status="completed",
                output_parsed=_Payload(value="responses"),
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
    )
    assert result.value.value == "responses"
    assert result.enforcement == "openai_responses_parse"


@pytest.mark.asyncio
async def test_openai_chat_parse_returns_typed_value(profile):
    profile("openai_api")

    class Completions:
        async def parse(self, **kwargs):
            assert kwargs["response_format"] is _Payload
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        finish_reason="stop",
                        message=SimpleNamespace(
                            parsed=_Payload(value="chat")
                        ),
                    )
                ]
            )

    model = SimpleNamespace(
        _async_client=SimpleNamespace(
            chat=SimpleNamespace(completions=Completions())
        ),
        model_name="gpt-test",
        max_output_tokens=100,
        _requires_responses_api=lambda: False,
    )
    result = await call_model_with_schema(
        model,
        prompt="prompt",
        response_model=_Payload,
        max_tokens=100,
    )
    assert result.value.value == "chat"
    assert result.enforcement == "openai_chat_parse"


@pytest.mark.asyncio
async def test_anthropic_output_format_returns_typed_value(profile):
    profile("anthropic_api")

    class Stream:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def get_final_message(self):
            return SimpleNamespace(
                stop_reason="end_turn",
                parsed_output=_Payload(value="anthropic"),
            )

    class Messages:
        def stream(self, **kwargs):
            assert kwargs["output_format"] is _Payload
            return Stream()

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
        model,
        prompt="prompt",
        response_model=_Payload,
        max_tokens=100,
    )
    assert result.value.value == "anthropic"
    assert result.enforcement == "anthropic_output_format"


@pytest.mark.asyncio
async def test_anthropic_refusal_preserves_provider_diagnostics(profile):
    profile("anthropic_api")

    class Stream:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def get_final_message(self):
            return SimpleNamespace(
                stop_reason="refusal",
                stop_details=SimpleNamespace(
                    category="general_harms",
                    explanation="The provider declined this test request.",
                ),
                parsed_output=None,
            )

    class Messages:
        def stream(self, **_kwargs):
            return Stream()

    model = SimpleNamespace(
        _async_client=SimpleNamespace(messages=Messages()),
        _client=SimpleNamespace(),
        model_name="claude-test",
        max_output_tokens=100,
        temperature=0.1,
        _get_base_model_id=lambda: "claude-test",
        _apply_thinking_to_api_params=lambda _params: None,
    )

    with pytest.raises(StructuredModelOutputError) as exc_info:
        await call_model_with_schema(
            model,
            prompt="prompt",
            response_model=_Payload,
            max_tokens=100,
        )

    assert exc_info.value.category == "safety"
    assert exc_info.value.retryable is False
    assert exc_info.value.refusal_category == "general_harms"
    assert exc_info.value.refusal_explanation == "The provider declined this test request."


@pytest.mark.asyncio
async def test_gemini_response_json_schema_returns_typed_value(profile):
    profile("gemini_api")
    captured = {}

    class Models:
        def generate_content(self, *, model, contents, config):
            captured["model"] = model
            captured["contents"] = contents
            captured["config"] = config
            return SimpleNamespace(
                text='{"value":"gemini"}',
                candidates=[
                    SimpleNamespace(
                        finish_reason=SimpleNamespace(name="STOP")
                    )
                ],
            )

    def build_config(_tokens, **overrides):
        return {"max_output_tokens": 100, **overrides}

    model = SimpleNamespace(
        model_name="gemini-test",
        _client=SimpleNamespace(models=Models()),
        _build_generation_config=build_config,
    )
    result = await call_model_with_schema(
        model,
        prompt="prompt",
        response_model=_Payload,
        max_tokens=100,
    )
    assert result.value.value == "gemini"
    assert result.enforcement == "gemini_response_schema"
    assert captured["model"] == "gemini-test"
    assert captured["contents"] == "prompt"
    assert captured["config"]["response_mime_type"] == "application/json"
    assert captured["config"]["response_json_schema"] == _Payload.model_json_schema()
    assert "response_schema" not in captured["config"]


@pytest.mark.asyncio
async def test_gemini_structured_call_reports_unavailable_client(profile):
    profile("gemini_api")

    class Unloadable:
        model_name = "gemini-test"
        _client = None
        _error = "Failed to load Gemini model: no key"

        async def load(self):
            return None

    with pytest.raises(
        StructuredModelOutputError,
        match="Gemini client is unavailable: Failed to load Gemini model: no key",
    ):
        await call_model_with_schema(
            Unloadable(),
            prompt="prompt",
            response_model=_Payload,
            max_tokens=10,
        )


@pytest.mark.asyncio
async def test_gemini_structured_call_rejects_empty_candidates(profile):
    profile("gemini_api")

    class Models:
        def generate_content(self, *, model, contents, config):
            return SimpleNamespace(text=None, candidates=[])

    model = SimpleNamespace(
        model_name="gemini-test",
        _client=SimpleNamespace(models=Models()),
        _build_generation_config=lambda _tokens, **overrides: dict(overrides),
    )
    with pytest.raises(StructuredModelOutputError, match="Gemini returned no candidates"):
        await call_model_with_schema(
            model,
            prompt="prompt",
            response_model=_Payload,
            max_tokens=10,
        )


def test_classify_provider_exception_reads_google_genai_code():
    class GenaiError(Exception):
        def __init__(self, code):
            super().__init__(f"{code} error")
            self.code = code

    assert _classify_provider_exception(GenaiError(429)) == ("transient", True)
    assert _classify_provider_exception(GenaiError(503)) == ("transient", True)
    assert _classify_provider_exception(GenaiError(403)) == ("authentication", False)
    assert _classify_provider_exception(GenaiError(400)) == ("provider", False)
    assert _classify_provider_exception(GenaiError("429")) == ("provider", False)
