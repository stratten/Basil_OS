"""LangChain adapter for user-defined OpenAI-compatible endpoints."""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
from typing import Any, Dict, List, Optional, Union

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import BaseTool
from pydantic import Field

from .auth_proxy_stream import StreamAccumulator, apply_chunk
from api.core.models.reasoning.ollama_native_chat import (
    build_ollama_chat_body,
    ollama_context_tokens_used,
    ollama_native_root,
    ollama_tool_calls_to_openai,
    stream_ollama_chat,
    uses_ollama_native_chat,
)
from .llama_cpp_langchain_adapter import LocalModelContextWindowExceeded

from api.core.models.reasoning.model_runtime_profile import (
    TOOL_RENDERING_SLIM_TEXT_CATALOG,
    RuntimeModelProfile,
    resolve_tool_call_format_for,
    resolve_tool_rendering_for,
)
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

logger = logging.getLogger(__name__)


class OpenAICompatibleLangChainAdapter(BaseChatModel):
    """LangChain chat model for custom OpenAI-compatible endpoints."""

    model_name: str = Field(description="Custom model registry ID")
    model_identifier: str = Field(description="Model name sent to the endpoint")
    base_url: str = Field(description="OpenAI-compatible endpoint base URL")
    temperature: float = Field(default=0.7, description="Sampling temperature")
    max_tokens: int = Field(default=4096, description="Maximum tokens to generate")
    tool_rendering: str = Field(default="full_schema", description="Tool rendering mode")
    tool_call_format: str = Field(default="json_tool_call", description="Text tool-call format")
    context_window: int = Field(default=0, description="Configured context window in tokens")
    server_type: str = Field(default="openai_compatible", description="'ollama' routes calls to Ollama's native chat API")

    _client: Any = None
    _bound_tools: Optional[List[Dict[str, Any]]] = None
    _bound_tools_raw: Optional[List[Any]] = None

    class Config:
        arbitrary_types_allowed = True

    @property
    def _llm_type(self) -> str:
        return "openai_compatible_langchain"

    @property
    def _identifying_params(self) -> Dict[str, Any]:
        return {
            "model_name": self.model_name,
            "model_identifier": self.model_identifier,
            "base_url": self.base_url,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }

    def bind_tools(
        self,
        tools: List[Union[BaseTool, Dict[str, Any]]],
        **kwargs: Any,
    ) -> "OpenAICompatibleLangChainAdapter":
        openai_tools: List[Dict[str, Any]] = []
        raw_tools: List[Any] = []
        for tool in tools:
            if isinstance(tool, dict):
                openai_tools.append(tool)
                raw_tools.append(tool)
            elif hasattr(tool, "name") and hasattr(tool, "description"):
                openai_tools.append(
                    {
                        "type": "function",
                        "function": {
                            "name": tool.name,
                            "description": tool.description or "",
                            "parameters": self._get_tool_parameters(tool),
                        },
                    }
                )
                raw_tools.append(tool)

        new_instance = OpenAICompatibleLangChainAdapter(
            model_name=self.model_name,
            model_identifier=self.model_identifier,
            base_url=self.base_url,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            tool_rendering=self.tool_rendering,
            tool_call_format=self.tool_call_format,
            context_window=self.context_window,
            server_type=self.server_type,
        )
        new_instance._client = self._client
        new_instance._bound_tools = openai_tools
        new_instance._bound_tools_raw = raw_tools

        logger.info(
            "Bound %s tools to OpenAICompatibleLangChainAdapter "
            "(tool_rendering=%s, tool_call_format=%s)",
            len(openai_tools),
            self.tool_rendering,
            self.tool_call_format,
        )
        return new_instance

    def _get_tool_parameters(self, tool: BaseTool) -> Dict[str, Any]:
        if hasattr(tool, "args_schema") and tool.args_schema is not None:
            try:
                schema = tool.args_schema.model_json_schema()
                schema.pop("title", None)
                return schema
            except Exception:
                pass
        return {"type": "object", "properties": {}, "required": []}

    async def aresolve_effective_context_window(self) -> Optional[int]:
        """Read by the agent runner to size proactive compaction; always the configured value."""
        return self.context_window if self.context_window > 0 else None

    def _convert_messages(self, messages: List[BaseMessage]) -> List[Dict[str, Any]]:
        converted: List[Dict[str, Any]] = []
        for msg in messages:
            if isinstance(msg, SystemMessage):
                converted.append({"role": "system", "content": msg.content})
            elif isinstance(msg, HumanMessage):
                converted.append({"role": "user", "content": msg.content})
            elif isinstance(msg, AIMessage):
                converted.append(self._convert_ai_message(msg))
            elif isinstance(msg, ToolMessage):
                converted.append(
                    {
                        "role": "tool",
                        "tool_call_id": msg.tool_call_id,
                        "content": (
                            msg.content
                            if isinstance(msg.content, str)
                            else json.dumps(msg.content)
                        ),
                    }
                )
            else:
                role = getattr(msg, "type", "user")
                if role == "human":
                    role = "user"
                elif role == "ai":
                    role = "assistant"
                converted.append({"role": role, "content": str(msg.content)})
        return converted

    def _convert_ai_message(self, msg: AIMessage) -> Dict[str, Any]:
        ai_msg: Dict[str, Any] = {"role": "assistant", "content": msg.content or ""}
        if getattr(msg, "tool_calls", None):
            ai_msg["tool_calls"] = [
                {
                    "id": tc.get("id", f"call_{i}"),
                    "type": "function",
                    "function": {
                        "name": tc.get("name", ""),
                        "arguments": json.dumps(tc.get("args", {})),
                    },
                }
                for i, tc in enumerate(msg.tool_calls)
            ]
        elif getattr(msg, "additional_kwargs", None) and msg.additional_kwargs.get("tool_calls"):
            ai_msg["tool_calls"] = msg.additional_kwargs["tool_calls"]
        return ai_msg

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
                    return pool.submit(
                        asyncio.run,
                        self._agenerate(messages, stop, run_manager, **kwargs),
                    ).result()
            return loop.run_until_complete(self._agenerate(messages, stop, run_manager, **kwargs))
        except RuntimeError:
            return asyncio.run(self._agenerate(messages, stop, run_manager, **kwargs))

    async def _agenerate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        if self._client is None:
            raise RuntimeError("OpenAI-compatible custom model is not loaded")

        converted_messages = self._convert_messages(messages)
        use_slim_catalog = (
            self.tool_rendering == TOOL_RENDERING_SLIM_TEXT_CATALOG
            and bool(self._bound_tools_raw)
        )
        if use_slim_catalog:
            preamble = render_slim_catalog_preamble(
                self._bound_tools_raw or [],
                extra_invariants=[
                    "Emit at most one <tool_calls> block per turn.",
                    "If you have enough information to answer, respond with plain text and no <tool_calls> block.",
                ],
            )
            if preamble:
                converted_messages = [{"role": "system", "content": preamble}] + converted_messages

        call_kwargs: Dict[str, Any] = {
            "model": self.model_identifier,
            "messages": converted_messages,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
        }
        if self._bound_tools and not use_slim_catalog:
            call_kwargs["tools"] = self._bound_tools
            call_kwargs["tool_choice"] = "auto"
        if stop:
            call_kwargs["stop"] = stop
        # Stream so on_llm_new_token fires per delta (drives live reasoning);
        # the deltas are re-accumulated into the same final message the
        # non-streaming path produced, so tool-call parsing below is unchanged.
        call_kwargs["stream"] = True

        logger.info(
            "OpenAI-compatible custom request: model=%s, endpoint=%s, messages=%s, "
            "tool_rendering=%s, tool_call_format=%s, tools=%s",
            self.model_identifier,
            self.base_url,
            len(converted_messages),
            self.tool_rendering,
            self.tool_call_format,
            len(self._bound_tools or []) if not use_slim_catalog else 0,
        )

        if uses_ollama_native_chat(self.server_type):
            content, structured_tool_calls = await self._consume_ollama_native(call_kwargs, run_manager)
        else:
            content, structured_tool_calls = await self._consume_stream(call_kwargs, run_manager)
        tool_calls: List[Dict[str, Any]] = []
        parse_errors: List[str] = []

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

        if not tool_calls and structured_tool_calls:
            synthetic_response = {
                "choices": [
                    {
                        "message": {
                            "content": content,
                            "tool_calls": structured_tool_calls,
                        }
                    }
                ]
            }
            tool_calls, parse_errors = parse_structured_tool_calls(synthetic_response)
            content = strip_think_sections(content)

        if not tool_calls:
            tool_calls, content = extract_text_tool_calls(content, self.tool_call_format)

        if parse_errors:
            logger.warning("OpenAI-compatible custom tool parse errors: %s", parse_errors)

        ai_message = self._build_ai_message(content, tool_calls)
        logger.info(
            "OpenAI-compatible custom response: %s chars, %s tool calls",
            len(content),
            len(tool_calls),
        )
        return ChatResult(generations=[ChatGeneration(message=ai_message)])

    async def _consume_stream(
        self,
        call_kwargs: Dict[str, Any],
        run_manager: Optional[CallbackManagerForLLMRun],
    ) -> tuple[str, List[Dict[str, Any]]]:
        """Consume the SSE completion stream, forwarding live text deltas.

        Awaiting ``on_llm_new_token`` per natural-language delta is what drives the
        LiveProgressCallbackHandler reasoning stream. Content and tool-call deltas are
        folded back into a single message via the shared ``StreamAccumulator`` so the
        caller's tool-call parsing stays identical to the old non-streaming path.
        Returns the same ``(content, tool_calls)`` shape the caller expects.
        """
        stream = self._client.chat.completions.create(**call_kwargs)
        if inspect.isawaitable(stream):
            stream = await stream

        acc = StreamAccumulator()

        async def _handle(chunk: Any) -> None:
            data = chunk.model_dump() if hasattr(chunk, "model_dump") else chunk
            if not isinstance(data, dict):
                return
            delta = apply_chunk(acc, data)
            if delta and run_manager is not None:
                try:
                    await run_manager.on_llm_new_token(
                        delta, chunk=AIMessageChunk(content=delta)
                    )
                except Exception as cb_err:
                    logger.debug("on_llm_new_token forwarding failed: %s", cb_err)

        if hasattr(stream, "__aiter__"):
            async for chunk in stream:
                await _handle(chunk)
        else:
            for chunk in stream:
                await _handle(chunk)

        return acc.content, acc.merged_tool_calls()

    async def _consume_ollama_native(
        self,
        call_kwargs: Dict[str, Any],
        run_manager: Optional[CallbackManagerForLLMRun],
    ) -> tuple[str, List[Dict[str, Any]]]:
        """Ollama's native chat API honors the configured context window through ``options.num_ctx``."""
        body = build_ollama_chat_body(call_kwargs, num_ctx=self.context_window or None)
        api_key = getattr(self._client, "api_key", None)
        content_parts: List[str] = []
        native_calls: List[Dict[str, Any]] = []
        final_chunk: Dict[str, Any] = {}
        async for chunk in stream_ollama_chat(ollama_native_root(self.base_url), body, api_key=api_key):
            message = chunk.get("message") or {}
            for delta in (message.get("thinking") or "", message.get("content") or ""):
                if delta and run_manager is not None:
                    try:
                        await run_manager.on_llm_new_token(delta, chunk=AIMessageChunk(content=delta))
                    except Exception as cb_err:
                        logger.debug("on_llm_new_token forwarding failed: %s", cb_err)
            if message.get("content"):
                content_parts.append(message["content"])
            if message.get("tool_calls"):
                native_calls.extend(message["tool_calls"])
            if chunk.get("done"):
                final_chunk = chunk
        logger.info(
            "Ollama native chat finished: model=%s num_ctx=%s prompt_tokens=%s output_tokens=%s tool_calls=%s",
            self.model_identifier,
            body["options"].get("num_ctx"),
            final_chunk.get("prompt_eval_count"),
            final_chunk.get("eval_count"),
            len(native_calls),
        )
        num_ctx = body["options"].get("num_ctx")
        used_tokens = ollama_context_tokens_used(final_chunk, num_ctx, body["options"].get("num_predict"))
        if used_tokens is not None:
            logger.warning(
                "Ollama filled the %s-token context window for %s (%s tokens); treating the call as a context overflow",
                num_ctx,
                self.model_identifier,
                used_tokens,
            )
            raise LocalModelContextWindowExceeded(used_tokens, int(num_ctx))
        return "".join(content_parts), ollama_tool_calls_to_openai(native_calls)

    def _build_ai_message(self, content: str, tool_calls: List[Dict[str, Any]]) -> AIMessage:
        if not tool_calls:
            return AIMessage(content=content)
        return AIMessage(
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


def create_langchain_llm_from_openai_compatible(
    openai_compatible_model: Any,
    profile: Optional[RuntimeModelProfile] = None,
) -> OpenAICompatibleLangChainAdapter:
    if getattr(openai_compatible_model, "_async_client", None) is None:
        raise RuntimeError("OpenAI-compatible custom model is not loaded")

    tool_rendering = resolve_tool_rendering_for(profile)
    tool_call_format = resolve_tool_call_format_for(profile)
    adapter = OpenAICompatibleLangChainAdapter(
        model_name=getattr(openai_compatible_model, "model_name", "custom"),
        model_identifier=openai_compatible_model.model_identifier,
        base_url=openai_compatible_model.base_url,
        temperature=getattr(openai_compatible_model, "temperature", 0.7),
        max_tokens=getattr(openai_compatible_model, "max_output_tokens", 4096),
        tool_rendering=tool_rendering,
        tool_call_format=tool_call_format,
        context_window=int(getattr(openai_compatible_model, "max_context_length", 0) or 0),
        server_type=str(getattr(openai_compatible_model, "server_type", None) or "openai_compatible"),
    )
    adapter._client = openai_compatible_model._async_client
    logger.info(
        "Created OpenAICompatibleLangChainAdapter: model=%s, endpoint=%s, "
        "tool_rendering=%s, tool_call_format=%s",
        adapter.model_identifier,
        adapter.base_url,
        tool_rendering,
        tool_call_format,
    )
    return adapter
