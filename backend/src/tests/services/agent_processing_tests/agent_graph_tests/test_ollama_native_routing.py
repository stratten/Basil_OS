from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import HumanMessage
from langchain_core.tools import StructuredTool

from api.core.models.model_types import ModelCapability
from api.core.models.reasoning import openai_compatible_model as wrapper_module
from api.core.models.reasoning.ollama_native_chat import OllamaContextWindowFilled
from api.core.models.reasoning.openai_compatible_model import OpenAICompatibleModel
from api.services.agent_processing.lifecycle.execution_graph import openai_compatible_langchain_adapter as adapter_module
from api.services.agent_processing.lifecycle.execution_graph.agent_executor_factory import create_langchain_llm
from api.services.agent_processing.lifecycle.execution_graph.llama_cpp_langchain_adapter import LocalModelContextWindowExceeded

TEXT_CHUNKS = [
    {"message": {"role": "assistant", "thinking": "Considering.", "content": "Hel"}, "done": False},
    {"message": {"content": "lo"}, "done": False},
    {"message": {"content": ""}, "done": True, "done_reason": "stop", "prompt_eval_count": 12, "eval_count": 2},
]
FILLED_CHUNKS = [
    {"message": {"content": "partial"}, "done": False},
    {"message": {"content": ""}, "done": True, "done_reason": "length", "prompt_eval_count": 16300, "eval_count": 84},
]


def _failing_openai_client():
    create = MagicMock(side_effect=AssertionError("the OpenAI-compatible path must not run"))
    return SimpleNamespace(api_key="not-needed", chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


def _adapter(**overrides):
    values = {
        "model_name": "local-qwen",
        "model_identifier": "qwen2.5:1.5b",
        "base_url": "http://localhost:11434/v1",
        "max_tokens": 256,
        "context_window": 16384,
        "server_type": "ollama",
    }
    values.update(overrides)
    adapter = adapter_module.OpenAICompatibleLangChainAdapter(**values)
    adapter._client = _failing_openai_client()
    return adapter


def _install(module, monkeypatch, chunks=()):
    calls = []

    async def fake_stream(native_root, body, *, api_key=None, transport=None):
        calls.append({"native_root": native_root, "body": body, "api_key": api_key})
        for chunk in chunks:
            yield chunk

    monkeypatch.setattr(module, "stream_ollama_chat", fake_stream)
    return calls


class TokenRecorder:
    def __init__(self):
        self.tokens = []

    async def on_llm_new_token(self, token, **_kwargs):
        self.tokens.append(token)


def read_file(path: str) -> str:
    """Read a file."""
    return path


def test_no_server_probe_remains():
    assert not hasattr(adapter_module, "resolve_local_server_profile")
    assert not hasattr(wrapper_module, "resolve_local_server_profile")
    assert not hasattr(adapter_module.OpenAICompatibleLangChainAdapter, "aresolve_server_profile")


@pytest.mark.asyncio
async def test_adapter_sends_ollama_requests_to_the_native_api(monkeypatch):
    calls = _install(adapter_module, monkeypatch, TEXT_CHUNKS)
    recorder = TokenRecorder()

    result = await _adapter()._agenerate([HumanMessage(content="hi")], run_manager=recorder)

    message = result.generations[0].message
    assert message.content == "Hello"
    assert message.tool_calls == []
    assert recorder.tokens == ["Considering.", "Hel", "lo"]
    body = calls[0]["body"]
    assert calls[0]["native_root"] == "http://localhost:11434"
    assert calls[0]["api_key"] == "not-needed"
    assert body["model"] == "qwen2.5:1.5b"
    assert body["messages"] == [{"role": "user", "content": "hi"}]
    assert body["options"]["num_ctx"] == 16384
    assert body["options"]["num_predict"] == 256


@pytest.mark.asyncio
async def test_adapter_converts_native_tool_calls(monkeypatch):
    chunks = [
        {
            "message": {"content": "", "tool_calls": [{"function": {"name": "read_file", "arguments": {"path": "/tmp/a.txt"}}}]},
            "done": True,
        }
    ]
    calls = _install(adapter_module, monkeypatch, chunks)
    bound = _adapter().bind_tools([StructuredTool.from_function(read_file)])

    result = await bound._agenerate([HumanMessage(content="read it")])

    assert bound.context_window == 16384
    message = result.generations[0].message
    assert [call["name"] for call in message.tool_calls] == ["read_file"]
    assert message.tool_calls[0]["args"] == {"path": "/tmp/a.txt"}
    assert [tool["function"]["name"] for tool in calls[0]["body"]["tools"]] == ["read_file"]
    assert "tool_choice" not in calls[0]["body"]


@pytest.mark.asyncio
async def test_adapter_raises_a_context_overflow_when_ollama_fills_the_window(monkeypatch):
    _install(adapter_module, monkeypatch, FILLED_CHUNKS)

    with pytest.raises(LocalModelContextWindowExceeded) as raised:
        await _adapter()._agenerate([HumanMessage(content="hi")])

    assert (raised.value.actual_tokens, raised.value.max_tokens) == (16384, 16384)


@pytest.mark.asyncio
@pytest.mark.parametrize("server_type", ["openai_compatible", "", None])
async def test_adapter_keeps_the_openai_path_unless_ollama_is_chosen(monkeypatch, server_type):
    calls = _install(adapter_module, monkeypatch)

    async def _stream():
        yield {"choices": [{"delta": {"content": "plain"}}]}

    adapter = _adapter(server_type=server_type or "openai_compatible")
    adapter._client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=MagicMock(return_value=_stream()))))

    result = await adapter._agenerate([HumanMessage(content="hi")])

    assert result.generations[0].message.content == "plain"
    assert calls == []


@pytest.mark.asyncio
async def test_adapter_reports_only_the_configured_context_window():
    assert await _adapter(context_window=32768).aresolve_effective_context_window() == 32768
    assert await _adapter(context_window=32768, server_type="openai_compatible").aresolve_effective_context_window() == 32768
    assert await _adapter(context_window=0).aresolve_effective_context_window() is None


def _coordinator_for(config, monkeypatch, server_type):
    monkeypatch.setattr(
        "api.core.models.reasoning.model_runtime_profile.get_model",
        lambda model_id: config if model_id == "local-qwen" else None,
    )
    model = OpenAICompatibleModel(Path("/tmp"), {ModelCapability.REASONING})
    model.model_name = "local-qwen"
    model.model_identifier = config["model_identifier"]
    model.base_url = config["base_url"]
    model.api_key = None
    model.max_context_length = config["context_window"]
    model.max_output_tokens = config["max_output_tokens"]
    model.server_type = server_type
    model._async_client = MagicMock()
    coordinator = MagicMock()
    coordinator._llm_model = model
    return coordinator


@pytest.mark.parametrize("server_type", ["openai_compatible", "ollama"])
def test_factory_copies_the_configured_context_window_and_server_type(monkeypatch, server_type):
    config = {
        "model_id": "local-qwen",
        "handler": "openai_compatible",
        "base_url": "https://qwen35.example/v1",
        "model_identifier": "Qwen3.5-32B-Instruct",
        "context_window": 131072,
        "max_output_tokens": 8192,
        "capabilities": ["reasoning", "function_calling"],
        "features": ["streaming", "system_prompts", "function_calling"],
        "location": "cloud",
        "provider": "custom",
    }

    adapter = create_langchain_llm(_coordinator_for(config, monkeypatch, server_type))

    assert adapter.context_window == 131072
    assert adapter.server_type == server_type


def _wrapper(*, supports_streaming=True, server_type="ollama"):
    model = OpenAICompatibleModel(Path("/tmp"), {ModelCapability.REASONING})
    model.model_name = "local-qwen"
    model.model_identifier = "qwen2.5:1.5b"
    model.base_url = "http://localhost:11434/v1"
    model.api_key = None
    model.temperature = 0.2
    model.max_context_length = 16384
    model.max_output_tokens = 512
    model.supports_streaming = supports_streaming
    model.supports_system_prompts = True
    model.server_type = server_type
    model._async_client = _failing_openai_client()
    return model


def test_wrapper_defaults_to_the_openai_path():
    assert OpenAICompatibleModel(Path("/tmp"), {ModelCapability.REASONING}).server_type == "openai_compatible"


@pytest.mark.asyncio
async def test_wrapper_generates_through_the_native_api(monkeypatch):
    calls = _install(wrapper_module, monkeypatch, TEXT_CHUNKS)

    text = await _wrapper().generate_response("Summarize", context={"system_prompt": "Be brief."})

    assert text == "Hello"
    body = calls[0]["body"]
    assert calls[0]["native_root"] == "http://localhost:11434"
    assert calls[0]["api_key"] is None
    assert body["messages"] == [
        {"role": "system", "content": "Be brief."},
        {"role": "user", "content": "Summarize"},
    ]
    assert body["options"] == {"num_ctx": 16384, "num_predict": 512, "temperature": 0.2}


@pytest.mark.asyncio
async def test_wrapper_streams_through_the_native_api(monkeypatch):
    calls = _install(wrapper_module, monkeypatch, TEXT_CHUNKS)

    pieces = [piece async for piece in _wrapper().generate_response_stream("Summarize", max_tokens=128)]

    assert pieces == ["Hel", "lo"]
    assert calls[0]["body"]["options"]["num_predict"] == 128
    assert calls[0]["body"]["options"]["num_ctx"] == 16384


@pytest.mark.asyncio
async def test_wrapper_raises_when_ollama_fills_the_window(monkeypatch):
    _install(wrapper_module, monkeypatch, FILLED_CHUNKS)

    with pytest.raises(OllamaContextWindowFilled) as raised:
        await _wrapper().generate_response("Summarize")

    assert (raised.value.used_tokens, raised.value.num_ctx) == (16384, 16384)
    assert "qwen2.5:1.5b" in str(raised.value)


@pytest.mark.asyncio
async def test_wrapper_keeps_the_openai_path_for_other_servers(monkeypatch):
    calls = _install(wrapper_module, monkeypatch)
    model = _wrapper(server_type="openai_compatible")
    response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="plain"))])
    model._async_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock(return_value=response))))

    assert await model.generate_response("Summarize") == "plain"
    assert calls == []
