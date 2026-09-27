import os
import asyncio
import base64
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, AsyncGenerator, Tuple, Union, Literal, TypedDict

from openai import OpenAI, AsyncOpenAI
from openai.types.chat import ChatCompletionMessage, ChatCompletionRole

from ..base_model import ModelMetadata, ModelState
from ..model_types import ModelCapability
from ..model_downloader import ModelDownloader
from config.api_keys import get_api_key
from api.core.logging.api_logger import api_logger
from .base_reasoning import BaseReasoningModel
from .streaming_async_bridge import async_iter_sync_stream
from .streaming_contract import (
    GenerationBudget,
    StreamEvent,
    terminal_from_error,
    terminal_from_provider_reason,
)


from ..models_registry import (
    get_model,
    has_feature,
    ModelFeature,
    requires_responses_api,
    get_reasoning_effort_default,
)


class OpenAIModel(BaseReasoningModel):
    """OpenAI GPT model implementation."""
    SHOULD_CHECK_API_KEY = True
    
    def __init__(self, model_path: Path, required_capabilities: Set[ModelCapability]):
        """Initialize the OpenAI model."""
        super().__init__(model_path, required_capabilities)
        self._client = None
        self._async_client = None
        
        # Default to o3-mini as it's the latest available reasoning model
        self.model_name = "o3-mini"
        
        # API settings
        self.api_key = None
        self.max_tokens_to_generate = 1000
        self.temperature = 0.7
        self.top_p = 0.9
        self.response_format = None  # Can be set to "json_object" when needed
        
        # Support for vision input flag
        self.vision_enabled = False
        
        # Set context window based on model
        self.max_context_length = self._get_context_window()
        
        # Set max output tokens based on model
        self.max_output_tokens = self._get_max_output_tokens()

    def _get_context_window(self) -> int:
        """Get the context window size for the current model."""
        cfg = get_model(self.model_name)
        if cfg and "context_window" in cfg:
            return cfg["context_window"]
        # Default to 128k for modern models
        return 128000
        
    def _get_max_output_tokens(self) -> int:
        """Get the maximum output tokens for the current model."""
        cfg = get_model(self.model_name)
        if cfg and "max_output_tokens" in cfg:
            return cfg["max_output_tokens"]
        # Default to 16384 for modern models
        return 16384
        
    def _supports_vision(self) -> bool:
        """Check if the current model supports vision/image inputs."""
        cfg = get_model(self.model_name)
        if cfg:
            caps = cfg.get("capabilities", [])
            return "vision" in [c.lower() if isinstance(c, str) else c for c in caps]
        # Default: most modern GPT models support vision
        return True

    def _supports_web_search(self) -> bool:
        """Check if the model supports web search functionality."""
        return has_feature(self.model_name, ModelFeature.WEB_SEARCH)
    
    def _should_use_search_model(self) -> bool:
        """Check if we should use a search-enabled model variant."""
        # For OpenAI, we need to use search-enabled model variants for web search
        # Check if the current model is NOT already a search variant
        return not ("search" in self.model_name)
    
    def _requires_responses_api(self) -> bool:
        """Determine if this model requires the Responses API instead of Chat Completions API.

        Delegates to the registry-driven ``requires_responses_api`` helper
        (explicit ``api_endpoint == "responses"`` or the ``reasoning_effort``
        feature) so the direct path and the LangChain agent path can never
        diverge. Keeps prefix-based fallbacks for models not in the registry.
        """
        if requires_responses_api(self.model_name):
            return True

        # Fallback logic for models not in the registry.
        # O-series models (o1, o3, o4) require the Responses API.
        if (self.model_name.startswith("o1") or
            self.model_name.startswith("o3") or
            self.model_name.startswith("o4")):
            return True

        # GPT-4.1 and GPT-4.5 series require the Responses API.
        if ("gpt-4.1" in self.model_name or "gpt-4.5" in self.model_name):
            return True

        return False

    def _get_reasoning_effort(self) -> Optional[str]:
        """Get the registry-configured reasoning effort for Responses API models."""
        effort = get_reasoning_effort_default(self.model_name)
        if effort:
            return effort

        # Fallback for o-series models that are not in the registry.
        if get_model(self.model_name) is None and self.model_name.startswith(("o1", "o3", "o4")):
            return "medium"
        return None
    
    def _get_web_search_tool_config(self) -> Dict[str, Any]:
        """Get the correct web search tool configuration based on API type."""
        if self._requires_responses_api():
            # Responses API uses web_search_preview tool type
            return {"type": "web_search"}
        else:
            # Chat Completions API doesn't support web search tools directly
            # Would need to use search-enabled model variants
            return None
    
    def _get_search_model_variant(self) -> str:
        """Get the search-enabled model variant for web search, or return original model.
        
        Returns:
            str: The search-enabled model variant if available, otherwise the original model name
        """
        cfg = get_model(self.model_name)
        if cfg:
            # Check feature_config for search_model_variant
            feature_cfg = cfg.get("feature_config", {}).get("web_search", {})
            if "search_model_variant" in feature_cfg:
                return feature_cfg["search_model_variant"]
        
        # Fallback: if model already ends with -search-preview, return as-is
        if self.model_name.endswith("-search-preview"):
            return self.model_name
        
        # For models that support web search, return as-is (they don't need variants)
        if self._supports_web_search():
            return self.model_name
        
        # Fallback: try appending -search-preview
        return f"{self.model_name}-search-preview"

    async def load(self) -> None:
        """Load the OpenAI model by initializing the API client."""
        try:
            self.state = ModelState.LOADING
            api_logger.info(f"Loading OpenAI model: {self.model_name}")
            
            if OpenAIModel.SHOULD_CHECK_API_KEY:
                # Get API key from key manager
                try:
                    self.api_key = get_api_key("openai")
                    api_logger.info("Loaded OpenAI API key from key manager")
                except ValueError:
                    api_logger.error("No OpenAI API key available")
                    raise ValueError("No OpenAI API key available. Please set an API key in the application settings.")
                
                # Initialize both synchronous and asynchronous clients
                self._client = OpenAI(api_key=self.api_key)
                self._async_client = AsyncOpenAI(api_key=self.api_key)
            else:
                api_logger.info("API key check is disabled for OpenAIModel. Skipping API key loading.")

            # Update context window size based on selected model
            self.max_context_length = self._get_context_window()

            # Update max output tokens after extended thinking settings have been updated
            self.max_output_tokens = self._get_max_output_tokens()
            
            # Check if model supports vision
            self.vision_enabled = self._supports_vision()
            
            # Log successful initialization
            cfg = get_model(self.model_name) or {}
            model_display_name = cfg.get("display_name", self.model_name)
            api_logger.info(f"OpenAI model {model_display_name} initialized successfully")
            self.state = ModelState.READY
            
        except Exception as e:
            self.state = ModelState.ERROR
            self._error = f"Failed to load OpenAI model: {str(e)}"
            api_logger.error(f"Error loading OpenAI model: {str(e)}")

    async def unload(self) -> None:
        """Unload the OpenAI model."""
        # No specific cleanup needed for API clients
        self._client = None
        self._async_client = None
        self.state = ModelState.UNLOADED
        api_logger.info("OpenAI model unloaded successfully")

    def get_metadata(self) -> ModelMetadata:
        """Get model metadata."""
        # Get the display name for the model from registry
        cfg = get_model(self.model_name) or {}
        display_name = cfg.get("display_name", self.model_name)
        description = cfg.get("description", "Cloud-based OpenAI model for reasoning tasks")
        
        # Build parameters dictionary
        parameters = {
            "model": self.model_name,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "max_tokens": self.max_tokens_to_generate,
            "context_window": self.max_context_length,
            "max_output_tokens": self.max_output_tokens,
            "vision_enabled": self.vision_enabled
        }
        
        # Add response format if set
        if self.response_format:
            parameters["response_format"] = self.response_format
        
        return ModelMetadata(
            name=f"OpenAI ({display_name})",
            version="1.0",
            source="openai",
            capabilities={ModelCapability.REASONING},
            description=description,
            parameters=parameters,
            requirements={
                "openai": ">=1.0.0"
            },
            memory_requirements="API-based (minimal local memory)",
            supports_gpu=False  # API-based, no GPU required locally
        )

    async def generate_response(
        self,
        prompt: str,
        context: Dict[str, Any] = None,
        max_tokens: Optional[int] = None,
        enable_web_search: bool = True
    ) -> str:
        """Generate a response using the appropriate OpenAI API endpoint."""
        if not self.is_loaded:
            raise RuntimeError("Model is not loaded")

        # Use model's max_output_tokens when not specified
        if max_tokens is None:
            max_tokens = self.max_output_tokens

        messages: List[Dict[str, str]] = []
        if context and "system_prompt" in context:
            messages.append({"role": "system", "content": context["system_prompt"]})
        messages.append({"role": "user", "content": prompt})

        try:
            # Determine which API to use based on model requirements
            if self._requires_responses_api():
                return await self._generate_with_responses_api(
                    messages, max_tokens, enable_web_search
                )
            else:
                return await self._generate_with_chat_completions_api(
                    messages, max_tokens, enable_web_search
                )
                
        except Exception as e:
            raise RuntimeError(f"Failed to generate response: {e}")

    async def generate_from_messages(
        self,
        messages: List[Dict[str, str]],
        *,
        max_tokens: Optional[int] = None,
        preserve_thinking: bool = False,
        enable_web_search: bool = True,
    ) -> str:
        """Generate from role-tagged messages using OpenAI's native format."""
        if not self.is_loaded:
            raise RuntimeError("Model is not loaded")

        budget = max_tokens if max_tokens is not None else self.max_output_tokens

        if self._requires_responses_api():
            return await self._generate_with_responses_api(
                messages, budget, enable_web_search
            )
        return await self._generate_with_chat_completions_api(
            messages, budget, enable_web_search
        )
    
    async def _generate_with_responses_api(
        self,
        messages: List[Dict[str, str]],
        max_tokens: int = 1200,
        enable_web_search: bool = True
    ) -> str:
        """Generate response using OpenAI Responses API."""
        # Set max tokens to generate, respecting model-specific limits
        tokens_to_generate = min(max_tokens, self.max_output_tokens)
        
        # Hoist system instructions from the first message when present
        system_instructions = "You are a helpful assistant."
        conversation_messages = messages
        if messages and messages[0].get("role", "").lower() == "system":
            system_instructions = messages[0]["content"]
            conversation_messages = messages[1:]
        
        # Prepare tools for web search if enabled and supported
        tools = []
        if enable_web_search and self._supports_web_search():
            tool_config = self._get_web_search_tool_config()
            if tool_config:
                tools.append(tool_config)
                api_logger.info(f"🔍 RESPONSES_API: Added web_search tool for {self.model_name}")
            else:
                api_logger.warning(f"🚫 RESPONSES_API: {self.model_name} doesn't support web search tool format")
        elif enable_web_search:
            api_logger.warning(f"🚫 RESPONSES_API: Web search not supported for {self.model_name}")
        else:
            api_logger.info("🚫 RESPONSES_API: Web search disabled")
        
        # Prepare input for Responses API - use simple string format for single user turn
        if (
            len(conversation_messages) == 1
            and conversation_messages[0].get("role") == "user"
        ):
            input_data = conversation_messages[0]["content"]
            api_logger.info("📝 RESPONSES_API: Using simple string input format")
        else:
            input_messages = []
            for msg in conversation_messages:
                if msg.get("role") == "user":
                    input_messages.append({
                        "role": "user",
                        "content": msg["content"]
                    })
                elif msg.get("role") == "assistant":
                    input_messages.append({
                        "role": "assistant", 
                        "content": msg["content"]
                    })
            input_data = input_messages
            api_logger.info(
                f"📝 RESPONSES_API: Using messages array format with {len(input_messages)} messages"
            )
        
        # Set reasoning parameters from the registry for reasoning-capable models.
        reasoning_params = {}
        reasoning_effort = self._get_reasoning_effort()
        if reasoning_effort:
            reasoning_params = {
                "reasoning": {
                    "effort": reasoning_effort
                }
            }
        
        # Make API call
        response = await self._async_client.responses.create(
            model=self.model_name,
            instructions=system_instructions,
            input=input_data,
            max_output_tokens=tokens_to_generate,
            tools=tools if tools else None,
            **reasoning_params
        )
        
        # Extract text from response
        return self._extract_text_from_responses_api(response)
    
    async def _generate_with_chat_completions_api(
        self,
        messages: List[Dict[str, str]],
        max_tokens: int = 1200,
        enable_web_search: bool = True
    ) -> str:
        """Generate response using OpenAI Chat Completions API."""
        # Set max tokens to generate, respecting model-specific limits
        tokens_to_generate = min(max_tokens, self.max_output_tokens)
        
        openai_messages = self._convert_to_openai_format(messages)
        if not any(msg.get("role") == "system" for msg in openai_messages):
            openai_messages = [
                {"role": "system", "content": "You are a helpful assistant."},
                *openai_messages,
            ]
        
        # Determine if web search can be enabled
        actual_model = self.model_name
        if enable_web_search and self._supports_web_search():
            # For Chat Completions API, web search requires search-enabled model variants
            # Use configured search variant from model card
            actual_model = self._get_search_model_variant()
            if actual_model != self.model_name:
                api_logger.info(f"💬 CHAT_COMPLETIONS: Switching to search variant: {actual_model}")
            
            api_logger.info(f"🔍 CHAT_COMPLETIONS: Web search enabled via model {actual_model}")
        elif enable_web_search:
            api_logger.warning(f"🚫 CHAT_COMPLETIONS: Web search not supported for {self.model_name}")
        else:
            api_logger.info("🚫 CHAT_COMPLETIONS: Web search disabled")
        
        # Make API call
        response = await self._async_client.chat.completions.create(
            model=actual_model,
            messages=openai_messages,
            max_tokens=tokens_to_generate,
            temperature=0.7
        )
        
        return response.choices[0].message.content
    
    def _extract_text_from_responses_api(self, response) -> str:
        """Extract text from OpenAI Responses API response."""
        try:
            # For Responses API, iterate through output items
            text_parts = []
            
            for output_item in response.output:
                if hasattr(output_item, "content"):
                    for content_item in output_item.content:
                        if hasattr(content_item, "text"):
                            text_parts.append(content_item.text)
                        elif hasattr(content_item, "type") and content_item.type == "output_text":
                            text_parts.append(content_item.text)
            
            # Join all text parts
            return "\n".join(text_parts) if text_parts else "No response generated"
            
        except Exception as e:
            # Fallback: try to access output_text directly
            if hasattr(response, "output_text") and response.output_text:
                return response.output_text
            else:
                raise RuntimeError(f"Failed to extract text from Responses API response: {e}")

    async def validate(self) -> bool:
        """Validate OpenAI model functionality."""
        if not self.is_loaded:
            return False

        try:
            # Test basic generation
            response = await self.generate_response(
                "Hello, this is a test message. Please respond with a brief greeting.",
                max_tokens=20
            )
            if not response or len(response) < 1:
                self._error = "Model failed to generate response"
                return False
            return True
            
        except Exception as e:
            self._error = f"Error validating model: {str(e)}"
            return False

    def _convert_to_openai_format(self, messages: List[Dict[str, str]]) -> List[Dict[str, str]]:
        """Convert standard message format to OpenAI format."""
        openai_messages = []
        
        for message in messages:
            role = message.get("role", "user").lower()
            
            # Map to valid OpenAI roles
            if role == "system":
                role = "system"
            elif role == "assistant":
                role = "assistant"
            elif role == "user" or role == "human":
                role = "user"
            else:
                # Default to user for unknown roles
                role = "user"
            
            openai_messages.append({
                "role": role,
                "content": message.get("content", "")
            })
            
        return openai_messages

    def configure(self, **kwargs) -> None:
        """Configure model parameters.
        
        Supported parameters:
        - model_name: str - The specific model to use
        - temperature: float - Controls randomness (0.0 to 1.0)
        - top_p: float - Controls diversity (0.0 to 1.0)
        - max_tokens: int - Maximum tokens to generate
        - response_format: str - Format for response (e.g., "json_object")
        """
        # Track if model has changed
        model_changed = False
        
        # Handle model name changes
        if "model_name" in kwargs and kwargs["model_name"] != self.model_name:
            old_model = self.model_name
            self.model_name = kwargs["model_name"]
            model_changed = True
            api_logger.info(f"Model changed from {old_model} to {self.model_name}")
            
            # Update context window and output tokens based on new model
            self.max_context_length = self._get_context_window()
            self.max_output_tokens = self._get_max_output_tokens()
            self.vision_enabled = self._supports_vision()
        
        # Handle other parameters
        if "temperature" in kwargs:
            self.temperature = max(0.0, min(kwargs["temperature"], 1.0))
            
        if "top_p" in kwargs:
            self.top_p = max(0.0, min(kwargs["top_p"], 1.0))
            
        if "max_tokens" in kwargs:
            self.max_tokens_to_generate = min(kwargs["max_tokens"], self.max_output_tokens)
            
        if "response_format" in kwargs:
            self.response_format = kwargs["response_format"]
            
        # Print configuration info for debugging
        api_logger.info(f"OpenAI model configured: {self.model_name}, temp={self.temperature}, top_p={self.top_p}, "
                       f"max_tokens={self.max_tokens_to_generate}")

    def _generate(self, prompt: str, max_tokens: int) -> str:
        """Synchronous generation - not implemented for OpenAI."""
        raise NotImplementedError("Synchronous generation not supported for OpenAI models. Use async methods instead.")

    async def _generate_async(self, prompt: str, max_tokens: int) -> str:
        """Simple wrapper around generate_response."""
        return await self.generate_response(prompt, max_tokens=max_tokens)
        
    async def stream_chat_completion(
        self,
        messages: List[Dict[str, str]],
        budget: Optional[GenerationBudget] = None,
    ) -> AsyncGenerator[StreamEvent, None]:
        """Generate streaming response with provider-neutral terminal metadata."""
        if not self.is_loaded:
            yield StreamEvent(terminal=terminal_from_error(RuntimeError("Model is not loaded")))
            return

        max_tokens = budget.effective_output_tokens if budget else self.max_output_tokens
        try:
            async for token in self.chat_completion_streaming(messages, max_tokens=max_tokens):
                yield StreamEvent(text=token)
            yield StreamEvent(
                terminal=terminal_from_provider_reason(
                    "unknown",
                    raw={"model": self.model_name, "terminal_metadata_available": False},
                )
            )
        except Exception as exc:
            api_logger.error("OpenAI event streaming error: %s", exc)
            yield StreamEvent(terminal=terminal_from_error(exc))

    async def chat_completion_streaming(
        self,
        messages: List[Dict[str, str]],
        max_tokens: int = 1200,
        enable_web_search: bool = True
    ) -> AsyncGenerator[str, None]:
        """Generate streaming response using appropriate OpenAI API endpoint."""
        if not self.is_loaded:
            raise RuntimeError("Model is not loaded")
        
        try:
            # Set max tokens to generate, respecting model-specific limits
            tokens_to_generate = min(max_tokens, self.max_output_tokens)
            
            # Determine which API to use based on model requirements
            if self._requires_responses_api():
                # Use Responses API for newer models (o-series, GPT-4.1)
                async for chunk in self._stream_with_responses_api(
                    messages, tokens_to_generate, enable_web_search
                ):
                    yield chunk
            else:
                # Use Chat Completions API for older models (GPT-4o, GPT-4, GPT-3.5)
                async for chunk in self._stream_with_chat_completions_api(
                    messages, tokens_to_generate, enable_web_search
                ):
                    yield chunk
                
        except Exception as e:
            api_logger.error(f"OpenAI streaming error: {e}")
            yield f"[Error: {e}]"

    async def _stream_with_responses_api(
        self,
        messages: List[Dict[str, str]],
        max_tokens: int,
        enable_web_search: bool = True
    ) -> AsyncGenerator[str, None]:
        """Generate streaming response using OpenAI Responses API via direct HTTP."""
        try:
            api_logger.info(f"🌊 RESPONSES_API_DIRECT_HTTP: Starting with model={self.model_name}, max_tokens={max_tokens}, web_search={enable_web_search}")
            
            # Import and use the direct HTTP streaming implementation
            from .openai_supporting_files.direct_http_streaming import OpenAIDirectHTTPStreaming
            
            # Create direct HTTP streamer to bypass problematic OpenAI SDK
            http_streamer = OpenAIDirectHTTPStreaming(self.api_key)
            
            try:
                # Direct HTTP stream is synchronous; bridge so the event loop can run other work.
                async for token in async_iter_sync_stream(
                    lambda: http_streamer.stream_responses_api(
                        model=self.model_name,
                        messages=messages,
                        max_tokens=max_tokens,
                        enable_web_search=enable_web_search,
                        reasoning_effort=self._get_reasoning_effort(),
                    ),
                    thread_name="openai-responses-direct-http",
                ):
                    yield token

            except Exception as e:
                api_logger.error(f"💥 RESPONSES_API_DIRECT_HTTP: Error in streaming: {e}")
                raise
                
        except Exception as e:
            api_logger.error(f"💥 RESPONSES_API_DIRECT_HTTP: Error occurred: {e}")
            api_logger.error(f"💥 RESPONSES_API_DIRECT_HTTP: Error type: {type(e).__name__}")
            import traceback
            api_logger.error(f"💥 RESPONSES_API_DIRECT_HTTP: Traceback: {traceback.format_exc()}")
            yield f"[Error: {e}]"

    async def _stream_with_chat_completions_api(
        self,
        messages: List[Dict[str, str]],
        max_tokens: int,
        enable_web_search: bool = True
    ) -> AsyncGenerator[str, None]:
        """Generate streaming response using OpenAI Chat Completions API via direct HTTP."""
        try:
            api_logger.info(f"💬 CHAT_COMPLETIONS_DIRECT_HTTP: Starting with model={self.model_name}, max_tokens={max_tokens}, web_search={enable_web_search}")
            
            # Import and use the direct HTTP streaming implementation
            from .openai_supporting_files.direct_http_streaming import OpenAIDirectHTTPStreaming
            
            # Create direct HTTP streamer to bypass problematic OpenAI SDK
            http_streamer = OpenAIDirectHTTPStreaming(self.api_key)
            
            # Convert messages to OpenAI format for the HTTP implementation
            openai_messages = self._convert_to_openai_format(messages)
            
            # Determine which model variant to use (search-enabled if web search is requested)
            actual_model = self.model_name
            if enable_web_search and self._supports_web_search():
                actual_model = self._get_search_model_variant()
                if actual_model != self.model_name:
                    api_logger.info(f"💬 CHAT_COMPLETIONS_DIRECT_HTTP: Using search variant: {actual_model}")
            
            try:
                # Direct HTTP stream is synchronous; bridge so the event loop can run other work.
                async for token in async_iter_sync_stream(
                    lambda: http_streamer.stream_chat_completions_api(
                        model=actual_model,
                        messages=openai_messages,
                        max_tokens=max_tokens,
                        enable_web_search=False,  # Don't add tools - model variant handles it
                    ),
                    thread_name="openai-chat-completions-direct-http",
                ):
                    yield token

            except Exception as e:
                api_logger.error(f"💥 CHAT_COMPLETIONS_DIRECT_HTTP: Error in streaming: {e}")
                raise
                
        except Exception as e:
            api_logger.error(f"💥 CHAT_COMPLETIONS_DIRECT_HTTP: Error occurred: {e}")
            api_logger.error(f"💥 CHAT_COMPLETIONS_DIRECT_HTTP: Error type: {type(e).__name__}")
            import traceback
            api_logger.error(f"💥 CHAT_COMPLETIONS_DIRECT_HTTP: Traceback: {traceback.format_exc()}")
            yield f"[Error: {e}]"

 