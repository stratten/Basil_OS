"""Auth Proxy Model - Routes LLM requests through the Basil Auth Service to OpenRouter.

This model is used when the user is authenticated and has selected app_keys preference.
All requests go through our auth service which handles:
1. OpenRouter routing (accepts OpenAI format, routes to any provider)
2. Usage logging and billing
3. Token validation
"""

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional, Set, List, AsyncGenerator
import httpx

from ..base_model import ModelMetadata, ModelState
from ..model_types import ModelCapability
from ....services.auth_service_endpoint import AUTH_SERVICE_URL
from ..models_registry import (
    apply_request_parameter_omissions,
    get_omitted_request_parameters,
)
from .base_reasoning import DEFAULT_STREAMING_MAX_TOKENS, BaseReasoningModel
from .streaming_contract import (
    GenerationBudget,
    StreamEvent,
    terminal_from_error,
    terminal_from_provider_reason,
)

logger = logging.getLogger(__name__)


def _get_model_info_from_registry(model_id: str) -> dict | None:
    """
    Look up model configuration from the unified registry.

    Args:
        model_id: The internal model ID (e.g. "claude-sonnet-4-5-20250929").

    Returns:
        Model config dict if found, None otherwise.
    """
    try:
        from ..models_registry import get_model
        return get_model(model_id)
    except Exception as e:
        logger.debug(f"Registry lookup failed for {model_id}: {e}")
        return None

class AuthProxyModel(BaseReasoningModel):
    """Model that proxies all requests through the Basil Auth Service to OpenRouter.
    
    OpenRouter accepts requests in OpenAI format and routes to the appropriate
    provider based on the model ID (e.g., 'anthropic/claude-3.5-sonnet').
    
    Model configuration (openrouter_id, context_window, max_output_tokens, etc.)
    is sourced from the unified model registry.
    """
    
    def __init__(
        self,
        model_id: str,
        access_token: str,
        required_capabilities: Optional[Set[ModelCapability]] = None,
    ):
        """Initialize the auth proxy model.

        Args:
            model_id: The model ID (internal or OpenRouter format)
            access_token: A confirmed authenticated-account JWT for the Auth Service
            required_capabilities: Required model capabilities

        Note: access_token must be a non-empty string.
        """
        if not access_token:
            raise ValueError("access_token must be provided")

        # Get model configuration from unified registry.
        cfg = _get_model_info_from_registry(model_id)
        
        if cfg:
            # Use registry data for all model metadata.
            self.openrouter_model_id = cfg.get("openrouter_id", model_id)
            self.provider = cfg.get("provider", "unknown")
            context_window = cfg.get("context_window", 128000)
            max_output = cfg.get("max_output_tokens", 8192)
        else:
            # Fallback for models not in registry (e.g., direct OpenRouter model IDs).
            # If model_id already contains "/", assume it's in OpenRouter format.
            if "/" in model_id:
                self.openrouter_model_id = model_id
                self.provider = model_id.split("/")[0]
            else:
                # Unknown model - use as-is and log warning.
                self.openrouter_model_id = model_id
                self.provider = "unknown"
                logger.warning(f"Model {model_id} not found in registry, using as-is")
            context_window = 128000
            max_output = 8192

        self.access_token = access_token
        self._client: Optional[httpx.AsyncClient] = None
        
        # Initialize base class with a dummy path (we don't use local files).
        super().__init__(
            model_path=Path("/dev/null"),
            required_capabilities=required_capabilities or {ModelCapability.REASONING}
        )
        
        # Set model metadata from registry.
        self.model_name = model_id
        self.max_context_length = context_window
        self.max_output_tokens = max_output
        self.max_tokens_to_sample = max_output
        self.omitted_request_parameters = get_omitted_request_parameters(model_id)
        self.state = ModelState.READY
        
        logger.info(
            "AuthProxyModel initialized: %s -> %s (provider: %s)",
            model_id,
            self.openrouter_model_id,
            self.provider,
        )
    
    @property
    def api_key(self) -> str:
        """Alias for access_token to maintain compatibility with direct model classes.
        
        This allows AuthProxyModel to be used interchangeably with ClaudeModel/OpenAIModel
        in code that expects an api_key attribute (e.g., LangChain agent initialization).
        """
        return self.access_token
    
    def _build_headers(self) -> Dict[str, str]:
        """Build request headers for the authenticated account."""
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.access_token}",
        }
    
    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create async HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=120.0)
        return self._client
    
    async def load(self) -> None:
        """Load the model (no-op for proxy, just validate token)."""
        self.state = ModelState.READY
        logger.info(f"AuthProxyModel ready: {self.model_name}")
    
    async def unload(self) -> None:
        """Unload the model (close HTTP client)."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None
        self.state = ModelState.UNLOADED
    
    def get_metadata(self) -> ModelMetadata:
        """Return model metadata."""
        return ModelMetadata(
            name=self.model_name,
            version="1.0",
            source=self.provider,
            capabilities={ModelCapability.REASONING},
            description=f"Auth-proxied model: {self.openrouter_model_id}",
            parameters={
                "openrouter_model_id": self.openrouter_model_id,
                "max_context_length": self.max_context_length,
                "max_tokens_to_sample": self.max_tokens_to_sample,
            },
            requirements={},
            memory_requirements="0MB",  # No local memory needed for API model
        )
    
    async def generate_response(
        self,
        prompt: str,
        context: Dict[str, Any] = None,
        max_tokens: Optional[int] = None,
        enable_web_search: bool = False,
        preserve_thinking: bool = False
    ) -> str:
        """Generate a response via the auth service proxy.
        
        Args:
            prompt: The prompt text
            context: Optional context dict
            max_tokens: Maximum tokens to generate
            enable_web_search: Whether to enable web search (not supported via proxy)
            preserve_thinking: Whether to preserve thinking tags
            
        Returns:
            The generated response text
        """
        # Use model's max_output_tokens when not specified
        if max_tokens is None:
            max_tokens = self.max_output_tokens
        
        # Convert prompt to messages format
        messages = [{"role": "user", "content": prompt}]
        
        # Add system message if provided in context
        if context and "system_prompt" in context:
            messages.insert(0, {"role": "system", "content": context["system_prompt"]})
        
        client = await self._get_client()
        
        payload = {
            "provider": self.provider,
            "model": self.openrouter_model_id,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": max_tokens,
            "stream": False
        }
        if self.omitted_request_parameters:
            payload["omit_parameters"] = self.omitted_request_parameters
        payload = apply_request_parameter_omissions(
            payload,
            self.omitted_request_parameters,
        )
        
        headers = self._build_headers()
        
        logger.info(
            "🔐 AuthProxy request: model=%s, max_tokens=%s",
            self.openrouter_model_id,
            max_tokens,
        )
        
        try:
            response = await client.post(
                f"{AUTH_SERVICE_URL}/route/request",
                json=payload,
                headers=headers
            )
            
            if response.status_code == 401:
                raise ValueError("Authentication required - token expired or invalid")
            elif response.status_code == 402:
                raise ValueError("Payment required - please add a payment method")
            elif response.status_code == 403:
                raise ValueError("Subscription inactive")
            elif response.status_code >= 400:
                error_detail = response.text
                raise ValueError(f"Auth service error ({response.status_code}): {error_detail}")
            
            result = response.json()
            
            # Extract content from response
            if "choices" in result and len(result["choices"]) > 0:
                content = result["choices"][0].get("message", {}).get("content", "")
            elif "content" in result:
                content = result["content"]
            else:
                content = str(result)
            
            logger.info(f"🔐 AuthProxy response received: {len(content)} chars")
            return content
            
        except httpx.TimeoutException:
            logger.error("Auth service request timed out")
            raise ValueError("Request timed out - please try again")
        except Exception as e:
            logger.error(f"Auth proxy error: {e}")
            raise
    
    def validate(self) -> bool:
        """Validate model is ready."""
        return self.state == ModelState.READY and bool(self.access_token)
    
    def _generate(self, prompt: str, max_tokens: int) -> str:
        """Synchronous generation via auth proxy (blocks until complete).
        
        This implements the abstract method from BaseAIModel.
        """
        # Call async method synchronously
        return asyncio.run(self._generate_async(prompt, max_tokens))
    
    async def _generate_async(self, prompt: str, max_tokens: int) -> str:
        """Asynchronous generation via auth proxy.
        
        This implements the abstract method from BaseAIModel.
        """
        # Use existing generate_response logic
        return await self.generate_response(prompt, max_tokens=max_tokens)
    
    async def chat_completion(self, messages: List[Dict[str, str]]) -> Dict[str, str]:
        """Handle chat completion request.
        
        Args:
            messages: List of message dicts with 'role' and 'content'
            
        Returns:
            Dict with 'content' key containing response
        """
        client = await self._get_client()
        
        payload = {
            "provider": self.provider,
            "model": self.openrouter_model_id,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens_to_sample,
            "stream": False
        }
        if self.omitted_request_parameters:
            payload["omit_parameters"] = self.omitted_request_parameters
        payload = apply_request_parameter_omissions(
            payload,
            self.omitted_request_parameters,
        )
        
        headers = self._build_headers()
        
        logger.info(
            "🔐 AuthProxy chat_completion: model=%s, messages=%s",
            self.openrouter_model_id,
            len(messages),
        )
        
        try:
            response = await client.post(
                f"{AUTH_SERVICE_URL}/route/request",
                json=payload,
                headers=headers
            )
            
            if response.status_code >= 400:
                error_msg = response.text
                if response.status_code == 401:
                    error_msg = "Authentication required - token expired"
                elif response.status_code == 402:
                    error_msg = "Payment required"
                raise ValueError(f"Auth service error: {error_msg}")
            
            result = response.json()
            
            # Extract content
            if "choices" in result and len(result["choices"]) > 0:
                content = result["choices"][0].get("message", {}).get("content", "")
            elif "content" in result:
                content = result["content"]
            else:
                content = str(result)
            
            return {
                "content": content,
                "metadata": {
                    "model": self.openrouter_model_id,
                    "via": "auth_proxy"
                }
            }
            
        except Exception as e:
            logger.error(f"Auth proxy chat_completion error: {e}")
            raise
    
    async def _generate_from_messages_streaming(
        self,
        messages: List[Dict[str, str]],
        *,
        max_tokens: Optional[int] = None,
    ) -> AsyncGenerator[str, None]:
        """Stream a conversation, sending the roles the caller actually gave us.

        The inherited default flattens messages into one "User:/Assistant:" string,
        which then arrived here as a single user turn: the system prompt became user
        text and the model's own prior replies were presented as the user's words.
        The proxy has always forwarded a real array, so only the caller needed fixing.
        """
        budget = max_tokens if max_tokens is not None else DEFAULT_STREAMING_MAX_TOKENS
        async for token in self._stream_messages(messages, budget):
            yield token

    async def _generate_response_streaming(
        self, prompt: str, max_tokens: int = DEFAULT_STREAMING_MAX_TOKENS
    ) -> AsyncGenerator[str, None]:
        """Stream a response to a single prompt, for callers that only have text.

        Args:
            prompt: The prompt text
            max_tokens: Maximum tokens

        Yields:
            Response tokens as they arrive
        """
        async for token in self._stream_messages(
            [{"role": "user", "content": prompt}], max_tokens
        ):
            yield token

    async def _stream_messages(
        self, messages: List[Dict[str, str]], max_tokens: int
    ) -> AsyncGenerator[str, None]:
        """Stream a chat completion for a messages array via the auth service.

        Args:
            messages: Role-tagged conversation turns, forwarded to the provider as-is
            max_tokens: Maximum tokens

        Yields:
            Response tokens as they arrive
        """
        payload = {
            "provider": self.provider,
            "model": self.openrouter_model_id,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": max_tokens,
            "stream": True
        }
        if self.omitted_request_parameters:
            payload["omit_parameters"] = self.omitted_request_parameters
        payload = apply_request_parameter_omissions(
            payload,
            self.omitted_request_parameters,
        )
        
        logger.info("🔐 AuthProxy streaming: model=%s", self.openrouter_model_id)

        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream(
                "POST",
                f"{AUTH_SERVICE_URL}/route/request",
                json=payload,
                headers=self._build_headers(),
            ) as response:
                if response.status_code >= 400:
                    error = await response.aread()
                    if response.status_code == 401:
                        raise ValueError("Authentication required - token expired or invalid")
                    if response.status_code == 402:
                        raise ValueError("Payment required - please add a payment method")
                    if response.status_code == 403:
                        raise ValueError("Subscription inactive")
                    raise ValueError(f"Auth service error: {error.decode()}")

                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        data = line[6:]
                        if data == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data)
                            if "choices" in chunk and len(chunk["choices"]) > 0:
                                delta = chunk["choices"][0].get("delta", {})
                                if "content" in delta:
                                    yield delta["content"]
                            elif "content" in chunk:
                                yield chunk["content"]
                        except json.JSONDecodeError:
                            continue

    async def stream_chat_completion(
        self,
        messages: List[Dict[str, str]],
        budget: Optional[GenerationBudget] = None,
    ) -> AsyncGenerator[StreamEvent, None]:
        """Stream chat completion through the auth proxy with budget metadata."""
        max_tokens = budget.effective_output_tokens if budget else self.max_tokens_to_sample
        try:
            async for token in self._stream_messages(messages, max_tokens):
                yield StreamEvent(text=token)
            yield StreamEvent(
                terminal=terminal_from_provider_reason(
                    "unknown",
                    raw={
                        "model": self.openrouter_model_id,
                        "terminal_metadata_available": False,
                    },
                )
            )
        except Exception as exc:
            yield StreamEvent(terminal=terminal_from_error(exc))

