"""
LangChain Adapter for LlamaCppModel

Provides a LangChain-compatible chat model that wraps a local llama.cpp model,
enabling tool calling support for the LangChain agent pipeline.

Follows the same pattern as auth_proxy_langchain_adapter.py but calls
llama-cpp-python's create_chat_completion() directly instead of routing
through an HTTP service.

Key features:
- Full bind_tools() support for LangChain tool-calling agents
- Uses llama-cpp-python's native tools/tool_choice parameters
- Async execution via asyncio.to_thread() (blocking llama.cpp calls)
- Robust JSON parsing for tool call arguments (shared with AuthProxy adapter)
"""

import asyncio
import json
import logging
import os
import re
import time
import threading
import uuid
from typing import Any, Callable, Dict, List, Optional, Union

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import BaseTool
from pydantic import Field, PrivateAttr

from api.core.models.reasoning.mlx_prompt_cache import PromptCacheStats
from api.core.models.reasoning.model_runtime_profile import (
    TOOL_RENDERING_SLIM_TEXT_CATALOG,
    RuntimeModelProfile,
    resolve_runtime_model_profile,
    resolve_tool_call_format_for,
    resolve_tool_rendering_for,
)
from .conversation_turns import turn_input_index
from .model_errors import TransientModelError
from .local_tool_call_parser import (
    extract_text_tool_calls,
    parse_structured_tool_calls,
    strip_think_sections,
)
from .slim_catalog_renderer import (
    SLIM_CATALOG_OPEN_TAG,
    parse_slim_catalog_tool_calls,
    render_slim_catalog_preamble,
)
from api.core.models.reasoning.local_model_failure import LocalModelDecodeError, parse_decode_failure

logger = logging.getLogger(__name__)


class LocalModelGenerationStalled(TransientModelError):
    """The local model stopped emitting tokens mid-generation for longer than the stall limit."""


class LocalModelContextWindowExceeded(RuntimeError):
    """A local llama.cpp prompt does not fit the model's context window.

    Carries the actual/max token counts as integers, computed live from the
    model's own tokenizer (``Llama.tokenize``) and its own ``Llama.n_ctx()``
    -- never parsed from llama.cpp's ``ValueError`` text, whose exact wording
    is an internal implementation detail, not a contract Basil owns.

    Deliberately subclasses ``RuntimeError`` rather than ``ValueError`` so ``classify_model_error`` never mistakes it for the unrelated "No generation chunks were returned" ``ValueError``.
    """

    def __init__(self, actual_tokens: int, max_tokens: int) -> None:
        super().__init__(
            f"Local model prompt requires {actual_tokens} tokens, "
            f"exceeding its {max_tokens} token context window."
        )
        self.actual_tokens = actual_tokens
        self.max_tokens = max_tokens


def _emit_runtime_trace(event: str, **fields: Any) -> None:
    """Emit opt-in, prompt-free timing data for adapter-managed native streams."""
    if os.getenv("BASIL_LOCAL_RUNTIME_TRACE") != "1":
        return
    logger.warning(
        "LOCAL_RUNTIME_TRACE %s",
        json.dumps(
            {"event": event, "monotonic_seconds": time.monotonic(), **fields},
            sort_keys=True,
        ),
    )


def _last_prompt_stats(llama_instance: Any) -> Optional[PromptCacheStats]:
    """How the engine's prompt cache served its latest call, or None for engines that report nothing."""
    stats = getattr(llama_instance, "last_prompt_stats", None)
    return stats if isinstance(stats, PromptCacheStats) else None


def _prompt_cache_trace_fields(stats: Optional[PromptCacheStats]) -> Dict[str, Any]:
    """Trace fields describing how the engine's prompt cache served one call. Empty when there are none."""
    if stats is None:
        return {}
    return {
        "prompt_cache_path": stats.path,
        "prompt_tokens": stats.prompt_tokens,
        "prompt_cache_reused_tokens": stats.reused_tokens,
        "prompt_cache_prefill_tokens": stats.prefill_tokens,
        "prompt_tokens_per_second": stats.prompt_tps,
        "generation_tokens_per_second": stats.generation_tps,
    }


class _ReplyTally:
    """Tallies how much of one streamed reply is thinking and how much is the answer, from the text alone."""

    def __init__(self) -> None:
        self._reasoning_chars = 0
        self._content_parts: List[str] = []

    def add(self, chunk: Any) -> None:
        try:
            delta = chunk["choices"][0].get("delta") or {}
        except (KeyError, IndexError, TypeError, AttributeError):
            return
        reasoning = delta.get("reasoning_content")
        if isinstance(reasoning, str):
            self._reasoning_chars += len(reasoning)
        content = delta.get("content")
        if isinstance(content, str):
            self._content_parts.append(content)

    def thinking_and_answer_chars(self) -> tuple[int, int]:
        text = "".join(self._content_parts)
        end = text.find("</think>")
        if end >= 0:
            return self._reasoning_chars + end, len(text) - end - len("</think>")
        if text.lstrip().startswith("<think>"):
            return self._reasoning_chars + len(text), 0
        return self._reasoning_chars, len(text)


def describe_model_call(
    *,
    native_seconds: float,
    chunk_count: int,
    stopped: bool,
    stats: Optional[PromptCacheStats],
    tally: _ReplyTally,
) -> str:
    """One prompt-free line saying where a model call's time went: reading the prompt, thinking, or answering."""

    def number(value: Optional[float], spec: str) -> str:
        return "n/a" if value is None else format(value, spec)

    thinking_chars, answer_chars = tally.thinking_and_answer_chars()
    fields = [
        f"seconds={native_seconds:.1f}",
        f"chunks={chunk_count}",
        f"stopped={str(stopped).lower()}",
        f"thinking_chars={thinking_chars}",
        f"answer_chars={answer_chars}",
    ]
    if stats is not None:
        fields[1:1] = [
            f"first_token_seconds={number(stats.first_token_seconds, '.1f')}",
            f"prompt_tokens={stats.prompt_tokens}",
            f"reused_tokens={stats.reused_tokens}",
            f"prefill_tokens={stats.prefill_tokens}",
            f"prefill_tps={number(stats.prompt_tps, '.0f')}",
            f"completion_tokens={stats.generation_tokens}",
            f"decode_tps={number(stats.generation_tps, '.1f')}",
        ]
    return "[ModelCall] " + " ".join(fields)


def _message_plain_text(message: BaseMessage) -> str:
    """Flatten a message's content and tool_calls to plain text for token
    counting. Not the exact rendering llama.cpp's chat template produces --
    the goal is a close, real-tokenizer estimate for a trim decision, not a
    byte-exact prompt reconstruction.
    """
    parts = [str(message.content or "")]
    tool_calls = getattr(message, "tool_calls", None)
    if tool_calls:
        parts.append(json.dumps(tool_calls, default=str))
    return "\n".join(parts)


def _converted_message_plain_text(message: Dict[str, Any]) -> str:
    """Same flattening as ``_message_plain_text`` for already-converted
    OpenAI-format dict messages (used post ``_convert_messages``)."""
    parts = [str(message.get("content") or "")]
    if message.get("tool_calls"):
        parts.append(json.dumps(message["tool_calls"], default=str))
    return "\n".join(parts)


def _count_tokens(llama_instance: Any, text: str) -> int:
    """Real token count from the model's own tokenizer. Falls back to a
    conservative char/4 estimate only if the native call itself errors, so a
    tokenizer failure can never crash the trim/detection path it supports."""
    if not text:
        return 0
    try:
        return len(llama_instance.tokenize(text.encode("utf-8", errors="ignore"), add_bos=False))
    except Exception:
        return max(1, len(text) // 4)


def _estimate_prompt_tokens(llama_instance: Any, messages: List[Dict[str, Any]], tools: Any = None) -> Optional[int]:
    """Token count of the request about to be read, for progress display only. The chat template adds a little, so callers present it as approximate."""
    try:
        text = "\n".join(_converted_message_plain_text(message) for message in messages)
        if tools:
            text += "\n" + json.dumps(tools, default=str)
        return _count_tokens(llama_instance, text)
    except Exception:
        return None


def with_unique_tool_call_ids(tool_calls: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Give every parsed tool call an id no other call in the run shares.

    The local parsers number calls by position within one reply, so a model that makes one call per reply produced the same id on every turn, and anything that pairs results to calls by id kept only the last result. Cloud providers and Ollama already issue a fresh id per call; the readable prefix is kept so logs still show which tool the id belongs to.
    """
    return [{**call, "id": f"{call.get('id') or 'call'}_{uuid.uuid4().hex[:8]}"} for call in tool_calls]


_CONTEXT_TRIM_TOKEN_MARGIN = 512


def _group_turns(messages: List[BaseMessage]) -> List[List[BaseMessage]]:
    """Each non-tool message plus the ToolMessages that directly answer it form one atomic turn."""
    turns: List[List[BaseMessage]] = []
    cursor = 0
    while cursor < len(messages):
        turn = [messages[cursor]]
        cursor += 1
        while cursor < len(messages) and isinstance(messages[cursor], ToolMessage):
            turn.append(messages[cursor])
            cursor += 1
        turns.append(turn)
    return turns


def _turn_tokens(llama_instance: Any, turn: List[BaseMessage]) -> int:
    return sum(_count_tokens(llama_instance, _message_plain_text(m)) for m in turn)


def _keep_newest_turns(
    llama_instance: Any,
    turns: List[List[BaseMessage]],
    available_tokens: int,
    *,
    keep_at_least_one: bool,
) -> List[List[BaseMessage]]:
    kept: List[List[BaseMessage]] = []
    used = 0
    for turn in reversed(turns):
        cost = _turn_tokens(llama_instance, turn)
        if used + cost > available_tokens and (kept or not keep_at_least_one):
            break
        kept.append(turn)
        used += cost
    kept.reverse()
    return kept


def _omitted_turns_marker(dropped_count: int) -> AIMessage:
    return AIMessage(
        content=(
            f"[{dropped_count} earlier tool-call turn(s) omitted here to fit the "
            "model's context window. Continue from the remaining history below.]"
        )
    )


def compact_scratchpad_for_context_window(
    llama_instance: Any,
    messages: List[BaseMessage],
    max_generation_tokens: int,
) -> List[BaseMessage]:
    """Drop the oldest complete tool-call turns until the prompt fits.

    Leading SystemMessages are always kept. When the conversation carries a
    marked current request (a follow-up seeded with earlier turns), that
    request is pinned, the current turn's newest steps are kept first (at
    least one), and earlier turns are kept only while they still fit.
    Otherwise the first HumanMessage is pinned and the newest turns are kept,
    as before. A tool call is never separated from its response, and one
    marker message replaces everything dropped.
    """
    if not messages:
        return messages

    budget = llama_instance.n_ctx() - max_generation_tokens - _CONTEXT_TRIM_TOKEN_MARGIN
    if budget <= 0:
        budget = llama_instance.n_ctx() // 2

    head: List[BaseMessage] = []
    idx = 0
    while idx < len(messages) and isinstance(messages[idx], SystemMessage):
        head.append(messages[idx])
        idx += 1

    pinned_index = turn_input_index(messages)
    if pinned_index is not None and pinned_index >= idx:
        prior_turns = _group_turns(messages[idx:pinned_index])
        current_head = [messages[pinned_index]]
        current_turns = _group_turns(messages[pinned_index + 1:])
        head_tokens = _turn_tokens(llama_instance, head + current_head)
        kept_current = _keep_newest_turns(
            llama_instance, current_turns, budget - head_tokens, keep_at_least_one=True
        )
        kept_prior: List[List[BaseMessage]] = []
        if len(kept_current) == len(current_turns):
            current_tokens = sum(_turn_tokens(llama_instance, turn) for turn in kept_current)
            kept_prior = _keep_newest_turns(
                llama_instance, prior_turns, budget - head_tokens - current_tokens, keep_at_least_one=False
            )
        dropped_count = (len(prior_turns) - len(kept_prior)) + (len(current_turns) - len(kept_current))
        if dropped_count == 0:
            return messages
        return (
            head
            + [_omitted_turns_marker(dropped_count)]
            + [m for turn in kept_prior for m in turn]
            + current_head
            + [m for turn in kept_current for m in turn]
        )

    if idx < len(messages) and isinstance(messages[idx], HumanMessage):
        head.append(messages[idx])
        idx += 1
    turns = _group_turns(messages[idx:])
    head_tokens = _turn_tokens(llama_instance, head)
    kept = _keep_newest_turns(llama_instance, turns, budget - head_tokens, keep_at_least_one=True)
    dropped_count = len(turns) - len(kept)
    if dropped_count == 0:
        return messages
    return head + [_omitted_turns_marker(dropped_count)] + [m for turn in kept for m in turn]


def _detect_context_window_overflow(
    llama_instance: Any,
    converted_messages: List[Dict[str, Any]],
) -> Optional[tuple[int, int]]:
    """Independently recompute prompt size against the model's own context
    window, rather than parsing whatever wording llama.cpp's own ValueError
    happens to use. Returns (actual_tokens, max_tokens) when the prompt is at
    or over budget, else None.
    """
    try:
        max_tokens = llama_instance.n_ctx()
    except Exception:
        return None
    combined_text = "\n".join(
        _converted_message_plain_text(msg) for msg in converted_messages
    )
    actual_tokens = _count_tokens(llama_instance, combined_text)
    if actual_tokens >= max_tokens:
        return actual_tokens, max_tokens
    return None


class LlamaCppLangChainAdapter(BaseChatModel):
    """LangChain chat model that wraps a local llama.cpp model with tool calling.

    Accepts a loaded LlamaCppModel instance and delegates to its underlying
    llama_cpp.Llama object for chat completions, passing tools in OpenAI format.
    """

    model_name: str = Field(default="llama.cpp", description="Model display name")
    temperature: float = Field(default=0.1, description="Sampling temperature")
    max_tokens: int = Field(default=4096, description="Maximum tokens to generate")
    context_window: int = Field(default=32768, description="Model context window size")
    top_p: float = Field(default=0.95, description="Nucleus sampling probability")
    top_k: int = Field(default=40, description="Top-k sampling limit")
    min_p: Optional[float] = Field(default=None, description="Optional minimum probability")
    repeat_penalty: float = Field(default=1.15, description="Repetition penalty")
    reasoning_mode: str = Field(default="tagged", description="Local reasoning marker mode")

    _llama_instance: Any = None  # llama_cpp.Llama object
    # The LlamaCppModel that owns the native context. It lets a failed decode reload the context at a smaller size, and keeps this adapter pointed at the live context after any reload.
    _llama_wrapper: Any = None
    _bound_tools: Optional[List[Dict[str, Any]]] = None
    # Plan B.3: the original BaseTool list as bound. Needed so the slim
    # text-catalog renderer can introspect args_schema for signature
    # rendering after bind_tools has already converted to OpenAI dicts.
    # Empty/None when no tools are bound or when the construction layer
    # passed in pre-rendered OpenAI tool dicts directly.
    _bound_tools_raw: Optional[List[Any]] = None
    _activity_callback: Any = None  # Optional[Callable[[int, Optional[str], bool], None]] — (tokens, thinking_text, thinking_complete)
    # Optional[Callable[[str], None]]: called with the tail of everything streamed so far at each heartbeat, whether or not the model wraps its reasoning in think tags. Used by callers that show the model's live output.
    _stream_preview_callback: Any = None
    _native_execution_lock: Any = PrivateAttr(default_factory=threading.RLock)
    # Plan B.2: the active RuntimeModelProfile is threaded through so the
    # adapter can branch on `tool_rendering` for *delivery* (e.g. drop the
    # tools= kwarg under slim_text_catalog and inject a text preamble in
    # B.3). The construction layer has already chosen FULL vs SLIM
    # description/schema by this point; bind_tools() does NOT mutate
    # tool.description or args_schema based on the profile.
    _tool_rendering_profile: Optional[RuntimeModelProfile] = None

    class Config:
        arbitrary_types_allowed = True

    @property
    def _llm_type(self) -> str:
        return "llama_cpp_langchain"

    @property
    def _identifying_params(self) -> Dict[str, Any]:
        return {
            "model_name": self.model_name,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }

    def bind_tools(
        self,
        tools: List[Union[BaseTool, Dict[str, Any]]],
        **kwargs: Any,
    ) -> "LlamaCppLangChainAdapter":
        """Bind tools for use in subsequent calls.

        Creates a new instance with tools bound, following LangChain's
        immutable pattern for tool binding.
        """
        openai_tools = []
        raw_tools: List[Any] = []
        for tool in tools:
            if isinstance(tool, dict):
                openai_tools.append(tool)
                # No raw BaseTool to capture; the slim catalog renderer
                # falls back to a degraded signature for these.
                raw_tools.append(tool)
            elif hasattr(tool, "name") and hasattr(tool, "description"):
                tool_schema = {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description or "",
                        "parameters": self._get_tool_parameters(tool),
                    },
                }
                openai_tools.append(tool_schema)
                raw_tools.append(tool)

        new_instance = LlamaCppLangChainAdapter(
            model_name=self.model_name,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            context_window=self.context_window,
            top_p=self.top_p,
            top_k=self.top_k,
            min_p=self.min_p,
            repeat_penalty=self.repeat_penalty,
            reasoning_mode=self.reasoning_mode,
        )
        new_instance._llama_instance = self._llama_instance
        new_instance._llama_wrapper = self._llama_wrapper
        new_instance._bound_tools = openai_tools
        new_instance._bound_tools_raw = raw_tools
        new_instance._activity_callback = self._activity_callback
        new_instance._stream_preview_callback = self._stream_preview_callback
        new_instance._native_execution_lock = self._native_execution_lock
        # Carry the rendering profile across the bind boundary so the
        # generation path keeps the same delivery decisions the factory made.
        new_instance._tool_rendering_profile = self._tool_rendering_profile

        rendering = resolve_tool_rendering_for(self._tool_rendering_profile)
        logger.info(
            f"Bound {len(openai_tools)} tools to LlamaCppLangChainAdapter "
            f"(tool_rendering={rendering})"
        )
        return new_instance

    # ------------------------------------------------------------------
    # Tool parameter extraction (mirrors AuthProxy adapter)
    # ------------------------------------------------------------------

    def _get_tool_parameters(self, tool: BaseTool) -> Dict[str, Any]:
        if hasattr(tool, "args_schema") and tool.args_schema is not None:
            try:
                schema = tool.args_schema.model_json_schema()
                schema.pop("title", None)
                return schema
            except Exception:
                pass
        return {"type": "object", "properties": {}, "required": []}

    # ------------------------------------------------------------------
    # Message conversion (LangChain -> OpenAI format)
    # ------------------------------------------------------------------

    def _convert_messages(self, messages: List[BaseMessage]) -> List[Dict[str, Any]]:
        converted = []
        for msg in messages:
            if isinstance(msg, SystemMessage):
                converted.append({"role": "system", "content": msg.content})
            elif isinstance(msg, HumanMessage):
                converted.append({"role": "user", "content": msg.content})
            elif isinstance(msg, AIMessage):
                ai_msg: Dict[str, Any] = {"role": "assistant", "content": msg.content or ""}

                if hasattr(msg, "tool_calls") and msg.tool_calls:
                    # A JSON *string* here matches the OpenAI wire format and
                    # llama_cpp's own documented type contract, but every
                    # locally-loaded GGUF's own embedded chat template renders
                    # this by walking `arguments` as an already-parsed mapping
                    # (either unconditionally, per qwen3-coder's crash-on-string
                    # behavior, or conditionally with a silent-drop-on-string
                    # fallback, per qwen3.5/3.6). None of Basil's local models
                    # need the string form, so pass a real dict.
                    ai_msg["tool_calls"] = [
                        {
                            "id": tc.get("id", f"call_{i}"),
                            "type": "function",
                            "function": {
                                "name": tc.get("name", ""),
                                "arguments": tc.get("args", {}),
                            },
                        }
                        for i, tc in enumerate(msg.tool_calls)
                    ]
                elif (
                    hasattr(msg, "additional_kwargs")
                    and msg.additional_kwargs.get("tool_calls")
                ):
                    ai_msg["tool_calls"] = msg.additional_kwargs["tool_calls"]

                converted.append(ai_msg)
            elif isinstance(msg, ToolMessage):
                tool_msg: Dict[str, Any] = {
                    "role": "tool",
                    "tool_call_id": msg.tool_call_id,
                    "content": (
                        msg.content
                        if isinstance(msg.content, str)
                        else json.dumps(msg.content)
                    ),
                }
                if getattr(msg, "name", None):
                    tool_msg["name"] = msg.name
                converted.append(tool_msg)
            else:
                role = getattr(msg, "type", "user")
                if role == "human":
                    role = "user"
                elif role == "ai":
                    role = "assistant"
                converted.append({"role": role, "content": str(msg.content)})
        return converted

    # ------------------------------------------------------------------
    # Generation
    # ------------------------------------------------------------------

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures

                with concurrent.futures.ThreadPoolExecutor() as pool:
                    result = pool.submit(
                        asyncio.run,
                        self._agenerate(messages, stop, run_manager, **kwargs),
                    ).result()
                return result
            else:
                return loop.run_until_complete(
                    self._agenerate(messages, stop, run_manager, **kwargs)
                )
        except RuntimeError:
            return asyncio.run(
                self._agenerate(messages, stop, run_manager, **kwargs)
            )

    _HEARTBEAT_INTERVAL_SECONDS = 5.0
    _STREAM_PREVIEW_CHARS = 4000
    _QUEUE_POLL_SECONDS = 10.0
    _MID_STREAM_STALL_SECONDS = 180.0

    def _follow_wrapper_context(self) -> None:
        """Point this adapter at the wrapper's live native context.

        A decode failure elsewhere can reload the context at a smaller size and close the old one, so an adapter built earlier would otherwise keep a closed handle.
        """
        wrapper = self._llama_wrapper
        live = getattr(wrapper, "llm", None) if wrapper is not None else None
        if live is not None and live is not self._llama_instance:
            self._llama_instance = live
            native_context = getattr(live, "n_ctx", None)
            if callable(native_context):
                self.context_window = int(native_context())

    async def _agenerate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        """Generate a response using the local llama.cpp model with streaming.

        Uses create_chat_completion(stream=True) so that tokens arrive
        incrementally.  A heartbeat callback fires every ~5 seconds to
        reset the model-manager idle timer and (optionally) push progress
        to the frontend.
        """
        if self._llama_instance is None:
            raise RuntimeError("LlamaCpp model not initialized - no Llama instance available")
        self._follow_wrapper_context()

        messages = compact_scratchpad_for_context_window(
            self._llama_instance, messages, self.max_tokens
        )
        converted_messages = self._convert_messages(messages)

        # Plan B.3: under slim_text_catalog, we omit the OpenAI tools=
        # kwarg entirely and instead inject a synthetic SystemMessage
        # preamble at the head of the conversation. The model is expected
        # to emit JSON tool calls inside a <tool_calls>...</tool_calls>
        # block in its content, which we parse below alongside the
        # existing <tool_call> tag fallback.
        active_rendering = resolve_tool_rendering_for(self._tool_rendering_profile)
        active_tool_call_format = resolve_tool_call_format_for(
            self._tool_rendering_profile
        )
        use_slim_catalog = (
            active_rendering == TOOL_RENDERING_SLIM_TEXT_CATALOG
            and bool(self._bound_tools_raw)
        )

        catalog_chars = 0
        if use_slim_catalog:
            preamble = render_slim_catalog_preamble(
                self._bound_tools_raw or [],
                extra_invariants=[
                    "Emit at most one <tool_calls> block per turn.",
                    "If you have enough information to answer, respond with plain text and no <tool_calls> block.",
                ],
            )
            catalog_chars = len(preamble)
            if preamble:
                converted_messages = (
                    [{"role": "system", "content": preamble}] + converted_messages
                )

        call_kwargs: Dict[str, Any] = {
            "messages": converted_messages,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "top_k": self.top_k,
            "repeat_penalty": self.repeat_penalty,
            "stream": True,
        }
        if self.min_p is not None:
            call_kwargs["min_p"] = self.min_p

        if self._bound_tools and not use_slim_catalog:
            call_kwargs["tools"] = self._bound_tools
            call_kwargs["tool_choice"] = "auto"

        if stop:
            call_kwargs["stop"] = stop

        logger.info(
            f"LlamaCpp streaming request: model={self.model_name}, "
            f"messages={len(converted_messages)}, "
            f"tool_rendering={active_rendering}, "
            f"tool_call_format={active_tool_call_format}, "
            f"tools={len(self._bound_tools or []) if not use_slim_catalog else 0}"
            + (f", catalog_chars={catalog_chars}" if use_slim_catalog else "")
        )

        # -- Async bridge: thread pushes chunks, we consume on the event loop --
        queue: asyncio.Queue = asyncio.Queue()
        loop = asyncio.get_running_loop()
        stop_event = threading.Event()
        stream_state: Dict[str, Any] = {
            "phase": "waiting_for_model",
            "phase_started_at": time.monotonic(),
            "prompt_tokens_estimate": None,
        }

        def _stream_attempt(allow_reload: bool, reloaded_to: Optional[int] = None) -> None:
            waiting_at = time.monotonic()
            chunk_count = 0
            try:
                _emit_runtime_trace(
                    "adapter_native_stream_waiting_for_lock",
                    model_name=self.model_name,
                    max_tokens=self.max_tokens,
                    message_count=len(converted_messages),
                    tool_count=len(self._bound_tools or []),
                )
                with self._native_execution_lock:
                    if stop_event.is_set():
                        _emit_runtime_trace(
                            "adapter_native_stream_skipped_after_stop",
                            model_name=self.model_name,
                        )
                        return
                    stream_state["phase"] = "processing_prompt"
                    stream_state["phase_started_at"] = time.monotonic()
                    stream_state["prompt_tokens_estimate"] = _estimate_prompt_tokens(
                        self._llama_instance, converted_messages, call_kwargs.get("tools")
                    )
                    native_started_at = time.monotonic()
                    _emit_runtime_trace(
                        "adapter_native_stream_started",
                        model_name=self.model_name,
                        lock_wait_seconds=native_started_at - waiting_at,
                        max_tokens=self.max_tokens,
                        message_count=len(converted_messages),
                        tool_count=len(self._bound_tools or []),
                    )
                    reply_tally = _ReplyTally()
                    stream = self._llama_instance.create_chat_completion(**call_kwargs)
                    for chunk in stream:
                        if stop_event.is_set():
                            _emit_runtime_trace(
                                "adapter_native_stream_stopped",
                                model_name=self.model_name,
                                chunk_count=chunk_count,
                            )
                            break
                        chunk_count += 1
                        if chunk_count == 1:
                            stream_state["phase"] = "generating"
                            stream_state["phase_started_at"] = time.monotonic()
                            logger.info(
                                "LlamaCpp read the prompt (about %s tokens) in %.1fs before the first token",
                                stream_state.get("prompt_tokens_estimate"),
                                time.monotonic() - native_started_at,
                            )
                            prompt_cache_stats = _last_prompt_stats(self._llama_instance)
                            if prompt_cache_stats is not None:
                                logger.info("[PromptCache] %s", prompt_cache_stats.describe())
                            _emit_runtime_trace(
                                "adapter_native_stream_first_chunk",
                                model_name=self.model_name,
                                first_chunk_seconds=time.monotonic() - native_started_at,
                            )
                        reply_tally.add(chunk)
                        loop.call_soon_threadsafe(queue.put_nowait, chunk)
                    close_stream = getattr(stream, "close", None)
                    if stop_event.is_set() and callable(close_stream):
                        close_stream()
                    logger.info(
                        "%s",
                        describe_model_call(
                            native_seconds=time.monotonic() - native_started_at,
                            chunk_count=chunk_count,
                            stopped=stop_event.is_set(),
                            stats=_last_prompt_stats(self._llama_instance),
                            tally=reply_tally,
                        ),
                    )
                    _emit_runtime_trace(
                        "adapter_native_stream_completed",
                        model_name=self.model_name,
                        native_duration_seconds=time.monotonic() - native_started_at,
                        chunk_count=chunk_count,
                        **_prompt_cache_trace_fields(_last_prompt_stats(self._llama_instance)),
                    )
            except Exception as exc:
                _emit_runtime_trace(
                    "adapter_native_stream_raised",
                    model_name=self.model_name,
                    error_type=type(exc).__name__,
                    chunk_count=chunk_count,
                )
                decode_failure = parse_decode_failure(exc)
                if decode_failure is not None:
                    retried_context: Optional[int] = reloaded_to
                    # Only a failure before the first chunk can be retried: nothing has been streamed, so the whole call can run again.
                    if allow_reload and chunk_count == 0 and self._llama_wrapper is not None:
                        retried_context = self._llama_wrapper._reload_after_memory_failure(decode_failure)
                        if retried_context is not None and self._llama_wrapper.llm is not None:
                            self._llama_instance = self._llama_wrapper.llm
                            self.context_window = retried_context
                            _stream_attempt(False, retried_context)
                            return
                    exc = LocalModelDecodeError(
                        code=decode_failure.code,
                        kind=decode_failure.kind,
                        model_name=self.model_name,
                        n_ctx=self.context_window,
                        retried_at_context=retried_context,
                    )
                # Diagnostic-only: dump the exact request shape that crashed the
                # model's own chat-template rendering, so a failure like this GGUF's
                # Jinja "Can only get item pairs from a mapping" can be reproduced
                # offline against the same messages/tools instead of guessed at.
                try:
                    logger.error(
                        "LlamaCpp create_chat_completion raised %s: %s | "
                        "request_dump messages=%s tools=%s",
                        type(exc).__name__,
                        exc,
                        json.dumps(call_kwargs.get("messages"), default=str),
                        json.dumps(call_kwargs.get("tools"), default=str),
                    )
                except Exception as dump_error:  # pragma: no cover - defensive
                    logger.error(
                        "LlamaCpp create_chat_completion raised %s: %s "
                        "(request dump failed: %s)",
                        type(exc).__name__,
                        exc,
                        dump_error,
                    )
                if isinstance(exc, ValueError):
                    overflow = _detect_context_window_overflow(
                        self._llama_instance, call_kwargs.get("messages") or []
                    )
                    if overflow is not None:
                        actual_tokens, max_tokens = overflow
                        exc = LocalModelContextWindowExceeded(actual_tokens, max_tokens)
                loop.call_soon_threadsafe(queue.put_nowait, exc)

        def _stream_worker() -> None:
            try:
                _stream_attempt(True)
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, None)

        thread_future = loop.run_in_executor(None, _stream_worker)

        # -- Consume streamed chunks --
        content_parts: List[str] = []
        accumulated_tool_calls: Dict[int, Dict[str, Any]] = {}
        tokens_generated = 0
        last_heartbeat = time.time()
        last_chunk_at = time.monotonic()

        try:
            while True:
                try:
                    # asyncio.timeout, not asyncio.wait_for: on Python 3.11 wait_for returns the item and drops a cancellation that lands in the same moment a chunk arrives, which let a canceled request keep generating.
                    async with asyncio.timeout(self._QUEUE_POLL_SECONDS):
                        chunk = await queue.get()
                except TimeoutError:
                    phase = str(stream_state.get("phase") or "generating")
                    silent_for = time.monotonic() - last_chunk_at
                    if phase == "generating" and silent_for >= self._MID_STREAM_STALL_SECONDS:
                        logger.error(
                            "LlamaCpp generation stalled: no chunk for %.0fs after %s token(s)",
                            silent_for,
                            tokens_generated,
                        )
                        raise LocalModelGenerationStalled(
                            f"Local model produced no output for {silent_for:.0f}s mid-generation"
                        )
                    self._fire_heartbeat(
                        tokens_generated,
                        content_parts,
                        phase=phase,
                        prompt_tokens=stream_state.get("prompt_tokens_estimate"),
                        phase_seconds=time.monotonic() - float(stream_state.get("phase_started_at") or time.monotonic()),
                    )
                    continue

                if chunk is None:
                    break
                if isinstance(chunk, Exception):
                    logger.error(f"LlamaCpp streaming error: {chunk}")
                    raise chunk
                last_chunk_at = time.monotonic()

                if "choices" in chunk and chunk["choices"]:
                    delta = chunk["choices"][0].get("delta", {})

                    if delta.get("content"):
                        content_parts.append(delta["content"])
                        tokens_generated += 1

                    for tc_delta in delta.get("tool_calls", []):
                        idx = tc_delta.get("index", 0)
                        if idx not in accumulated_tool_calls:
                            accumulated_tool_calls[idx] = {
                                "id": "",
                                "type": "function",
                                "function": {"name": "", "arguments": ""},
                            }
                        entry = accumulated_tool_calls[idx]
                        if tc_delta.get("id"):
                            entry["id"] = tc_delta["id"]
                        func_delta = tc_delta.get("function", {})
                        if func_delta.get("name"):
                            entry["function"]["name"] = func_delta["name"]
                        if "arguments" in func_delta:
                            entry["function"]["arguments"] += func_delta["arguments"]
                        tokens_generated += 1

                now = time.time()
                if now - last_heartbeat >= self._HEARTBEAT_INTERVAL_SECONDS:
                    self._fire_heartbeat(tokens_generated, content_parts)
                    last_heartbeat = now

            await thread_future
        finally:
            # Covers cancellation, stalls, and stream errors: the worker stops at its next chunk (or right after it gets the native lock) and releases the lock instead of generating for a caller that is gone.
            stop_event.set()

        # Final heartbeat so the idle timer is fully reset after generation
        self._fire_heartbeat(tokens_generated, content_parts)

        # -- Build result using registry-selected tool-call parsers --
        content = "".join(content_parts)

        parse_errors: List[str] = []
        tool_calls: List[Dict[str, Any]] = []

        # Plan B.3: under slim_text_catalog, prefer the <tool_calls> JSON
        # array block. If none is present, fall through to the existing
        # parsers (some models still emit OpenAI deltas or <tool_call>
        # tags by habit).
        if use_slim_catalog and SLIM_CATALOG_OPEN_TAG in content:
            cleaned, slim_calls = parse_slim_catalog_tool_calls(content)
            if slim_calls:
                tool_calls = [
                    {
                        "id": f"slim_call_{i}_{call['name']}",
                        "name": call["name"],
                        "args": call["arguments"],
                    }
                    for i, call in enumerate(slim_calls)
                ]
                content = strip_think_sections(cleaned)

        if not tool_calls:
            # Prefer structured tool_call deltas from the streaming API …
            if accumulated_tool_calls:
                merged_tool_calls = [
                    accumulated_tool_calls[idx]
                    for idx in sorted(accumulated_tool_calls.keys())
                ]
                synthetic_response: Dict[str, Any] = {
                    "choices": [{"message": {"content": content, "tool_calls": merged_tool_calls}}]
                }
                tool_calls, parse_errors = parse_structured_tool_calls(synthetic_response)
                content = strip_think_sections(content)
            else:
                # … but fall back to parsing <tool_call> tags from text content
                # (many local models emit tool calls this way)
                tool_calls, content = extract_text_tool_calls(
                    content, active_tool_call_format
                )
                parse_errors = []

        if parse_errors:
            logger.warning(
                f"Some tool calls had parse errors after repair attempts: {parse_errors}"
            )

        logger.info(
            f"LlamaCpp streaming response: {len(content)} chars, "
            f"{len(tool_calls)} tool calls, ~{tokens_generated} tokens"
            + (f", {len(parse_errors)} parse errors" if parse_errors else "")
        )

        tool_calls = with_unique_tool_call_ids(tool_calls)
        if tool_calls:
            ai_message = AIMessage(
                content=content,
                tool_calls=tool_calls,
                additional_kwargs={
                    "tool_calls": [
                        {
                            "id": tc["id"],
                            "type": "function",
                            "function": {
                                "name": tc["name"],
                                "arguments": json.dumps(tc["args"]),
                            },
                        }
                        for tc in tool_calls
                    ]
                },
            )
        else:
            ai_message = AIMessage(content=content)

        logger.info(
            f"LlamaCpp _agenerate returning ChatResult: "
            f"tool_calls={len(tool_calls)}, content_len={len(content)}, "
            f"msg_type={type(ai_message).__name__}"
        )
        result = ChatResult(generations=[ChatGeneration(message=ai_message)])
        logger.info("LlamaCpp ChatResult constructed, returning to LangChain pipeline")
        return result

    def _fire_heartbeat(
        self,
        tokens_generated: int,
        content_parts: Optional[List[str]] = None,
        phase: str = "generating",
        prompt_tokens: Optional[int] = None,
        phase_seconds: Optional[float] = None,
    ) -> None:
        """Invoke the activity callback and log a content preview.

        Extracts thinking content from ``<think>`` blocks and forwards it
        through the callback so callers (e.g. the heartbeat in
        agent_executor_factory) can stream it to the frontend.
        """
        preview_callback = self._stream_preview_callback
        if preview_callback is not None and content_parts:
            try:
                preview_callback("".join(content_parts)[-self._STREAM_PREVIEW_CHARS:])
            except Exception:
                pass
        if self.reasoning_mode == "none":
            self._invoke_activity_callback(tokens_generated, None, False, phase, prompt_tokens, phase_seconds)
            return
        thinking_text: Optional[str] = None
        thinking_complete = False

        if content_parts:
            full = "".join(content_parts)

            think_match = re.search(r"<think>(.*)", full, re.DOTALL)
            if think_match:
                thinking_text = think_match.group(1)
                end_idx = thinking_text.find("</think>")
                if end_idx != -1:
                    thinking_text = thinking_text[:end_idx]
                    thinking_complete = True
                    after_think = full[full.find("</think>") + len("</think>"):]
                    tail = after_think.strip()[-300:] if after_think.strip() else ""
                    logger.info(
                        f"LlamaCpp stream [{tokens_generated} tokens] "
                        f"[thinking complete, {len(thinking_text)} chars] "
                        f"response tail: {tail or '(generating...)'}"
                    )
                else:
                    logger.info(
                        f"LlamaCpp stream [{tokens_generated} tokens] "
                        f"[thinking…] {thinking_text[-500:]}"
                    )
            else:
                preview = full[-300:] if len(full) > 300 else full
                logger.info(
                    f"LlamaCpp stream [{tokens_generated} tokens]: {preview}"
                )

        self._invoke_activity_callback(tokens_generated, thinking_text, thinking_complete, phase, prompt_tokens, phase_seconds)

    def _invoke_activity_callback(
        self,
        tokens_generated: int,
        thinking_text: Optional[str],
        thinking_complete: bool,
        phase: str,
        prompt_tokens: Optional[int] = None,
        phase_seconds: Optional[float] = None,
    ) -> None:
        callback = self._activity_callback
        if not callback:
            return
        try:
            if getattr(callback, "accepts_prompt_progress", False):
                callback(
                    tokens_generated,
                    thinking_text,
                    thinking_complete,
                    phase=phase,
                    prompt_tokens=prompt_tokens,
                    phase_seconds=phase_seconds,
                )
            elif getattr(callback, "accepts_phase", False):
                callback(tokens_generated, thinking_text, thinking_complete, phase=phase)
            else:
                callback(tokens_generated, thinking_text, thinking_complete)
        except Exception:
            pass


def create_langchain_llm_from_llama_cpp(
    llama_cpp_model: Any,
    activity_callback: Optional[Callable[[int], None]] = None,
    profile: Optional[RuntimeModelProfile] = None,
    purpose: str = "agent_execution",
    requested_output_tokens: Optional[int] = None,
    stream_preview_callback: Optional[Callable[[str], None]] = None,
) -> LlamaCppLangChainAdapter:
    """Create a local LangChain model with one resolved workload budget."""
    from api.core.models.reasoning.streaming_contract import resolve_generation_budget

    if not hasattr(llama_cpp_model, "llm") or llama_cpp_model.llm is None:
        raise RuntimeError(
            "LlamaCppModel is not loaded - call load() before creating LangChain adapter"
        )
    active_profile = profile or resolve_runtime_model_profile(llama_cpp_model)
    budget = resolve_generation_budget(
        llama_cpp_model,
        purpose=purpose,
        requested_output_tokens=requested_output_tokens,
    )
    local_generation = active_profile.local_generation
    sampling = local_generation.get("sampling")
    sampling = sampling if isinstance(sampling, dict) else {}
    context_window = getattr(llama_cpp_model, "max_context_length", 32768) or 32768
    adapter = LlamaCppLangChainAdapter(
        model_name=getattr(getattr(llama_cpp_model, "model_path", None), "stem", "llama.cpp"),
        temperature=float(sampling.get("temperature", 0.1)),
        top_p=float(sampling.get("top_p", 0.95)),
        top_k=int(sampling.get("top_k", 40)),
        min_p=(
            float(sampling["min_p"])
            if isinstance(sampling.get("min_p"), (int, float))
            else None
        ),
        repeat_penalty=float(sampling.get("repeat_penalty", 1.15)),
        reasoning_mode=str(local_generation.get("reasoning_mode", "tagged")),
        max_tokens=budget.effective_output_tokens,
        context_window=int(context_window),
    )
    adapter._llama_instance = llama_cpp_model.llm
    adapter._llama_wrapper = llama_cpp_model
    adapter._native_execution_lock = llama_cpp_model.native_execution_lock
    adapter._activity_callback = activity_callback
    adapter._stream_preview_callback = stream_preview_callback
    adapter._tool_rendering_profile = active_profile
    return adapter
