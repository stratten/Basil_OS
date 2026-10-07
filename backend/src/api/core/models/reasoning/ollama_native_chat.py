"""Ollama's native chat API, used when a custom model's ``server_type`` is ``ollama`` so the configured context window reaches Ollama as ``num_ctx``."""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any, AsyncIterator, Dict, List, Optional
from urllib.parse import urlparse, urlunparse

import httpx

logger = logging.getLogger(__name__)

SERVER_TYPE_OLLAMA = "ollama"
OLLAMA_CHAT_TIMEOUT = httpx.Timeout(connect=5.0, read=600.0, write=60.0, pool=5.0)
NO_API_KEY_VALUES = frozenset({"", "not-needed", "none", "ollama", "lm-studio"})


def _positive(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def uses_ollama_native_chat(server_type: Any) -> bool:
    return str(server_type or "").strip().lower() == SERVER_TYPE_OLLAMA


def ollama_native_root(base_url: str) -> str:
    """``http://host:11434/v1`` becomes ``http://host:11434``; the native API lives beside the OpenAI-compatible one."""
    parsed = urlparse(str(base_url or "").strip())
    path = parsed.path.rstrip("/")
    if path.endswith("/v1"):
        path = path[: -len("/v1")]
    return urlunparse((parsed.scheme, parsed.netloc, path, "", "", "")).rstrip("/")


def openai_messages_to_ollama(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    names_by_id: Dict[str, str] = {}
    converted: List[Dict[str, Any]] = []
    for message in messages:
        role = str(message.get("role") or "user")
        content = message.get("content")
        text = content if isinstance(content, str) else ("" if content is None else json.dumps(content, default=str))
        entry: Dict[str, Any] = {"role": role, "content": text}
        if role == "assistant" and message.get("tool_calls"):
            calls: List[Dict[str, Any]] = []
            for call in message["tool_calls"]:
                function = call.get("function") or {}
                name = str(function.get("name") or "")
                names_by_id[str(call.get("id") or "")] = name
                arguments = function.get("arguments")
                if isinstance(arguments, str):
                    try:
                        arguments = json.loads(arguments) if arguments.strip() else {}
                    except ValueError:
                        arguments = {"raw": arguments}
                calls.append({"function": {"name": name, "arguments": arguments if isinstance(arguments, dict) else {}}})
            entry["tool_calls"] = calls
        if role == "tool":
            name = names_by_id.get(str(message.get("tool_call_id") or ""))
            if name:
                entry["tool_name"] = name
        converted.append(entry)
    return converted


def build_ollama_chat_body(call_kwargs: Dict[str, Any], num_ctx: Optional[int]) -> Dict[str, Any]:
    options: Dict[str, Any] = {}
    if _positive(num_ctx):
        options["num_ctx"] = int(num_ctx)
    if _positive(call_kwargs.get("max_tokens")):
        options["num_predict"] = int(call_kwargs["max_tokens"])
    if call_kwargs.get("temperature") is not None:
        options["temperature"] = float(call_kwargs["temperature"])
    if call_kwargs.get("stop"):
        options["stop"] = list(call_kwargs["stop"])
    body: Dict[str, Any] = {
        "model": call_kwargs["model"],
        "messages": openai_messages_to_ollama(list(call_kwargs.get("messages") or [])),
        "stream": True,
        "options": options,
    }
    if call_kwargs.get("tools"):
        body["tools"] = list(call_kwargs["tools"])
    return body


def ollama_tool_calls_to_openai(calls: Any) -> List[Dict[str, Any]]:
    converted: List[Dict[str, Any]] = []
    for call in calls or []:
        function = call.get("function") if isinstance(call, dict) else None
        if not isinstance(function, dict) or not function.get("name"):
            continue
        arguments = function.get("arguments")
        arguments_text = arguments if isinstance(arguments, str) else json.dumps(arguments if isinstance(arguments, dict) else {})
        converted.append(
            {
                "id": str(call.get("id") or f"call_{uuid.uuid4().hex[:12]}"),
                "type": "function",
                "function": {"name": str(function["name"]), "arguments": arguments_text},
            }
        )
    return converted


def ollama_context_tokens_used(final_chunk: Dict[str, Any], num_ctx: Optional[int], num_predict: Optional[int]) -> Optional[int]:
    """Tokens used when a finished call filled the context window, else None.

    Ollama never reports an overflow: it truncates the prompt or shifts the context and carries on. A filled window shows up as prompt plus output tokens reaching ``num_ctx``, or as a ``length`` stop before ``num_predict`` was reached.
    """
    window = _positive(num_ctx)
    if not window:
        return None
    prompt_tokens = _positive(final_chunk.get("prompt_eval_count")) or 0
    output_tokens = _positive(final_chunk.get("eval_count")) or 0
    used = prompt_tokens + output_tokens
    if used >= window:
        return used
    limit = _positive(num_predict)
    if final_chunk.get("done_reason") == "length" and limit and output_tokens < limit:
        return max(used, window)
    return None


class OllamaContextWindowFilled(RuntimeError):
    """The wording matches the model-error classifier's context-window overflow markers."""

    def __init__(self, used_tokens: int, num_ctx: int, model_identifier: str) -> None:
        super().__init__(
            f"Ollama model {model_identifier} filled its context window: maximum context length is {num_ctx} tokens, but the request resulted in {used_tokens} tokens."
        )
        self.used_tokens = used_tokens
        self.num_ctx = num_ctx


class OllamaChatError(RuntimeError):
    def __init__(self, message: str, status_code: Optional[int] = None) -> None:
        super().__init__(message)
        self.status_code = status_code


async def stream_ollama_chat(
    native_root: str,
    body: Dict[str, Any],
    *,
    api_key: Optional[str] = None,
    transport: Any = None,
) -> AsyncIterator[Dict[str, Any]]:
    """Yield each NDJSON chunk from ``POST {root}/api/chat``; HTTP and in-stream errors raise ``OllamaChatError``."""
    headers = {"Content-Type": "application/json"}
    if api_key and str(api_key).strip().lower() not in NO_API_KEY_VALUES:
        headers["Authorization"] = f"Bearer {api_key}"
    async with httpx.AsyncClient(timeout=OLLAMA_CHAT_TIMEOUT, transport=transport) as client:
        async with client.stream("POST", f"{native_root}/api/chat", json=body, headers=headers) as response:
            if response.status_code >= 400:
                detail = (await response.aread()).decode("utf-8", errors="replace")[:500]
                raise OllamaChatError(
                    f"Ollama /api/chat returned HTTP {response.status_code} {response.reason_phrase}: {detail}",
                    status_code=response.status_code,
                )
            async for line in response.aiter_lines():
                line = line.strip()
                if not line:
                    continue
                try:
                    chunk = json.loads(line)
                except ValueError:
                    logger.debug("Skipping a malformed Ollama stream line: %s", line[:200])
                    continue
                if not isinstance(chunk, dict):
                    continue
                if chunk.get("error"):
                    raise OllamaChatError(f"Ollama error: {chunk['error']}")
                yield chunk
