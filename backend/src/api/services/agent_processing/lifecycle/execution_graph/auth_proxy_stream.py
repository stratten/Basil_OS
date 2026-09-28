"""SSE streaming consumer for the Basil Auth Service proxy.

Parses the ``text/event-stream`` produced by ``/route/request`` when the client
sends ``stream: true``. It folds the OpenAI-format streaming chunks into a single
accumulator so that :class:`AuthProxyLangChainAdapter` can fire
``on_llm_new_token`` per natural-language delta (which is what surfaces live
reasoning to the frontend) while still assembling a complete final message for
tool-calling agents.

The accumulation logic mirrors the incremental tool-call handling already used by
the llama.cpp adapter, but consumes httpx SSE lines instead of a local generator.
"""

import json
import logging
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Awaitable, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

SSE_DATA_PREFIX = "data: "
SSE_DONE_SENTINEL = "[DONE]"


@dataclass
class StreamAccumulator:
    """Running state assembled from the auth-service SSE stream."""

    content_parts: List[str] = field(default_factory=list)
    tool_calls_by_index: Dict[int, Dict[str, Any]] = field(default_factory=dict)
    input_tokens: int = 0
    output_tokens: int = 0
    request_id: Optional[str] = None
    stream_error: Optional[str] = None

    @property
    def content(self) -> str:
        return "".join(self.content_parts)

    def merged_tool_calls(self) -> List[Dict[str, Any]]:
        """Return accumulated tool calls in stable, index-sorted order."""
        return [self.tool_calls_by_index[i] for i in sorted(self.tool_calls_by_index)]

    def as_openai_response(self) -> Dict[str, Any]:
        """Synthesize a non-streaming OpenAI response for downstream parsing.

        Lets the adapter reuse its existing ``_parse_tool_calls`` (with JSON
        repair) unchanged rather than duplicating tool-call parsing here.
        """
        message: Dict[str, Any] = {"content": self.content}
        merged = self.merged_tool_calls()
        if merged:
            message["tool_calls"] = merged
        return {"choices": [{"message": message}]}


def apply_chunk(acc: StreamAccumulator, chunk: Dict[str, Any]) -> str:
    """Fold one OpenRouter streaming chunk into ``acc``.

    Returns the natural-language content delta from this chunk (may be empty when
    the chunk only carried tool-call arguments or usage metadata).
    """
    if not acc.request_id and chunk.get("id"):
        acc.request_id = chunk["id"]

    usage = chunk.get("usage")
    if isinstance(usage, dict):
        acc.input_tokens = usage.get("prompt_tokens") or acc.input_tokens
        acc.output_tokens = usage.get("completion_tokens") or acc.output_tokens

    choices = chunk.get("choices") or []
    if not choices:
        return ""
    delta = choices[0].get("delta") or {}

    for tc_delta in delta.get("tool_calls") or []:
        index = tc_delta.get("index", 0)
        entry = acc.tool_calls_by_index.setdefault(
            index,
            {"id": "", "type": "function", "function": {"name": "", "arguments": ""}},
        )
        if tc_delta.get("id"):
            entry["id"] = tc_delta["id"]
        func_delta = tc_delta.get("function") or {}
        if func_delta.get("name"):
            entry["function"]["name"] = func_delta["name"]
        if func_delta.get("arguments"):
            entry["function"]["arguments"] += func_delta["arguments"]

    content_delta = delta.get("content") or ""
    if content_delta:
        acc.content_parts.append(content_delta)
    return content_delta


async def consume_auth_proxy_stream(
    lines: AsyncIterator[str],
    on_content_delta: Optional[Callable[[str], Awaitable[None]]] = None,
) -> StreamAccumulator:
    """Consume the auth-service SSE stream, firing ``on_content_delta`` per text delta.

    ``lines`` is an async iterator of raw SSE lines, e.g. the output of
    ``httpx.Response.aiter_lines()``. Content and tool-call deltas are folded into
    the returned :class:`StreamAccumulator`. ``on_content_delta`` is awaited for
    each non-empty natural-language delta so the caller can forward live tokens.
    """
    acc = StreamAccumulator()
    async for raw_line in lines:
        line = (raw_line or "").strip()
        if not line:
            continue

        if not line.startswith(SSE_DATA_PREFIX):
            continue

        data = line[len(SSE_DATA_PREFIX):].strip()
        if data == SSE_DONE_SENTINEL:
            break

        try:
            parsed = json.loads(data)
        except (ValueError, TypeError):
            continue

        if not isinstance(parsed, dict):
            continue

        if parsed.get("error"):
            acc.stream_error = str(parsed.get("error"))
            continue

        content_delta = apply_chunk(acc, parsed)
        if content_delta and on_content_delta is not None:
            await on_content_delta(content_delta)

    return acc
