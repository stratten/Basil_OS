import base64
from pathlib import Path
from types import SimpleNamespace

import pytest

from api.core.models.base_model import ModelState
from api.core.models.model_types import ModelCapability
from api.core.models.reasoning.gemini_model import GeminiModel


class _FakeModels:
    def __init__(self, response=None, stream_chunks=None):
        self.calls = []
        self.response = response
        self.stream_chunks = stream_chunks or []

    def generate_content(self, *, model, contents, config):
        self.calls.append({"model": model, "contents": contents, "config": config})
        return self.response

    def generate_content_stream(self, *, model, contents, config):
        self.calls.append({"model": model, "contents": contents, "config": config})
        return iter(self.stream_chunks)


class _FakeClient:
    def __init__(self, models):
        self.models = models
        self.closed = False

    def close(self):
        self.closed = True


def _part(text, thought=False):
    return SimpleNamespace(text=text, thought=thought)


def _response(*texts, finish="STOP", thought_texts=(), safety_ratings=()):
    parts = [_part(text, thought=True) for text in thought_texts]
    parts.extend(_part(text) for text in texts)
    candidate = SimpleNamespace(
        content=SimpleNamespace(parts=parts),
        finish_reason=SimpleNamespace(name=finish),
        safety_ratings=list(safety_ratings),
    )
    return SimpleNamespace(candidates=[candidate], prompt_feedback=None)


def _loaded_model(model_name, models):
    model = GeminiModel(Path("gemini"), {ModelCapability.REASONING})
    model.model_name = model_name
    model.max_output_tokens = model._get_max_output_tokens()
    model._client = _FakeClient(models)
    model.state = ModelState.READY
    return model


def test_config_sends_registry_thinking_level_and_omits_sampling():
    model = _loaded_model("gemini-3.8-flash", _FakeModels())
    assert model._build_generation_config(100) == {
        "max_output_tokens": 100,
        "thinking_config": {"thinking_level": "medium"},
        "automatic_function_calling": {"disable": True},
    }


def test_config_with_auto_thinking_sends_no_thinking_config():
    model = _loaded_model("gemini-3.5-flash", _FakeModels())
    assert model._build_generation_config(100) == {
        "temperature": 0.7,
        "top_p": 0.9,
        "top_k": 40,
        "max_output_tokens": 100,
        "automatic_function_calling": {"disable": True},
    }


def test_config_caps_max_tokens_and_applies_overrides():
    model = _loaded_model("gemini-3.8-flash", _FakeModels())
    config = model._build_generation_config(10_000_000, response_mime_type="application/json")
    assert config["max_output_tokens"] == model.max_output_tokens
    assert config["response_mime_type"] == "application/json"


@pytest.mark.asyncio
async def test_predict_sends_system_instruction_and_full_history():
    png = base64.b64encode(b"png-bytes").decode("ascii")
    models = _FakeModels(response=_response("done"))
    model = _loaded_model("gemini-3.8-flash", models)
    result = await model.predict([
        {"role": "system", "content": "be terse"},
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "reply"},
        {"role": "user", "content": [
            {"type": "text", "text": "look"},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{png}"}},
        ]},
    ])
    assert result == "done"
    call = models.calls[0]
    assert call["model"] == "gemini-3.8-flash"
    assert call["config"]["system_instruction"] == "be terse"
    assert [content["role"] for content in call["contents"]] == ["user", "model", "user"]
    assert call["contents"][0]["parts"] == [{"text": "first"}]
    assert call["contents"][2]["parts"] == [
        {"text": "look"},
        {"inline_data": {"mime_type": "image/png", "data": b"png-bytes"}},
    ]


@pytest.mark.asyncio
async def test_predict_forwards_pdf_data_url_with_its_mime_type():
    pdf = base64.b64encode(b"%PDF-1.7").decode("ascii")
    models = _FakeModels(response=_response("ok"))
    model = _loaded_model("gemini-3.8-flash", models)
    await model.predict([{"role": "user", "content": [
        {"type": "text", "text": "summarize"},
        {"type": "image_url", "image_url": {"url": f"data:application/pdf;base64,{pdf}"}},
    ]}])
    parts = models.calls[0]["contents"][0]["parts"]
    assert parts[1] == {"inline_data": {"mime_type": "application/pdf", "data": b"%PDF-1.7"}}


@pytest.mark.asyncio
async def test_predict_skips_malformed_data_url():
    models = _FakeModels(response=_response("ok"))
    model = _loaded_model("gemini-3.8-flash", models)
    await model.predict([{"role": "user", "content": [
        {"type": "text", "text": "hi"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,@@not-base64@@"}},
        {"type": "image_url", "image_url": {"url": "https://example.com/a.png"}},
    ]}])
    assert models.calls[0]["contents"][0]["parts"] == [{"text": "hi"}]


@pytest.mark.asyncio
async def test_predict_rejects_message_list_without_content():
    model = _loaded_model("gemini-3.8-flash", _FakeModels(response=_response("unused")))
    with pytest.raises(ValueError, match="No user or assistant content"):
        await model.predict([{"role": "system", "content": "only system"}])


@pytest.mark.asyncio
async def test_generate_response_ignores_thought_parts():
    models = _FakeModels(response=_response("answer", thought_texts=("private reasoning",)))
    model = _loaded_model("gemini-3.8-flash", models)
    assert await model.generate_response("question", max_tokens=50) == "answer"
    assert models.calls[0]["contents"] == "question"
    assert models.calls[0]["config"]["max_output_tokens"] == 50
    assert "system_instruction" not in models.calls[0]["config"]


@pytest.mark.asyncio
async def test_generate_response_sends_context_system_prompt_as_system_instruction():
    models = _FakeModels(response=_response("answer"))
    model = _loaded_model("gemini-3.8-flash", models)
    await model.generate_response("question", context={"system_prompt": "be terse"}, max_tokens=50)
    assert models.calls[0]["contents"] == "question"
    assert models.calls[0]["config"]["system_instruction"] == "be terse"


@pytest.mark.asyncio
async def test_generate_response_ignores_empty_context_system_prompt():
    models = _FakeModels(response=_response("answer"))
    model = _loaded_model("gemini-3.8-flash", models)
    await model.generate_response("question", context={"system_prompt": ""}, max_tokens=50)
    assert "system_instruction" not in models.calls[0]["config"]


@pytest.mark.asyncio
async def test_generate_response_returns_partial_text_on_max_tokens():
    model = _loaded_model("gemini-3.8-flash", _FakeModels(response=_response("partial", finish="MAX_TOKENS")))
    assert await model.generate_response("question", max_tokens=5) == "partial"


@pytest.mark.asyncio
async def test_generate_response_raises_when_max_tokens_leaves_no_text():
    model = _loaded_model("gemini-3.8-flash", _FakeModels(response=_response(finish="MAX_TOKENS", thought_texts=("x",))))
    with pytest.raises(RuntimeError, match="truncated at max tokens"):
        await model.generate_response("question", max_tokens=5)


@pytest.mark.asyncio
async def test_generate_response_raises_on_safety_block():
    rating = SimpleNamespace(
        category=SimpleNamespace(name="HARM_CATEGORY_DANGEROUS_CONTENT"),
        probability=SimpleNamespace(name="HIGH"),
    )
    model = _loaded_model(
        "gemini-3.8-flash",
        _FakeModels(response=_response(finish="SAFETY", safety_ratings=(rating,))),
    )
    with pytest.raises(RuntimeError, match="HARM_CATEGORY_DANGEROUS_CONTENT: HIGH"):
        await model.generate_response("question")


@pytest.mark.asyncio
async def test_generate_response_reports_blocked_prompt():
    blocked = SimpleNamespace(
        candidates=[],
        prompt_feedback=SimpleNamespace(block_reason=SimpleNamespace(name="PROHIBITED_CONTENT")),
    )
    model = _loaded_model("gemini-3.8-flash", _FakeModels(response=blocked))
    with pytest.raises(RuntimeError, match="Prompt was blocked by Gemini: PROHIBITED_CONTENT"):
        await model.generate_response("question")


@pytest.mark.asyncio
async def test_generate_response_wraps_sdk_errors():
    class FailingModels(_FakeModels):
        def generate_content(self, *, model, contents, config):
            raise ConnectionError("network down")

    model = _loaded_model("gemini-3.8-flash", FailingModels())
    with pytest.raises(RuntimeError, match="Failed to generate response: network down"):
        await model.generate_response("question")


@pytest.mark.asyncio
async def test_stream_predict_yields_text_chunks_and_skips_empty_ones():
    chunks = [
        _response("Hel"),
        SimpleNamespace(candidates=[], prompt_feedback=None),
        _response(thought_texts=("thinking",)),
        _response("lo"),
    ]
    models = _FakeModels(stream_chunks=chunks)
    model = _loaded_model("gemini-3.8-flash", models)
    received = [text async for text in model.stream_predict("hi")]
    assert received == ["Hel", "lo"]
    assert models.calls[0]["contents"] == "hi"


@pytest.mark.asyncio
async def test_unload_closes_client_and_marks_unloaded():
    model = _loaded_model("gemini-3.8-flash", _FakeModels())
    client = model._client
    await model.unload()
    assert client.closed is True
    assert model._client is None
    assert model.state == ModelState.UNLOADED
