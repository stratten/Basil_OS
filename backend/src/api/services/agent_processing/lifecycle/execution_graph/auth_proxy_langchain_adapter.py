"""
LangChain Adapter for AuthProxyModel

This module provides a LangChain-compatible chat model that routes requests
through the Basil Auth Service, mirroring the architecture used by AssistantSession suggestions.

The adapter implements full tool calling support for LangChain agents, converting
between LangChain's tool format and the OpenAI-compatible format used by the auth service.

Key features:
- Routes all requests through AUTH_SERVICE_URL/route/request (same as AssistantSession suggestions)
- Full bind_tools() support for LangChain tool-calling agents
- Proper tool call parsing from OpenAI-format responses
- Both sync and async generation methods
"""

import json
import logging
import re
from typing import Any, Dict, Iterator, List, Optional, Tuple, Union

import httpx
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

from api.core.models.models_registry import apply_request_parameter_omissions

from .auth_proxy_stream import StreamAccumulator, consume_auth_proxy_stream
from .model_errors import TransientModelError, is_transient_error_text

logger = logging.getLogger(__name__)


class AuthProxyLangChainAdapter(BaseChatModel):
    """LangChain chat model that routes through Basil Auth Service.
    
    This adapter wraps AuthProxyModel to provide full LangChain compatibility,
    including tool calling support required by LangChain agents.
    
    The adapter routes requests to the same /route/request endpoint used by
    AssistantSession suggestions, ensuring consistent authentication and billing.
    """
    
    # Pydantic fields for configuration
    auth_service_url: str = Field(description="Base URL for auth service")
    access_token: str = Field(description="JWT access token")
    model_id: str = Field(description="OpenRouter model ID")
    model_name: str = Field(description="Human-readable model name")
    provider: str = Field(description="Provider name (anthropic, openai, etc.)")
    temperature: float = Field(default=0.7, description="Sampling temperature")
    max_tokens: int = Field(default=4096, description="Maximum tokens to generate")
    omitted_request_parameters: List[str] = Field(default_factory=list, description="Request parameters to omit")
    
    # Internal state for tool binding
    _bound_tools: Optional[List[Dict[str, Any]]] = None
    
    class Config:
        """Pydantic configuration."""
        arbitrary_types_allowed = True
    
    @property
    def _llm_type(self) -> str:
        """Return LLM type identifier."""
        return "auth_proxy_langchain"
    
    @property
    def _identifying_params(self) -> Dict[str, Any]:
        """Return identifying parameters for caching."""
        return {
            "model_id": self.model_id,
            "provider": self.provider,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
    
    def bind_tools(
        self,
        tools: List[Union[BaseTool, Dict[str, Any]]],
        **kwargs: Any
    ) -> "AuthProxyLangChainAdapter":
        """Bind tools for use in subsequent calls.
        
        Creates a new instance with tools bound, following LangChain's
        immutable pattern for tool binding.
        
        Args:
            tools: List of LangChain tools or tool dictionaries
            **kwargs: Additional arguments (tool_choice, etc.)
            
        Returns:
            New adapter instance with tools bound
        """
        # Convert LangChain tools to OpenAI function format
        openai_tools = []
        for tool in tools:
            if isinstance(tool, dict):
                # Already in dict format
                openai_tools.append(tool)
            elif hasattr(tool, "name") and hasattr(tool, "description"):
                # LangChain BaseTool - convert to OpenAI format
                tool_schema = {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description or "",
                        "parameters": self._get_tool_parameters(tool),
                    }
                }
                openai_tools.append(tool_schema)
        
        # Create new instance with tools bound
        new_instance = AuthProxyLangChainAdapter(
            auth_service_url=self.auth_service_url,
            access_token=self.access_token,
            model_id=self.model_id,
            model_name=self.model_name,
            provider=self.provider,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            omitted_request_parameters=self.omitted_request_parameters,
        )
        new_instance._bound_tools = openai_tools
        
        logger.info(f"🔧 Bound {len(openai_tools)} tools to AuthProxyLangChainAdapter")
        return new_instance
    
    def _get_tool_parameters(self, tool: BaseTool) -> Dict[str, Any]:
        """Extract parameter schema from a LangChain tool.
        
        Args:
            tool: LangChain BaseTool instance
            
        Returns:
            JSON Schema for the tool's parameters
        """
        # Try to get schema from args_schema (Pydantic model)
        if hasattr(tool, "args_schema") and tool.args_schema is not None:
            try:
                schema = tool.args_schema.model_json_schema()
                # Remove title if present (not needed for OpenAI format)
                schema.pop("title", None)
                return schema
            except Exception:
                pass
        
        # Fallback: empty object schema
        return {"type": "object", "properties": {}, "required": []}
    
    def _safe_parse_json(self, json_str: str, context: str = "") -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        """Safely parse JSON with multiple recovery strategies.
        
        Attempts to parse JSON, and if it fails, tries various repair strategies
        to recover from common LLM JSON formatting issues.
        
        Args:
            json_str: The JSON string to parse
            context: Optional context for error logging (e.g., tool name)
            
        Returns:
            Tuple of (parsed_dict, error_message). If successful, error_message is None.
            If all strategies fail, parsed_dict is None and error_message describes the issue.
        """
        if not json_str or json_str.strip() == "":
            return {}, None
        
        original_str = json_str
        
        # Strategy 1: Direct parse
        try:
            return json.loads(json_str), None
        except json.JSONDecodeError:
            pass
        
        # Strategy 2: Fix common issues - trailing commas, single quotes
        try:
            # Remove trailing commas before } or ]
            fixed = re.sub(r',\s*([}\]])', r'\1', json_str)
            # Replace single quotes with double quotes (but not inside strings)
            # This is a simplified approach - handles most cases
            if "'" in fixed and '"' not in fixed:
                fixed = fixed.replace("'", '"')
            result = json.loads(fixed)
            logger.warning(f"🔧 JSON repair (trailing commas/quotes) succeeded for {context}")
            return result, None
        except json.JSONDecodeError:
            pass
        
        # Strategy 3: Try to extract JSON object from surrounding text
        try:
            # Find the outermost {} pair
            start = json_str.find('{')
            end = json_str.rfind('}')
            if start != -1 and end != -1 and end > start:
                extracted = json_str[start:end + 1]
                result = json.loads(extracted)
                logger.warning(f"🔧 JSON repair (extraction) succeeded for {context}")
                return result, None
        except json.JSONDecodeError:
            pass
        
        # Strategy 4: Handle truncated JSON by attempting to close it
        try:
            # Count open braces/brackets and try to close them
            open_braces = json_str.count('{') - json_str.count('}')
            open_brackets = json_str.count('[') - json_str.count(']')
            
            if open_braces > 0 or open_brackets > 0:
                # Remove any trailing incomplete key-value pair
                truncated = re.sub(r',\s*"[^"]*"?\s*:?\s*$', '', json_str)
                # Close open structures
                truncated += '}' * open_braces + ']' * open_brackets
                result = json.loads(truncated)
                logger.warning(f"🔧 JSON repair (truncation fix) succeeded for {context}")
                return result, None
        except json.JSONDecodeError:
            pass
        
        # Strategy 5: Handle unescaped quotes in string values
        try:
            # This regex attempts to fix unescaped quotes inside string values
            # Pattern: after a colon and quote, before the next comma/brace
            fixed = re.sub(
                r'(?<=: ")([^"]*?)(?<!\\)"(?=[^,}\]]*[,}\]])',
                lambda m: m.group(1).replace('"', '\\"') + '"',
                json_str
            )
            if fixed != json_str:
                result = json.loads(fixed)
                logger.warning(f"🔧 JSON repair (unescaped quotes) succeeded for {context}")
                return result, None
        except (json.JSONDecodeError, re.error):
            pass
        
        # All strategies failed
        error_preview = original_str[:100] + "..." if len(original_str) > 100 else original_str
        error_msg = f"Failed to parse JSON after all repair attempts. Preview: {error_preview}"
        logger.error(f"❌ JSON parse failed for {context}: {error_msg}")
        return None, error_msg
    
    def _convert_messages(self, messages: List[BaseMessage]) -> List[Dict[str, Any]]:
        """Convert LangChain messages to OpenAI format.
        
        Args:
            messages: List of LangChain BaseMessage objects
            
        Returns:
            List of message dicts in OpenAI format
        """
        converted = []
        for msg in messages:
            if isinstance(msg, SystemMessage):
                converted.append({"role": "system", "content": msg.content})
            elif isinstance(msg, HumanMessage):
                converted.append({"role": "user", "content": msg.content})
            elif isinstance(msg, AIMessage):
                ai_msg: Dict[str, Any] = {"role": "assistant"}
                
                # Tool-call-only assistant turns may have empty content, but
                # the auth service schema still requires the field to be present.
                ai_msg["content"] = msg.content if isinstance(msg.content, str) else ""
                
                # Handle tool calls in the message
                if hasattr(msg, "tool_calls") and msg.tool_calls:
                    ai_msg["tool_calls"] = [
                        {
                            "id": tc.get("id", f"call_{i}"),
                            "type": "function",
                            "function": {
                                "name": tc.get("name", ""),
                                "arguments": json.dumps(tc.get("args", {}))
                            }
                        }
                        for i, tc in enumerate(msg.tool_calls)
                    ]
                # Also check additional_kwargs for tool_calls
                elif hasattr(msg, "additional_kwargs") and msg.additional_kwargs.get("tool_calls"):
                    ai_msg["tool_calls"] = msg.additional_kwargs["tool_calls"]
                
                converted.append(ai_msg)
            elif isinstance(msg, ToolMessage):
                converted.append({
                    "role": "tool",
                    "tool_call_id": msg.tool_call_id,
                    "content": msg.content if isinstance(msg.content, str) else json.dumps(msg.content)
                })
            else:
                # Generic fallback
                role = getattr(msg, "type", "user")
                if role == "human":
                    role = "user"
                elif role == "ai":
                    role = "assistant"
                converted.append({"role": role, "content": str(msg.content)})
        
        return converted
    
    def _build_headers(self) -> Dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.access_token}",
        }

    def _auth_label(self) -> str:
        return "token"
    
    def _make_token_forwarder(
        self, run_manager: Optional[CallbackManagerForLLMRun]
    ) -> Optional[Any]:
        """Build the per-delta callback that surfaces live reasoning.

        Awaiting ``on_llm_new_token`` is what drives LiveProgressCallbackHandler's
        reasoning stream; without it the agent loop shows no live text until
        synthesis. Returns ``None`` when there is no callback manager (e.g. direct
        non-agent calls) so streaming still works with no observers.
        """
        if run_manager is None:
            return None

        async def _forward(delta: str) -> None:
            try:
                await run_manager.on_llm_new_token(
                    delta, chunk=AIMessageChunk(content=delta)
                )
            except Exception as cb_err:
                logger.debug(f"on_llm_new_token forwarding failed: {cb_err}")

        return _forward

    async def _raise_for_stream_status(self, status_code: int, body: str) -> None:
        """Map a non-200 initial response to the same errors as the blocking path.

        Auth/subscription/payment checks run before the auth service starts
        streaming, so these still arrive as ordinary non-streamed status codes.
        """
        if status_code == 401:
            raise ValueError("Authentication required - token expired or invalid")
        if status_code == 402:
            raise ValueError("Payment required - please add a payment method")
        if status_code == 403:
            raise ValueError("Subscription inactive")
        if status_code in (408, 429) or status_code >= 500:
            raise TransientModelError(f"Auth service error ({status_code}): {body}")
        if status_code >= 400:
            raise ValueError(f"Auth service error ({status_code}): {body}")

    async def _stream_route_request(
        self,
        client: httpx.AsyncClient,
        payload: Dict[str, Any],
        run_manager: Optional[CallbackManagerForLLMRun],
    ) -> "StreamAccumulator":
        """POST with ``stream: true`` and fold the SSE response into an accumulator."""
        url = f"{self.auth_service_url}/route/request"
        forward_token = self._make_token_forwarder(run_manager)

        async with client.stream(
            "POST", url, json=payload, headers=self._build_headers()
        ) as response:
            if response.status_code == 200:
                return await consume_auth_proxy_stream(response.aiter_lines(), forward_token)
            body = (await response.aread()).decode(errors="replace")

        await self._raise_for_stream_status(response.status_code, body)
    
    def _parse_tool_calls(self, response_data: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[str]]:
        """Parse tool calls from OpenAI-format response with robust error handling.
        
        Args:
            response_data: Response dict from auth service
            
        Returns:
            Tuple of (tool_calls, parse_errors):
            - tool_calls: List of successfully parsed tool call dicts in LangChain format
            - parse_errors: List of error messages for any tool calls that failed to parse
        """
        tool_calls = []
        parse_errors = []
        
        if "choices" in response_data and len(response_data["choices"]) > 0:
            message = response_data["choices"][0].get("message", {})
            raw_tool_calls = message.get("tool_calls", [])
            
            for tc in raw_tool_calls:
                if tc.get("type") == "function":
                    func = tc.get("function", {})
                    tool_name = func.get("name", "unknown")
                    arguments_str = func.get("arguments", "{}")
                    
                    # Use safe JSON parsing with recovery strategies
                    parsed_args, error = self._safe_parse_json(
                        arguments_str, 
                        context=f"tool '{tool_name}'"
                    )
                    
                    if error:
                        parse_errors.append(f"Tool '{tool_name}': {error}")
                        logger.warning(
                            f"⚠️ Skipping malformed tool call '{tool_name}' - "
                            f"will request retry. Raw args: {arguments_str[:200]}"
                        )
                    else:
                        tool_calls.append({
                            "id": tc.get("id", ""),
                            "name": tool_name,
                            "args": parsed_args or {}
                        })
        
        return tool_calls, parse_errors
    
    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any
    ) -> ChatResult:
        """Synchronous generation (wraps async).
        
        Args:
            messages: Input messages
            stop: Stop sequences
            run_manager: Callback manager
            **kwargs: Additional arguments
            
        Returns:
            ChatResult with generated response
        """
        import asyncio
        
        # Run async method in event loop
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # If we're already in an async context, use nest_asyncio pattern
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    result = pool.submit(
                        asyncio.run,
                        self._agenerate(messages, stop, run_manager, **kwargs)
                    ).result()
                return result
            else:
                return loop.run_until_complete(
                    self._agenerate(messages, stop, run_manager, **kwargs)
                )
        except RuntimeError:
            # No event loop exists, create one
            return asyncio.run(
                self._agenerate(messages, stop, run_manager, **kwargs)
            )
    
    async def _agenerate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any
    ) -> ChatResult:
        """Asynchronous generation via auth service.
        
        Note: Retry logic is handled by LangChain's native .with_retry() mechanism
        at the executor level. This method focuses on single-request handling
        with JSON repair for malformed tool call arguments.
        
        Args:
            messages: Input messages
            stop: Stop sequences
            run_manager: Callback manager
            **kwargs: Additional arguments
            
        Returns:
            ChatResult with generated response
        """
        # Convert messages to OpenAI format
        converted_messages = self._convert_messages(messages)
        
        # Build request payload
        payload: Dict[str, Any] = {
            "provider": self.provider,
            "model": self.model_id,
            "messages": converted_messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "stream": True,
        }
        if self.omitted_request_parameters:
            payload["omit_parameters"] = self.omitted_request_parameters
        payload = apply_request_parameter_omissions(
            payload,
            self.omitted_request_parameters,
        )
        
        # Add tools if bound
        if self._bound_tools:
            payload["tools"] = self._bound_tools
            # Allow parallel tool calls for efficiency
            payload["parallel_tool_calls"] = True
        
        # Add stop sequences if provided
        if stop:
            payload["stop"] = stop
        
        logger.info(
            f"🔐 AuthProxyLangChain request ({self._auth_label()}): model={self.model_id}, "
            f"messages={len(converted_messages)}, tools={len(self._bound_tools or [])}"
        )
        
        async with httpx.AsyncClient(timeout=120.0) as client:
            try:
                acc = await self._stream_route_request(client, payload, run_manager)

                if acc.stream_error:
                    stream_error_message = f"Auth service stream error: {acc.stream_error}"
                    if is_transient_error_text(str(acc.stream_error)):
                        raise TransientModelError(stream_error_message)
                    raise ValueError(stream_error_message)

                result = acc.as_openai_response()

                # Extract content and tool calls (with JSON repair)
                content = ""
                tool_calls = []
                parse_errors: List[str] = []
                
                if "choices" in result and len(result["choices"]) > 0:
                    message = result["choices"][0].get("message", {})
                    content = message.get("content", "") or ""
                    tool_calls, parse_errors = self._parse_tool_calls(result)
                elif "content" in result:
                    content = result["content"]
                
                # Log any parse errors (JSON repair was attempted in _parse_tool_calls)
                if parse_errors:
                    logger.warning(
                        f"⚠️ Some tool calls had parse errors after repair attempts: {parse_errors}"
                    )
                
                logger.info(
                    f"🔐 AuthProxyLangChain response: {len(content)} chars, "
                    f"{len(tool_calls)} tool calls"
                    + (f", {len(parse_errors)} parse errors" if parse_errors else "")
                )
                
                # Build AIMessage with tool calls if present
                if tool_calls:
                    ai_message = AIMessage(
                        content=content,
                        tool_calls=tool_calls,
                        additional_kwargs={"tool_calls": [
                            {
                                "id": tc["id"],
                                "type": "function",
                                "function": {
                                    "name": tc["name"],
                                    "arguments": json.dumps(tc["args"])
                                }
                            }
                            for tc in tool_calls
                        ]}
                    )
                else:
                    ai_message = AIMessage(content=content)
                
                return ChatResult(
                    generations=[ChatGeneration(message=ai_message)]
                )
                
            except httpx.TimeoutException as e:
                logger.error("Auth service request timed out")
                raise TransientModelError("Request timed out - please try again") from e
            except httpx.TransportError as e:
                logger.error(f"Auth service connection failed: {e}")
                raise TransientModelError(f"Auth service connection failed: {e}") from e
            except Exception as e:
                logger.error(f"AuthProxyLangChain error: {e}")
                raise


def create_langchain_llm_from_auth_proxy(auth_proxy_model: Any) -> AuthProxyLangChainAdapter:
    """Factory function to create LangChain adapter from AuthProxyModel.
    
    This is the main entry point for creating a LangChain-compatible LLM
    from an existing AuthProxyModel instance.
    
    Args:
        auth_proxy_model: An AuthProxyModel instance
        
    Returns:
        AuthProxyLangChainAdapter configured with the same settings
    """
    from api.core.models.reasoning.auth_proxy_model import AUTH_SERVICE_URL
    
    return AuthProxyLangChainAdapter(
        auth_service_url=AUTH_SERVICE_URL,
        access_token=auth_proxy_model.access_token,
        model_id=auth_proxy_model.openrouter_model_id,
        model_name=auth_proxy_model.model_name,
        provider=auth_proxy_model.provider,
        temperature=auth_proxy_model.temperature,
        max_tokens=auth_proxy_model.max_tokens_to_sample,
        omitted_request_parameters=getattr(auth_proxy_model, "omitted_request_parameters", []),
    )
