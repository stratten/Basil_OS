from __future__ import annotations

import json

import httpx
import pytest

from api.core.models.reasoning.ollama_native_chat import (
    OllamaChatError,
    OllamaContextWindowFilled,
    build_ollama_chat_body,
    ollama_context_tokens_used,
    ollama_native_root,
    ollama_tool_calls_to_openai,
    openai_messages_to_ollama,
    stream_ollama_chat,
    uses_ollama_native_chat,
)
from api.services.agent_processing.lifecycle.execution_graph.model_error_policy import (
    CONTEXT_OVERFLOW,
    classify_model_error,
)


def test_native_root_strips_the_openai_suffix():
    assert ollama_native_root("http://localhost:11434/v1") == "http://localhost:11434"
    assert ollama_native_root("http://localhost:11434/v1/") == "http://localhost:11434"
    assert ollama_native_root("http://gpu-box:11434") == "http://gpu-box:11434"
    assert ollama_native_root("https://proxy.example/ollama/v1") == "https://proxy.example/ollama"


@pytest.mark.parametrize(
    ("server_type", "expected"),
    [("ollama", True), ("Ollama ", True), ("openai_compatible", False), (None, False), ("", False), ("lmstudio", False)],
)
def test_only_the_explicit_ollama_server_type_uses_the_native_api(server_type, expected):
    assert uses_ollama_native_chat(server_type) is expected


@pytest.mark.parametrize(
    ("final_chunk", "num_ctx", "num_predict", "expected"),
    [
        ({"prompt_eval_count": 3000, "eval_count": 200, "done_reason": "stop"}, 4096, 512, None),
        ({"prompt_eval_count": 4000, "eval_count": 96, "done_reason": "stop"}, 4096, 512, 4096),
        ({"prompt_eval_count": 4090, "eval_count": 40, "done_reason": "length"}, 4096, 512, 4130),
        ({"prompt_eval_count": 3000, "eval_count": 100, "done_reason": "length"}, 4096, 512, 4096),
        ({"prompt_eval_count": 3000, "eval_count": 512, "done_reason": "length"}, 4096, 512, None),
        ({"prompt_eval_count": 3000, "eval_count": 100, "done_reason": "length"}, 4096, None, None),
        ({"prompt_eval_count": 9000, "eval_count": 10}, None, 512, None),
        ({}, 4096, 512, None),
        ({"prompt_eval_count": "bad", "eval_count": True}, 4096, 512, None),
    ],
)
def test_a_filled_context_window_is_detected(final_chunk, num_ctx, num_predict, expected):
    assert ollama_context_tokens_used(final_chunk, num_ctx, num_predict) == expected


def test_a_filled_window_error_classifies_as_a_context_overflow_with_counts():
    error = OllamaContextWindowFilled(used_tokens=16400, num_ctx=16384, model_identifier="qwen2.5:1.5b")

    classification = classify_model_error(error)

    assert "qwen2.5:1.5b" in str(error)
    assert classification.kind == CONTEXT_OVERFLOW
    assert (classification.actual_tokens, classification.max_tokens) == (16400, 16384)


def test_openai_messages_convert_to_ollama_shape():
    converted = openai_messages_to_ollama(
        [
            {"role": "system", "content": "Be brief."},
            {"role": "user", "content": [{"type": "text", "text": "hi"}]},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {"id": "call-1", "type": "function", "function": {"name": "read_file", "arguments": '{"path": "/tmp/a.txt"}'}},
                    {"id": "call-2", "type": "function", "function": {"name": "list_dir", "arguments": ""}},
                    {"id": "call-3", "type": "function", "function": {"name": "broken", "arguments": "{not json"}},
                ],
            },
            {"role": "tool", "tool_call_id": "call-1", "content": "CODE WORD: amber"},
            {"role": "tool", "tool_call_id": "unknown", "content": "orphan"},
        ]
    )

    assert converted[0] == {"role": "system", "content": "Be brief."}
    assert json.loads(converted[1]["content"]) == [{"type": "text", "text": "hi"}]
    assert converted[2]["content"] == ""
    assert converted[2]["tool_calls"] == [
        {"function": {"name": "read_file", "arguments": {"path": "/tmp/a.txt"}}},
        {"function": {"name": "list_dir", "arguments": {}}},
        {"function": {"name": "broken", "arguments": {"raw": "{not json"}}},
    ]
    assert converted[3] == {"role": "tool", "content": "CODE WORD: amber", "tool_name": "read_file"}
    assert converted[4] == {"role": "tool", "content": "orphan"}


def test_chat_body_carries_num_ctx_and_sampling_options():
    tools = [{"type": "function", "function": {"name": "read_file", "parameters": {"type": "object"}}}]
    body = build_ollama_chat_body(
        {
            "model": "qwen2.5:1.5b",
            "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": 512,
            "temperature": 0.2,
            "stop": ["</done>"],
            "tools": tools,
            "tool_choice": "auto",
            "stream": True,
        },
        num_ctx=16384,
    )

    assert body == {
        "model": "qwen2.5:1.5b",
        "messages": [{"role": "user", "content": "hi"}],
        "stream": True,
        "options": {"num_ctx": 16384, "num_predict": 512, "temperature": 0.2, "stop": ["</done>"]},
        "tools": tools,
    }
    assert "num_ctx" not in build_ollama_chat_body({"model": "m", "messages": []}, num_ctx=None)["options"]


def test_ollama_tool_calls_convert_to_openai_shape():
    converted = ollama_tool_calls_to_openai(
        [
            {"function": {"name": "read_file", "arguments": {"path": "/tmp/a.txt"}}},
            {"id": "given-id", "function": {"name": "list_dir", "arguments": '{"path": "/tmp"}'}},
            {"function": {"arguments": {}}},
            "not a call",
        ]
    )

    assert len(converted) == 2
    assert converted[0]["id"].startswith("call_")
    assert converted[0]["function"] == {"name": "read_file", "arguments": '{"path": "/tmp/a.txt"}'}
    assert converted[1] == {"id": "given-id", "type": "function", "function": {"name": "list_dir", "arguments": '{"path": "/tmp"}'}}


def _ndjson(*chunks):
    return ("\n".join(chunks) + "\n").encode("utf-8")


@pytest.mark.asyncio
async def test_stream_yields_ndjson_chunks_and_skips_noise():
    captured = {}

    def handler(request):
        captured["path"] = request.url.path
        captured["authorization"] = request.headers.get("authorization")
        captured["body"] = json.loads(request.content)
        content = _ndjson(
            json.dumps({"message": {"content": "Hel"}, "done": False}),
            "",
            "{malformed",
            json.dumps(["not", "a", "dict"]),
            json.dumps({"message": {"content": "lo"}, "done": True, "eval_count": 2}),
        )
        return httpx.Response(200, content=content)

    body = {"model": "qwen2.5:1.5b", "messages": [], "stream": True, "options": {"num_ctx": 16384}}
    chunks = [
        chunk
        async for chunk in stream_ollama_chat(
            "http://localhost:11434", body, api_key="not-needed", transport=httpx.MockTransport(handler)
        )
    ]

    assert [chunk["message"]["content"] for chunk in chunks] == ["Hel", "lo"]
    assert captured["path"] == "/api/chat"
    assert captured["authorization"] is None
    assert captured["body"]["options"]["num_ctx"] == 16384


@pytest.mark.asyncio
async def test_stream_sends_a_real_api_key():
    captured = {}

    def handler(request):
        captured["authorization"] = request.headers.get("authorization")
        return httpx.Response(200, content=_ndjson(json.dumps({"done": True})))

    async for _chunk in stream_ollama_chat("http://10.0.0.5:11434", {}, api_key="sk-local", transport=httpx.MockTransport(handler)):
        pass

    assert captured["authorization"] == "Bearer sk-local"


@pytest.mark.asyncio
async def test_stream_raises_on_http_and_in_stream_errors():
    def not_found(request):
        return httpx.Response(404, json={"error": "model 'missing' not found"})

    def stream_error(request):
        return httpx.Response(200, content=_ndjson(json.dumps({"error": "out of memory"})))

    with pytest.raises(OllamaChatError) as http_error:
        async for _chunk in stream_ollama_chat("http://localhost:11434", {}, transport=httpx.MockTransport(not_found)):
            pass
    assert http_error.value.status_code == 404
    assert "HTTP 404 Not Found" in str(http_error.value)
    assert "model 'missing' not found" in str(http_error.value)

    with pytest.raises(OllamaChatError, match="out of memory"):
        async for _chunk in stream_ollama_chat("http://localhost:11434", {}, transport=httpx.MockTransport(stream_error)):
            pass
