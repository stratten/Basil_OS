import os
import asyncio
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, AsyncGenerator
import base64

from anthropic import Anthropic
from anthropic.types import MessageParam
from anthropic import AsyncAnthropic

from ..base_model import ModelMetadata, ModelState
from ..model_types import ModelCapability
from config.api_keys import get_api_key
from api.core.logging.api_logger import api_logger
from .base_reasoning import BaseReasoningModel
from .streaming_contract import (
    GenerationBudget,
    StreamEvent,
    terminal_from_error,
    terminal_from_provider_reason,
)


from ..models_registry import (
    ModelFeature,
    apply_request_parameter_omissions,
    get_model,
    get_omitted_request_parameters,
    get_thinking_request_config,
    has_feature,
)


class ClaudeModel(BaseReasoningModel):
    """Anthropic Claude model implementation."""
    SHOULD_CHECK_API_KEY = True
    
    def __init__(self, model_path: Path, required_capabilities: Set[ModelCapability]):
        super().__init__(model_path, required_capabilities)
        self._client = None
        self._async_client = None
        
        # Default to Claude Sonnet 4.5 (recommended model with full capabilities)
        self.model_name = "claude-sonnet-4-5-20250929"
        
        # API settings
        self.api_key = None
        self.max_tokens_to_sample = 4000
        self.temperature = 0.7
        self.top_p = 0.9
        
        # Extended thinking flag and settings
        self.extended_thinking_enabled = False
        self.thinking_budget = 40000  # Default thinking budget
        
        # Set context window based on model
        self.max_context_length = self._get_context_window()
        
        # Set max output tokens based on model
        self.max_output_tokens = self._get_max_output_tokens()

    def _get_context_window(self) -> int:
        """Get the context window size for the current model."""
        cfg = get_model(self.model_name)
        if cfg and "context_window" in cfg:
            return cfg["context_window"]
        # Default to 200k for Claude models
        return 200000
        
    def _get_max_output_tokens(self) -> int:
        """Get the maximum output tokens for the current model."""
        cfg = get_model(self.model_name)
        if cfg and "max_output_tokens" in cfg:
            return cfg["max_output_tokens"]
        # Default to 8192 for modern models
        return 8192
        
    def _supports_extended_thinking(self) -> bool:
        """Check if the current model supports registry-declared thinking."""
        return get_thinking_request_config(self.model_name) is not None

    def _thinking_mode(self) -> Optional[str]:
        """Return the registry thinking mode: 'adaptive', 'extended', or None.

        Adaptive models let the provider manage reasoning dynamically and have
        no fixed token budget, so callers must not report a budget for them.
        """
        thinking_cfg = get_thinking_request_config(self.model_name)
        if not thinking_cfg:
            return None
        return "adaptive" if thinking_cfg.get("thinking", {}).get("type") == "adaptive" else "extended"

    def _apply_thinking_to_api_params(self, api_params: Dict[str, Any]) -> None:
        """Inject registry-driven thinking config and drop sampling when required."""
        thinking_cfg = get_thinking_request_config(self.model_name)
        if not thinking_cfg:
            return
        api_params["thinking"] = thinking_cfg["thinking"]
        if thinking_cfg.get("effort"):
            api_params["output_config"] = {"effort": thinking_cfg["effort"]}
        api_params.pop("temperature", None)
        floor = thinking_cfg.get("max_output_tokens_with_thinking")
        max_tokens = api_params.get("max_tokens")
        if isinstance(floor, int) and isinstance(max_tokens, int) and max_tokens < floor:
            api_params["max_tokens"] = floor
        
    def _get_base_model_id(self) -> str:
        """Get the base model ID for API calls (relevant for thinking mode)."""
        cfg = get_model(self.model_name)
        if cfg:
            # Check feature_config for base_model_id
            feature_cfg = cfg.get("feature_config", {}).get("extended_thinking", {})
            if "base_model_id" in feature_cfg:
                return feature_cfg["base_model_id"]
        return self.model_name

    async def load(self) -> None:
        """Load the Claude model by initializing the API client."""
        try:
            self.state = ModelState.LOADING
            api_logger.info(f"Loading Claude model: {self.model_name}")
            
            if ClaudeModel.SHOULD_CHECK_API_KEY:
                # Get API key from key manager
                try:
                    self.api_key = get_api_key("anthropic")
                    api_logger.info("Loaded Anthropic API key from key manager")
                except ValueError:
                    api_logger.error("No Anthropic API key available")
                    raise ValueError("No Anthropic API key available. Please set an API key in the application settings.")
                
                # Initialize Anthropic clients
                self._client = Anthropic(api_key=self.api_key)
                self._async_client = AsyncAnthropic(api_key=self.api_key)
            else:
                api_logger.info("API key check is disabled for ClaudeModel. Skipping API key loading.")

            # Update context window size based on selected model
            self.max_context_length = self._get_context_window()
            
            # Check if extended thinking should be enabled based on model
            cfg = get_model(self.model_name) or {}
            self.extended_thinking_enabled = self._supports_extended_thinking()
            
            # Get thinking budget from registry feature_config
            if self.extended_thinking_enabled:
                feature_cfg = cfg.get("feature_config", {}).get("extended_thinking", {})
                if "budget_tokens" in feature_cfg:
                    self.thinking_budget = feature_cfg["budget_tokens"]
            
            # Update max output tokens after extended thinking settings have been updated
            self.max_output_tokens = self._get_max_output_tokens()
            
            # Log successful initialization
            model_display_name = cfg.get("display_name", self.model_name)
            api_logger.info(f"Claude model {model_display_name} initialized successfully")
            if self.extended_thinking_enabled:
                if self._thinking_mode() == "adaptive":
                    api_logger.info("Adaptive thinking enabled (provider-managed reasoning, no fixed budget)")
                else:
                    api_logger.info(f"Extended thinking enabled with budget of {self.thinking_budget} tokens")
            self.state = ModelState.READY
            
        except Exception as e:
            self.state = ModelState.ERROR
            self._error = f"Failed to load Claude model: {str(e)}"
            api_logger.error(f"Error loading Claude model: {str(e)}")

    async def unload(self) -> None:
        """Unload the Claude model."""
        # No specific cleanup needed for API clients
        self._client = None
        self._async_client = None
        self.state = ModelState.UNLOADED
        api_logger.info("Claude model unloaded successfully")

    def get_metadata(self) -> ModelMetadata:
        """Get model metadata."""
        # Get the display name for the model from registry
        cfg = get_model(self.model_name) or {}
        display_name = cfg.get("display_name", self.model_name)
        description = cfg.get("description", "Cloud-based Anthropic Claude model for reasoning tasks")
        
        # Add thinking information to description if applicable
        thinking_mode = self._thinking_mode()
        extended_thinking_info = ""
        if thinking_mode == "adaptive":
            extended_thinking_info = " with adaptive thinking enabled"
        elif thinking_mode == "extended":
            extended_thinking_info = " with extended thinking enabled"
        
        # Build parameters dictionary
        parameters = {
            "model": self._get_base_model_id(),
            "temperature": self.temperature,
            "top_p": self.top_p,
            "max_tokens": self.max_tokens_to_sample,
            "context_window": self.max_context_length,
            "max_output_tokens": self.max_output_tokens
        }
        
        # Report the concrete thinking mode. Adaptive models have no fixed
        # budget, so only extended (budgeted) thinking surfaces a budget.
        if thinking_mode == "adaptive":
            parameters["adaptive_thinking"] = True
        elif thinking_mode == "extended":
            parameters["extended_thinking"] = True
            parameters["thinking_budget"] = self.thinking_budget
        
        return ModelMetadata(
            name=f"Claude ({display_name}){extended_thinking_info}",
            version="3",
            source="anthropic",
            capabilities={ModelCapability.REASONING},
            description=description,
            parameters=parameters,
            requirements={
                "anthropic": ">=0.5.0"
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
        """Generate a response using Claude."""
        if not self.is_loaded:
            raise RuntimeError("Model is not loaded")

        try:
            # Use model's max_output_tokens when not specified
            if max_tokens is None:
                max_tokens = self.max_output_tokens
            
            # Set max tokens to generate, respecting model-specific limits
            tokens_to_sample = min(max_tokens, self.max_output_tokens)
            
            # DEBUG: Log the actual token calculation
            api_logger.info(f"🔍 [TOKEN DEBUG] max_tokens parameter: {max_tokens}")
            api_logger.info(f"🔍 [TOKEN DEBUG] self.max_output_tokens: {self.max_output_tokens}")
            api_logger.info(f"🔍 [TOKEN DEBUG] tokens_to_sample (final): {tokens_to_sample}")
            
            # Create a system prompt if context is provided
            system = None
            if context and "system_prompt" in context:
                system = context["system_prompt"]
            
            # Create a single user message
            messages = [{"role": "user", "content": prompt}]
            
            # Prepare API call parameters
            api_params = {
                "model": self._get_base_model_id(),
                "messages": messages,
                "max_tokens": tokens_to_sample,
            }
            api_params["temperature"] = self.temperature
            api_params = apply_request_parameter_omissions(
                api_params,
                get_omitted_request_parameters(self.model_name),
            )
            self._apply_thinking_to_api_params(api_params)
            # Note: top_p removed - Claude 4.5+ models don't allow both temperature and top_p
            
            # DEBUG: Log the actual API parameters
            api_logger.info(f"🔍 [API DEBUG] Final API call max_tokens: {api_params['max_tokens']}")
            
            # Add system message if provided
            if system:
                api_params["system"] = system
            
            # Add web search tool if enabled and model supports it  
            if enable_web_search and self._supports_web_search():
                api_params["tools"] = self._get_web_search_tool_config()
                api_logger.info("Web search tool enabled for Claude")
            
            # Check if we're in a fresh event loop (like when called via asyncio.run)
            import asyncio
            import threading
            current_thread = threading.current_thread()
            
            try:
                current_loop = asyncio.get_running_loop()
                api_logger.info(f"🔍 [DEBUG] Running in thread: {current_thread.name}, loop: {id(current_loop)}")
            except RuntimeError:
                current_loop = None
                api_logger.info(f"🔍 [DEBUG] No running loop in thread: {current_thread.name}")
            
            # Use streaming for all API calls to avoid Anthropic's timeout error
            # for large max_tokens values (>8K triggers "streaming required" error).
            # Using stream.get_final_message() returns the same response format as non-streaming.
            if enable_web_search and self._supports_web_search():
                api_logger.info("🔍 [DEBUG] About to call async client with web search enabled (streaming)")
                async with self._async_client.messages.stream(**api_params) as stream:
                    response = await stream.get_final_message()
                api_logger.info("🔍 [DEBUG] Async client call with web search completed")
            else:
                api_logger.info("🔍 [DEBUG] About to call async client without web search (streaming)")
                
                # If we detect we're in a problematic threading context, use sync client
                if (current_thread.name.startswith('ThreadPoolExecutor') or 
                    'run_agent_task_in_thread' in current_thread.name):
                    api_logger.info("🔍 [DEBUG] Using sync client due to threading context (streaming)")
                    # Use sync client in thread pool context with streaming
                    with self._client.messages.stream(**api_params) as stream:
                        response = stream.get_final_message()
                else:
                    # Use async client in normal context with streaming
                    async with self._async_client.messages.stream(**api_params) as stream:
                        response = await stream.get_final_message()
                    
                api_logger.info("🔍 [DEBUG] Async client call without web search completed")
            
            api_logger.info("🔍 [DEBUG] Starting response processing")
            return self._extract_text_from_message(response)
            
        except Exception as e:
            api_logger.error(f"Error generating response from Claude: {str(e)}")
            raise RuntimeError(f"Error generating response: {str(e)}")

    async def generate_from_messages(
        self,
        messages: List[Dict[str, str]],
        *,
        max_tokens: Optional[int] = None,
        preserve_thinking: bool = False,
        enable_web_search: bool = True,
    ) -> str:
        """Generate from role-tagged messages using Anthropic's native format."""
        if not self.is_loaded:
            raise RuntimeError("Model is not loaded")

        try:
            budget = max_tokens if max_tokens is not None else self.max_output_tokens
            api_params = self._build_streaming_api_params(
                messages,
                max_tokens=budget,
                enable_web_search=enable_web_search,
            )
            self._apply_thinking_to_api_params(api_params)

            import threading

            current_thread = threading.current_thread()

            if enable_web_search and self._supports_web_search():
                async with self._async_client.messages.stream(**api_params) as stream:
                    response = await stream.get_final_message()
            elif (
                current_thread.name.startswith("ThreadPoolExecutor")
                or "run_agent_task_in_thread" in current_thread.name
            ):
                with self._client.messages.stream(**api_params) as stream:
                    response = stream.get_final_message()
            else:
                async with self._async_client.messages.stream(**api_params) as stream:
                    response = await stream.get_final_message()

            return self._extract_text_from_message(response)
        except Exception as e:
            api_logger.error(f"Error generating from messages with Claude: {str(e)}")
            raise RuntimeError(f"Error generating from messages: {str(e)}")

    def _extract_text_from_message(self, response) -> str:
        """Extract assistant text from an Anthropic Message, including web-search metadata."""
        response_text = ""
        search_queries: List[str] = []
        sources: List[str] = []

        api_logger.info(f"🔍 [DEBUG] Processing {len(response.content)} content blocks")
        for i, content_block in enumerate(response.content):
            api_logger.info(f"🔍 [DEBUG] Processing content block {i}: {type(content_block)}")
            if hasattr(content_block, "text"):
                response_text += content_block.text
                api_logger.info(f"🔍 [DEBUG] Added text block: {len(content_block.text)} chars")
            elif hasattr(content_block, "type") and content_block.type == "tool_use":
                if hasattr(content_block, "input") and "query" in content_block.input:
                    search_queries.append(content_block.input["query"])
                    api_logger.info(
                        f"🔍 [DEBUG] Added search query: {content_block.input['query']}"
                    )
            elif hasattr(content_block, "type") and content_block.type == "tool_result":
                if hasattr(content_block, "content") and isinstance(content_block.content, list):
                    for result_item in content_block.content:
                        if hasattr(result_item, "text"):
                            text_content = result_item.text
                            if "http" in text_content or "source:" in text_content.lower():
                                sources.append(text_content)
                                api_logger.info(
                                    f"🔍 [DEBUG] Added source: {text_content[:50]}..."
                                )
            else:
                api_logger.warning(
                    f"🔍 [DEBUG] Skipping unsupported content block type: {type(content_block)}"
                )

        api_logger.info(
            f"🔍 [DEBUG] Content processing complete. Response length: {len(response_text)}"
        )

        if search_queries:
            api_logger.info(
                f"🔍 [DEBUG] Formatting web search response with {len(search_queries)} queries"
            )
            response_text = self._format_web_search_response(
                response_text, search_queries, sources
            )
            api_logger.info("🔍 [DEBUG] Web search formatting complete")

        api_logger.info(f"🔍 [DEBUG] Returning response: {len(response_text)} chars")
        return response_text

    def _format_web_search_response(self, response_text: str, search_queries: List[str], sources: List[str]) -> str:
        """Format web search responses to separate thinking messages from main content."""
        
        # Common patterns that indicate "thinking" or search status messages
        thinking_patterns = [
            r"Let me search for .*?\.",
            r"I'll search for .*?\.",
            r"Searching for .*?\.",
            r"Let me look up .*?\.",
            r"I need to find .*?\.",
            r"Let me research .*?\.",
            r"I'll help you research .*?\. Let me search for .*?\."
        ]
        
        # Split response into lines for processing
        lines = response_text.split('\n')
        thinking_lines = []
        content_lines = []
        
        for line in lines:
            is_thinking = False
            for pattern in thinking_patterns:
                if re.match(pattern, line.strip(), re.IGNORECASE):
                    thinking_lines.append(line.strip())
                    is_thinking = True
                    break
            
            if not is_thinking:
                content_lines.append(line)
        
        # Reconstruct the response with better formatting
        formatted_response = ""
        
        # Add thinking/search status section if we found any
        if thinking_lines:
            formatted_response += "**🔍 Research Process:**\n"
            for i, thinking in enumerate(thinking_lines, 1):
                # Clean up repetitive "Let me search" messages
                if i > 1 and thinking.startswith("Let me search for more specific"):
                    thinking = f"Refining search: {thinking[len('Let me search for '):]}"
                elif thinking.startswith("Let me search for"):
                    thinking = f"Searching: {thinking[len('Let me search for '):]}"
                elif thinking.startswith("I'll help you research"):
                    thinking = f"Starting research: {thinking.split('Let me search for')[1] if 'Let me search for' in thinking else thinking}"
                
                formatted_response += f"• {thinking}\n"
            
            formatted_response += "\n---\n\n"
        
        # Add the main content
        main_content = '\n'.join(content_lines).strip()
        
        # Remove any duplicate research process mentions from main content
        for pattern in thinking_patterns:
            main_content = re.sub(pattern, '', main_content, flags=re.IGNORECASE)
        
        # Clean up extra whitespace
        main_content = re.sub(r'\n\n+', '\n\n', main_content).strip()
        
        formatted_response += main_content
        
        # Add sources section if we have any
        if sources:
            formatted_response += "\n\n**📚 Sources:**\n"
            for source in sources[:5]:  # Limit to 5 sources to avoid clutter
                formatted_response += f"• {source}\n"
        
        # Add search queries as metadata (for debugging/transparency)
        if search_queries and len(search_queries) > 0:
            api_logger.info(f"Web search performed {len(search_queries)} queries: {search_queries}")
        
        return formatted_response

    def _supports_web_search(self) -> bool:
        """Check if the current model supports web search capabilities."""
        return has_feature(self.model_name, ModelFeature.WEB_SEARCH)
    
    def _get_web_search_tool_config(self) -> List[Dict[str, Any]]:
        """Get the web search tool configuration for API calls."""
        return [
            {
                "type": "web_search_20250305",
                "name": "web_search",
                "max_uses": 5
            }
        ]

    async def validate(self) -> bool:
        """Validate Claude model functionality."""
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
            self._error = f"Validation failed: {str(e)}"
            return False

    def _convert_to_anthropic_format(self, messages: List[Dict[str, str]]) -> List[MessageParam]:
        """Convert standard message format to Anthropic format."""
        anthropic_messages = []
        system_content = None
        
        for msg in messages:
            role = msg["role"].lower()
            content = msg["content"]
            
            if role == "system":
                # Set as system prompt (or content)
                system_content = content
            elif role == "user":
                anthropic_messages.append({"role": "user", "content": content})
            elif role == "assistant":
                anthropic_messages.append({"role": "assistant", "content": content})
            # Skip 'error' or other roles
        
        return anthropic_messages

    def configure(self, **kwargs) -> None:
        """Configure Claude specific parameters."""
        super().configure(**kwargs)
        
        # Handle model name changes
        if 'model_name' in kwargs:
            old_model_name = self.model_name
            self.model_name = kwargs['model_name']
            
            # Update context length when model changes
            self.max_context_length = self._get_context_window()
            
            # Update extended thinking settings based on the new model
            self.extended_thinking_enabled = self._supports_extended_thinking()
            if self.extended_thinking_enabled:
                cfg = get_model(self.model_name) or {}
                feature_cfg = cfg.get("feature_config", {}).get("extended_thinking", {})
                if "budget_tokens" in feature_cfg:
                    self.thinking_budget = feature_cfg["budget_tokens"]
            
            # Update max output tokens after extended thinking settings have been updated
            self.max_output_tokens = self._get_max_output_tokens()
            
            api_logger.info(f"Model changed from {old_model_name} to {self.model_name}")
            if self.extended_thinking_enabled:
                if self._thinking_mode() == "adaptive":
                    api_logger.info("Adaptive thinking enabled (provider-managed reasoning, no fixed budget)")
                else:
                    api_logger.info(f"Extended thinking enabled with budget of {self.thinking_budget} tokens")
        
        # Handle extended thinking configuration
        if 'extended_thinking_enabled' in kwargs:
            requested_thinking = bool(kwargs['extended_thinking_enabled'])
            
            # Only enable if the model supports it
            if requested_thinking and not self._supports_extended_thinking():
                api_logger.warning(f"Extended thinking requested but not supported by model {self.model_name}")
                self.extended_thinking_enabled = False
            else:
                self.extended_thinking_enabled = requested_thinking
            
            # Update max output tokens after extended thinking settings have been updated
            self.max_output_tokens = self._get_max_output_tokens()
            
            api_logger.info(f"Extended thinking {'enabled' if self.extended_thinking_enabled else 'disabled'}")
        
        if 'thinking_budget' in kwargs and self.extended_thinking_enabled:
            self.thinking_budget = int(kwargs['thinking_budget'])
            api_logger.info(f"Thinking budget set to {self.thinking_budget} tokens")
        
        # Handle token limits
        if 'max_tokens_to_sample' in kwargs:
            # Ensure we don't exceed model-specific limits
            specified_max = int(kwargs['max_tokens_to_sample'])
            self.max_tokens_to_sample = min(specified_max, self.max_output_tokens)
            api_logger.info(f"Max tokens to sample set to {self.max_tokens_to_sample}")

    def _generate(self, prompt: str, max_tokens: int) -> str:
        """Synchronous generation - not supported for Claude (API-based)."""
        raise NotImplementedError("Synchronous generation not supported for Claude models. Use async methods instead.")

    async def _generate_async(self, prompt: str, max_tokens: int) -> str:
        """Internal method for asynchronous text generation."""
        return await self.generate_response(prompt, max_tokens=max_tokens)
        
    async def stream_chat_completion(
        self,
        messages: List[Dict[str, str]],
        budget: Optional[GenerationBudget] = None,
    ) -> AsyncGenerator[StreamEvent, None]:
        """Stream Claude tokens with provider terminal metadata."""
        if not self.is_loaded:
            yield StreamEvent(terminal=terminal_from_error(RuntimeError("Model is not loaded")))
            return

        try:
            api_params = self._build_streaming_api_params(
                messages,
                max_tokens=budget.effective_output_tokens if budget else self.max_tokens_to_sample,
            )
            api_logger.info(
                "Starting Claude event stream with %s messages and max_tokens=%s",
                len(api_params.get("messages") or []),
                api_params.get("max_tokens"),
            )
            final_message = None
            async with self._async_client.messages.stream(**api_params) as stream:
                async for text_chunk in stream.text_stream:
                    yield StreamEvent(text=text_chunk)
                try:
                    final_message = await stream.get_final_message()
                except Exception as final_err:
                    api_logger.warning("Claude stream final-message metadata unavailable: %s", final_err)

            stop_reason = getattr(final_message, "stop_reason", None) if final_message is not None else None
            usage = getattr(final_message, "usage", None) if final_message is not None else None
            output_tokens = getattr(usage, "output_tokens", None) if usage is not None else None
            yield StreamEvent(
                terminal=terminal_from_provider_reason(
                    stop_reason or "completed",
                    output_tokens=output_tokens,
                    raw={"model": self._get_base_model_id()},
                )
            )
            api_logger.info("Claude event stream completed with stop_reason=%s", stop_reason)
        except Exception as exc:
            api_logger.error("Error streaming response from Claude: %s", str(exc))
            yield StreamEvent(terminal=terminal_from_error(exc))

    def _build_streaming_api_params(
        self,
        messages: List[Dict[str, str]],
        *,
        max_tokens: int,
        enable_web_search: bool = True,
    ) -> Dict[str, Any]:
        """Build Anthropic streaming request parameters."""
        anthropic_messages = self._convert_to_anthropic_format(messages)
        if not anthropic_messages:
            anthropic_messages = [{"role": "user", "content": "Hello"}]

        system = None
        if len(messages) > 0 and messages[0]["role"].lower() == "system":
            system = messages[0]["content"]

        api_params: Dict[str, Any] = {
            "model": self._get_base_model_id(),
            "messages": anthropic_messages,
            "max_tokens": min(int(max_tokens), int(self.max_output_tokens)),
            "temperature": self.temperature,
        }
        api_params = apply_request_parameter_omissions(
            api_params,
            get_omitted_request_parameters(self.model_name),
        )

        if system:
            api_params["system"] = system
        if enable_web_search and self._supports_web_search():
            api_params["tools"] = self._get_web_search_tool_config()
            api_logger.info("Web search tool enabled for Claude streaming")
        return api_params

    async def chat_completion_streaming(self, messages: List[Dict[str, str]]) -> AsyncGenerator[str, None]:
        """Stream tokens from Claude API."""
        if not self.is_loaded:
            raise RuntimeError("Model is not loaded")
        
        try:
            async for event in self.stream_chat_completion(messages):
                if event.text:
                    yield event.text
            
            api_logger.info("Claude streaming response completed")
                
        except Exception as e:
            api_logger.error(f"Error streaming response from Claude: {str(e)}")
            raise RuntimeError(f"Error streaming response: {str(e)}") 
    
    # ===== NEW FILE-AWARE METHODS =====
    
    async def generate_response_with_files(
        self,
        prompt: str,
        file_contents: List[Dict[str, Any]] = None,
        file_paths: List[str] = None,
        context: Dict[str, Any] = None,
        max_tokens: Optional[int] = None,
        enable_web_search: bool = True
    ) -> str:
        """
        Generate a response with file attachments using Claude.
        
        Args:
            prompt: The text prompt
            file_contents: List of file data dictionaries (with base64 content) OR
            file_paths: List of file paths to load (for agent integration) 
            context: Optional context dictionary
            max_tokens: Maximum tokens to generate
            enable_web_search: Whether to enable web search (if supported)
            
        Returns:
            Generated response as string
            
        Note:
            Provide either file_contents OR file_paths, not both.
            file_paths is preferred for agent integration to avoid storing large base64 data.
        """
        if not self.is_loaded:
            raise RuntimeError("Model is not loaded")

        # Validate input parameters
        if file_contents and file_paths:
            raise ValueError("Provide either file_contents OR file_paths, not both")
        
        if not file_contents and not file_paths:
            raise ValueError("Must provide either file_contents or file_paths")

        try:
            # Lazy import to avoid circular dependency
            from api.services.agent_processing.tools.direct_application_interactions.file_system.anthropic_file_handler import AnthropicFileHandler
            
            # Initialize the file handler
            file_handler = AnthropicFileHandler()
            
            # Load files from paths if provided
            if file_paths:
                api_logger.info(f"📁 Loading {len(file_paths)} files from paths for Claude API")
                file_contents = await file_handler.load_files_from_paths(file_paths)
                if not file_contents:
                    raise ValueError("No valid files could be loaded from provided paths")
            
            # Use model's max_output_tokens when not specified
            if max_tokens is None:
                max_tokens = self.max_output_tokens
            
            # Set max tokens to generate, respecting model-specific limits
            tokens_to_sample = min(max_tokens, self.max_output_tokens)
            
            api_logger.info(f"🔍 [FILE DEBUG] Generating response with {len(file_contents)} files")
            api_logger.info(f"🔍 [TOKEN DEBUG] tokens_to_sample: {tokens_to_sample}")
            
            # Validate request size first
            size_validation = file_handler.validate_request_size(file_contents, prompt)
            if not size_validation['valid']:
                api_logger.warning(f"Request size validation failed: {size_validation['error']}")
                # Use only files that fit
                file_contents = size_validation['files_that_fit']
                if size_validation['files_excluded']:
                    api_logger.info(f"Excluded {len(size_validation['files_excluded'])} files due to size limits")
            
            # Create mixed content message with files
            content_blocks = file_handler.create_mixed_content_message(prompt, file_contents)
            
            # Create system prompt if context is provided
            system = None
            if context and "system_prompt" in context:
                system = context["system_prompt"]
            
            # Create messages with mixed content
            messages = [{"role": "user", "content": content_blocks}]
            
            # Prepare API call parameters
            api_params = {
                "model": self._get_base_model_id(),
                "messages": messages,
                "max_tokens": tokens_to_sample,
                "temperature": self.temperature
                # Note: top_p removed - Claude 4.5+ models don't allow both temperature and top_p
            }
            api_params = apply_request_parameter_omissions(
                api_params,
                get_omitted_request_parameters(self.model_name),
            )
            self._apply_thinking_to_api_params(api_params)
            
            # Add system message if provided
            if system:
                api_params["system"] = system
                
            # Add web search tool if model supports it and enabled
            if enable_web_search and self._supports_web_search():
                api_params["tools"] = self._get_web_search_tool_config()
            
            api_logger.info(f"🚀 Sending request to Claude with files (total blocks: {len(content_blocks)})")
            
            # CRITICAL DEBUG: Log the exact message structure being sent
            api_logger.info(f"🔍 [MESSAGE DEBUG] Full API params structure:")
            api_logger.info(f"  - Model: {api_params['model']}")
            api_logger.info(f"  - Max tokens: {api_params['max_tokens']}")
            api_logger.info(f"  - Messages count: {len(api_params['messages'])}")
            
            # Debug the message content structure
            for i, message in enumerate(api_params['messages']):
                api_logger.info(f"  - Message {i}: role={message['role']}, content_type={type(message['content'])}")
                if isinstance(message['content'], list):
                    api_logger.info(f"    Content blocks: {len(message['content'])}")
                    for j, block in enumerate(message['content']):
                        block_type = block.get('type', 'unknown')
                        api_logger.info(f"      Block {j}: type={block_type}")
                        if block_type == 'document' and 'source' in block:
                            source = block['source']
                            api_logger.info(f"        Source type: {source.get('type')}")
                            api_logger.info(f"        Media type: {source.get('media_type')}")
                            api_logger.info(f"        Data length: {len(source.get('data', ''))}")
            
            # Make the API call with streaming to avoid Anthropic timeout for large max_tokens
            # NOTE: anthropic-beta header only needed for Files API (file_id), not base64 content
            async with self._async_client.messages.stream(**api_params) as stream:
                response = await stream.get_final_message()
            
            # Extract text from response, handling different content block types
            response_text = ""
            search_queries: List[str] = []
            sources: List[str] = []

            api_logger.info(f"🔍 [DEBUG] Processing {len(response.content)} content blocks (file-aware)")
            for i, content_block in enumerate(response.content):
                api_logger.info(f"🔍 [DEBUG] Content block {i}: {type(content_block)}")
                # Standard text content
                if hasattr(content_block, 'text'):
                    response_text += content_block.text
                    continue
                # Tool use / tool result blocks
                if hasattr(content_block, 'type') and content_block.type == 'tool_use':
                    try:
                        if hasattr(content_block, 'input') and 'query' in content_block.input:
                            search_queries.append(content_block.input['query'])
                    except Exception:
                        pass
                    continue
                if hasattr(content_block, 'type') and content_block.type == 'tool_result':
                    try:
                        if hasattr(content_block, 'content') and isinstance(content_block.content, list):
                            for result_item in content_block.content:
                                if hasattr(result_item, 'text'):
                                    txt = result_item.text
                                    if isinstance(txt, str) and ("http" in txt or 'source:' in txt.lower()):
                                        sources.append(txt)
                    except Exception:
                        pass
                    continue
                # Skip other block types (do not concatenate non-text to string)
                api_logger.warning(f"🔍 [DEBUG] Skipping non-text content block in file-aware response: {type(content_block)}")

            api_logger.info(f"🔍 [DEBUG] File-aware response length: {len(response_text)}")
            return response_text.strip()
            
        except Exception as e:
            api_logger.error(f"❌ Error generating response with files from Claude: {str(e)}")
            # DO NOT fall back to text-only - this misleads users into thinking files aren't attached
            # If file processing fails, we should fail clearly rather than silently dropping files
            if "overloaded" in str(e).lower() or "529" in str(e):
                raise RuntimeError(f"Claude API is currently overloaded and cannot process file attachments. Please try again in a moment. Original error: {str(e)}")
            else:
                raise RuntimeError(f"Failed to process files with Claude API. Original error: {str(e)}")
    
    async def chat_completion_streaming_with_files(
        self, 
        messages: List[Dict[str, str]], 
        file_contents: List[Dict[str, Any]] = None,
        file_paths: List[str] = None
    ) -> AsyncGenerator[str, None]:
        """
        Stream tokens from Claude API with file attachments.
        
        Args:
            messages: List of message dictionaries
            file_contents: List of file data dictionaries (with base64 content) OR
            file_paths: List of file paths to load (for agent integration)
            
        Yields:
            Text chunks as they arrive from Claude
            
        Note:
            Provide either file_contents OR file_paths, not both.
            file_paths is preferred for agent integration to avoid storing large base64 data.
        """
        if not self.is_loaded:
            raise RuntimeError("Model is not loaded")
        
        # Validate input parameters
        if file_contents and file_paths:
            raise ValueError("Provide either file_contents OR file_paths, not both")
        
        if not file_contents and not file_paths:
            raise ValueError("Must provide either file_contents or file_paths")
        
        try:
            # Lazy import to avoid circular dependency
            from api.services.agent_processing.tools.direct_application_interactions.file_system.anthropic_file_handler import AnthropicFileHandler
            
            # Initialize the file handler
            file_handler = AnthropicFileHandler()
            
            # Load files from paths if provided
            if file_paths:
                api_logger.info(f"📁 Loading {len(file_paths)} files from paths for streaming")
                file_contents = await file_handler.load_files_from_paths(file_paths)
                if not file_contents:
                    raise ValueError("No valid files could be loaded from provided paths")
            
            api_logger.info(f"🔍 [FILE STREAM DEBUG] Streaming with {len(file_contents)} files")
            
            # Validate request size first
            size_validation = file_handler.validate_request_size(
                file_contents, 
                ' '.join([msg.get('content', '') for msg in messages])
            )
            if not size_validation['valid']:
                api_logger.warning(f"Streaming request size validation failed: {size_validation['error']}")
                file_contents = size_validation['files_that_fit']
            
            # Convert to Anthropic format
            anthropic_messages = self._convert_to_anthropic_format(messages)
            
            # If we have files, modify the last user message to include files
            if file_contents and anthropic_messages:
                last_message = anthropic_messages[-1]
                if last_message["role"] == "user":
                    # Get the existing text content
                    existing_content = last_message["content"]
                    if isinstance(existing_content, str):
                        # Convert string content to mixed content with files
                        content_blocks = file_handler.create_mixed_content_message(existing_content, file_contents)
                        last_message["content"] = content_blocks
                    else:
                        api_logger.warning("Last message already has complex content, appending files")
                        # If it's already a list, add file blocks
                        for file_data in file_contents:
                            try:
                                file_block = file_handler.format_for_anthropic_api(file_data)
                                existing_content.append(file_block)
                            except Exception as e:
                                api_logger.error(f"Failed to add file to streaming message: {e}")
            
            # If no messages, provide a default with files
            if not anthropic_messages:
                if file_contents:
                    content_blocks = file_handler.create_mixed_content_message("Hello", file_contents)
                    anthropic_messages = [{"role": "user", "content": content_blocks}]
                else:
                    anthropic_messages = [{"role": "user", "content": "Hello"}]
            
            # Extract system message if present
            system = None
            if len(messages) > 0 and messages[0]["role"].lower() == "system":
                system = messages[0]["content"]
            
            # Prepare API call parameters
            api_params = {
                "model": self._get_base_model_id(),
                "messages": anthropic_messages,
                "max_tokens": self.max_tokens_to_sample,
                "temperature": self.temperature
                # Note: top_p removed - Claude 4.5+ models don't allow both temperature and top_p
            }
            api_params = apply_request_parameter_omissions(
                api_params,
                get_omitted_request_parameters(self.model_name),
            )
            self._apply_thinking_to_api_params(api_params)
            
            # Add system message if provided
            if system:
                api_params["system"] = system
                
            # Add web search tool if model supports it
            if self._supports_web_search():
                api_params["tools"] = self._get_web_search_tool_config()
            
            api_logger.info(f"🚀 Starting Claude file streaming (messages: {len(anthropic_messages)})")
            
            # Stream the response
            with self._client.messages.stream(
                **api_params
            ) as stream:
                for text_chunk in stream.text_stream:
                    yield text_chunk
            
            api_logger.info("✅ Claude file streaming completed")
                
        except Exception as e:
            api_logger.error(f"❌ Error streaming response with files from Claude: {str(e)}")
            # DO NOT fall back to text-only - this misleads users into thinking files aren't attached
            # If file processing fails, we should fail clearly rather than silently dropping files
            if "overloaded" in str(e).lower() or "529" in str(e):
                raise RuntimeError(f"Claude API is currently overloaded and cannot process file attachments. Please try again in a moment. Original error: {str(e)}")
            else:
                raise RuntimeError(f"Failed to process files with Claude API. Original error: {str(e)}") 