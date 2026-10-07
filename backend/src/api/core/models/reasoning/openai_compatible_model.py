"""
OpenAI-Compatible Model - Handler for any OpenAI-compatible API endpoint.

This model supports connecting to:
- Local inference servers: Ollama, LM Studio, vLLM, llama.cpp server.
- Cloud providers: Together AI, Groq, Fireworks, Anyscale, Mistral API.
- Any endpoint implementing the OpenAI Chat Completions API.

Configuration is sourced from the custom models registry.
"""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, AsyncGenerator

from openai import OpenAI, AsyncOpenAI

from ..base_model import ModelMetadata, ModelState
from ..model_types import ModelCapability
from .base_reasoning import BaseReasoningModel
from ..models_registry import get_model, has_feature, ModelFeature
from config.api_keys import get_api_key
from .ollama_native_chat import (
    OllamaContextWindowFilled,
    build_ollama_chat_body,
    ollama_context_tokens_used,
    ollama_native_root,
    stream_ollama_chat,
    uses_ollama_native_chat,
)

logger = logging.getLogger(__name__)


class OpenAICompatibleModel(BaseReasoningModel):
    """Model handler for OpenAI-compatible API endpoints."""
    
    def __init__(self, model_path: Path, required_capabilities: Set[ModelCapability]):
        """Initialize the OpenAI-compatible model.
        
        Args:
            model_path: Not used for API models, but required by base class.
            required_capabilities: Required model capabilities.
        """
        super().__init__(model_path, required_capabilities)
        self._client: Optional[OpenAI] = None
        self._async_client: Optional[AsyncOpenAI] = None
        
        # These will be populated from registry config.
        self.model_name: str = ""
        self.model_identifier: str = ""  # The model name sent to the API.
        self.base_url: str = ""
        self.api_key: Optional[str] = None
        self.api_key_name: Optional[str] = None
        self.requires_auth: bool = False
        self.server_type: str = "openai_compatible"
        
        # API settings.
        self.temperature: float = 0.7
        self.top_p: float = 0.9
        
        # Context limits - MUST be set from registry, no sensible defaults.
        self.max_context_length: int = 0
        self.max_output_tokens: int = 0
        
        # Feature flags - default to False, enabled from registry.
        self.supports_streaming: bool = False
        self.supports_system_prompts: bool = False
    
    def set_model_name(self, model_name: str) -> None:
        """Set the model name and load configuration from registry.
        
        Args:
            model_name: The model ID in the custom models registry.
        """
        self.model_name = model_name
        self._load_config_from_registry()
    
    def _load_config_from_registry(self) -> None:
        """Load configuration from the models registry.
        
        Raises:
            ValueError: If required configuration is missing.
        """
        cfg = get_model(self.model_name)
        if not cfg:
            raise ValueError(f"No registry config found for custom model '{self.model_name}'")
        
        # Required fields - these must be provided by the user.
        self.base_url = cfg.get("base_url")
        if not self.base_url:
            raise ValueError(f"Custom model '{self.model_name}' is missing required 'base_url'")
        
        self.model_identifier = cfg.get("model_identifier")
        if not self.model_identifier:
            raise ValueError(f"Custom model '{self.model_name}' is missing required 'model_identifier'")
        
        self.max_context_length = cfg.get("context_window")
        if not self.max_context_length:
            raise ValueError(f"Custom model '{self.model_name}' is missing required 'context_window'")
        
        self.max_output_tokens = cfg.get("max_output_tokens")
        if not self.max_output_tokens:
            raise ValueError(f"Custom model '{self.model_name}' is missing required 'max_output_tokens'")
        
        # Optional auth fields.
        self.requires_auth = cfg.get("requires_auth", False)
        self.api_key_name = cfg.get("api_key_name")
        self.server_type = str(cfg.get("server_type") or "openai_compatible")
        
        # Feature detection from user-defined features.
        features = cfg.get("features", [])
        feature_values = [f.value if hasattr(f, "value") else f for f in features]
        self.supports_streaming = "streaming" in feature_values
        self.supports_system_prompts = "system_prompts" in feature_values
        
        logger.info(f"Loaded config for {self.model_name}: base_url={self.base_url}, "
                   f"model_identifier={self.model_identifier}, context={self.max_context_length}, "
                   f"max_output={self.max_output_tokens}, requires_auth={self.requires_auth}, "
                   f"server_type={self.server_type}")
    
    def _get_api_key(self) -> Optional[str]:
        """Get the API key if required.
        
        Returns:
            API key string, or None if not required.
        """
        if not self.requires_auth:
            return None
        
        if not self.api_key_name:
            logger.warning(f"Model {self.model_name} requires auth but no api_key_name configured")
            return None
        
        try:
            return get_api_key(self.api_key_name)
        except ValueError:
            logger.warning(f"No API key found for '{self.api_key_name}'")
            return None
    
    async def load(self) -> None:
        """Load the model by initializing the API client."""
        try:
            self.state = ModelState.LOADING
            logger.info(f"Loading OpenAI-compatible model: {self.model_name}")
            
            # Get API key if required.
            self.api_key = self._get_api_key()
            
            if self.requires_auth and not self.api_key:
                raise ValueError(f"API key required for {self.model_name} but not available")
            
            # Validate base_url.
            if not self.base_url:
                raise ValueError(f"No base_url configured for {self.model_name}")
            
            # Initialize clients.
            # For local endpoints without auth, use a dummy key (some servers require it).
            api_key_for_client = self.api_key or "not-needed"
            
            self._client = OpenAI(
                api_key=api_key_for_client,
                base_url=self.base_url,
            )
            self._async_client = AsyncOpenAI(
                api_key=api_key_for_client,
                base_url=self.base_url,
            )
            
            logger.info(f"OpenAI-compatible model {self.model_name} initialized: "
                       f"endpoint={self.base_url}, model={self.model_identifier}")
            self.state = ModelState.READY
            
        except Exception as e:
            self.state = ModelState.ERROR
            self._error = f"Failed to load OpenAI-compatible model: {str(e)}"
            logger.error(f"Error loading OpenAI-compatible model: {str(e)}")
            raise
    
    async def unload(self) -> None:
        """Unload the model."""
        self._client = None
        self._async_client = None
        self.state = ModelState.UNLOADED
        logger.info(f"OpenAI-compatible model {self.model_name} unloaded")
    
    async def generate_response(
        self,
        prompt: str,
        context: Optional[Dict[str, Any]] = None,
        max_tokens: Optional[int] = None,
        preserve_thinking: bool = False,
    ) -> str:
        """Generate a response to a prompt.
        
        Args:
            prompt: The input prompt.
            context: Optional context dictionary.
            max_tokens: Maximum tokens to generate.
            
        Returns:
            Generated response text.
        """
        if self._async_client is None:
            raise RuntimeError("Model not loaded")
        
        # Default to registry-configured max_output_tokens
        if max_tokens is None:
            max_tokens = self.max_output_tokens
        tokens_to_sample = min(max_tokens, self.max_output_tokens)
        
        messages: List[Dict[str, str]] = []
        
        # Add system message if context provides one.
        if context and "system_prompt" in context and self.supports_system_prompts:
            messages.append({"role": "system", "content": context["system_prompt"]})
        
        # Add user message.
        messages.append({"role": "user", "content": prompt})
        
        try:
            native_root = self._ollama_native_root()
            if native_root is not None:
                return "".join([text async for text in self._stream_ollama_text(native_root, messages, tokens_to_sample)])
            response = await self._async_client.chat.completions.create(
                model=self.model_identifier,
                messages=messages,
                max_tokens=tokens_to_sample,
                temperature=self.temperature,
            )
            
            return response.choices[0].message.content or ""
            
        except Exception as e:
            logger.error(f"Error generating response: {e}")
            raise
    
    async def generate_response_stream(
        self,
        prompt: str,
        context: Optional[Dict[str, Any]] = None,
        max_tokens: Optional[int] = None,
    ) -> AsyncGenerator[str, None]:
        """Generate a streaming response to a prompt.
        
        Args:
            prompt: The input prompt.
            context: Optional context dictionary.
            max_tokens: Maximum tokens to generate.
            
        Yields:
            Response text chunks.
        """
        if self._async_client is None:
            raise RuntimeError("Model not loaded")
        
        # Default to registry-configured max_output_tokens
        if max_tokens is None:
            max_tokens = self.max_output_tokens
        tokens_to_sample = min(max_tokens, self.max_output_tokens)
        
        if not self.supports_streaming:
            # Fall back to non-streaming.
            result = await self.generate_response(prompt, context, max_tokens)
            yield result
            return
        
        messages: List[Dict[str, str]] = []
        
        # Add system message if context provides one.
        if context and "system_prompt" in context and self.supports_system_prompts:
            messages.append({"role": "system", "content": context["system_prompt"]})
        
        # Add user message.
        messages.append({"role": "user", "content": prompt})
        
        try:
            native_root = self._ollama_native_root()
            if native_root is not None:
                async for text in self._stream_ollama_text(native_root, messages, tokens_to_sample):
                    yield text
                return
            stream = await self._async_client.chat.completions.create(
                model=self.model_identifier,
                messages=messages,
                max_tokens=tokens_to_sample,
                temperature=self.temperature,
                stream=True,
            )
            
            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
                    
        except Exception as e:
            logger.error(f"Error in streaming response: {e}")
            raise
    
    def _ollama_native_root(self) -> Optional[str]:
        if not uses_ollama_native_chat(self.server_type):
            return None
        return ollama_native_root(self.base_url)

    async def _stream_ollama_text(
        self,
        native_root: str,
        messages: List[Dict[str, str]],
        max_tokens: int,
    ) -> AsyncGenerator[str, None]:
        body = build_ollama_chat_body(
            {
                "model": self.model_identifier,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": self.temperature,
            },
            num_ctx=self.max_context_length,
        )
        final_chunk: Dict[str, Any] = {}
        async for chunk in stream_ollama_chat(native_root, body, api_key=self.api_key):
            text = (chunk.get("message") or {}).get("content") or ""
            if text:
                yield text
            if chunk.get("done"):
                final_chunk = chunk
        used_tokens = ollama_context_tokens_used(final_chunk, body["options"].get("num_ctx"), body["options"].get("num_predict"))
        if used_tokens is not None:
            raise OllamaContextWindowFilled(used_tokens, int(body["options"]["num_ctx"]), self.model_identifier)

    def get_metadata(self) -> ModelMetadata:
        """Get model metadata."""
        cfg = get_model(self.model_name) or {}
        return ModelMetadata(
            name=cfg.get("display_name", self.model_name),
            description=cfg.get("description", f"Custom OpenAI-compatible model: {self.model_identifier}"),
            version="custom",
            source="custom",
            capabilities=set(self.required_capabilities),
            parameters={
                "base_url": self.base_url,
                "model_identifier": self.model_identifier,
                "context_window": self.max_context_length,
                "max_output_tokens": self.max_output_tokens,
                "features": cfg.get("features", []),
                "feature_config": cfg.get("feature_config", {}),
            },
            requirements={},
            memory_requirements="N/A",
            context_window=self.max_context_length,
            max_output_tokens=self.max_output_tokens,
        )
    
    async def validate(self) -> bool:
        """Validate that the model is working correctly."""
        return self.state == ModelState.READY and self._async_client is not None
    
    def _generate(self, prompt: str, max_tokens: int = 100) -> str:
        """Synchronous generation."""
        if self._client is None:
            raise RuntimeError("Model not loaded")
        response = self._client.chat.completions.create(
            model=self.model_identifier,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=min(max_tokens, self.max_output_tokens),
            temperature=self.temperature,
        )
        return response.choices[0].message.content or ""
    
    async def _generate_async(self, prompt: str, max_tokens: int = 100) -> str:
        """Asynchronous generation."""
        return await self.generate_response(prompt, max_tokens=max_tokens)