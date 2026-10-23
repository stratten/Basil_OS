"""
Anthropic-Compatible Model - Handler for any Anthropic-compatible API endpoint.

This model supports connecting to:
- AWS Bedrock (Claude via enterprise).
- Corporate proxies that use Anthropic's Messages API format.
- Any endpoint implementing the Anthropic Messages API.

Configuration is sourced from the custom models registry.
"""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, AsyncGenerator

from anthropic import Anthropic, AsyncAnthropic

from ..base_model import ModelMetadata, ModelState
from ..model_types import ModelCapability
from .base_reasoning import BaseReasoningModel
from ..models_registry import get_model
from config.api_keys import get_api_key

logger = logging.getLogger(__name__)


class AnthropicCompatibleModel(BaseReasoningModel):
    """Model handler for Anthropic-compatible API endpoints."""
    
    def __init__(self, model_path: Path, required_capabilities: Set[ModelCapability]):
        """Initialize the Anthropic-compatible model.
        
        Args:
            model_path: Not used for API models, but required by base class.
            required_capabilities: Required model capabilities.
        """
        super().__init__(model_path, required_capabilities)
        self._client: Optional[Anthropic] = None
        self._async_client: Optional[AsyncAnthropic] = None
        
        # These will be populated from registry config.
        self.model_name: str = ""
        self.model_identifier: str = ""  # The model name sent to the API.
        self.base_url: str = ""
        self.api_key: Optional[str] = None
        self.api_key_name: Optional[str] = None
        self.requires_auth: bool = False
        
        # API settings.
        self.temperature: float = 0.7
        
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
        
        # Feature detection from user-defined features.
        features = cfg.get("features", [])
        feature_values = [f.value if hasattr(f, "value") else f for f in features]
        self.supports_streaming = "streaming" in feature_values
        self.supports_system_prompts = "system_prompts" in feature_values
        
        logger.info(f"Loaded config for {self.model_name}: base_url={self.base_url}, "
                   f"model_identifier={self.model_identifier}, context={self.max_context_length}, "
                   f"max_output={self.max_output_tokens}, requires_auth={self.requires_auth}")
    
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
            logger.info(f"Loading Anthropic-compatible model: {self.model_name}")
            
            # Get API key if required.
            self.api_key = self._get_api_key()
            
            if self.requires_auth and not self.api_key:
                raise ValueError(f"API key required for {self.model_name} but not available")
            
            # Validate base_url.
            if not self.base_url:
                raise ValueError(f"No base_url configured for {self.model_name}")
            
            # Initialize clients.
            # For endpoints without auth, use a dummy key (some servers require it).
            api_key_for_client = self.api_key or "not-needed"
            
            self._client = Anthropic(
                api_key=api_key_for_client,
                base_url=self.base_url,
            )
            self._async_client = AsyncAnthropic(
                api_key=api_key_for_client,
                base_url=self.base_url,
            )
            
            logger.info(f"Anthropic-compatible model {self.model_name} initialized: "
                       f"endpoint={self.base_url}, model={self.model_identifier}")
            self.state = ModelState.READY
            
        except Exception as e:
            self.state = ModelState.ERROR
            self._error = f"Failed to load Anthropic-compatible model: {str(e)}"
            logger.error(f"Error loading Anthropic-compatible model: {str(e)}")
            raise
    
    async def unload(self) -> None:
        """Unload the model."""
        self._client = None
        self._async_client = None
        self.state = ModelState.UNLOADED
        logger.info(f"Anthropic-compatible model {self.model_name} unloaded")
    
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
        
        # Build the messages list.
        messages: List[Dict[str, str]] = [{"role": "user", "content": prompt}]
        
        # Prepare API parameters.
        api_params: Dict[str, Any] = {
            "model": self.model_identifier,
            "messages": messages,
            "max_tokens": tokens_to_sample,
            "temperature": self.temperature,
        }
        
        # Add system message if provided and supported.
        if context and "system" in context and self.supports_system_prompts:
            api_params["system"] = context["system"]
        elif context and "system_prompt" in context and self.supports_system_prompts:
            api_params["system"] = context["system_prompt"]
        
        try:
            response = await self._async_client.messages.create(**api_params)
            
            # Extract text from response.
            if response.content and len(response.content) > 0:
                return response.content[0].text
            return ""
            
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
        
        # Build the messages list.
        messages: List[Dict[str, str]] = [{"role": "user", "content": prompt}]
        
        # Prepare API parameters.
        api_params: Dict[str, Any] = {
            "model": self.model_identifier,
            "messages": messages,
            "max_tokens": tokens_to_sample,
            "temperature": self.temperature,
        }
        
        # Add system message if provided and supported.
        if context and "system" in context and self.supports_system_prompts:
            api_params["system"] = context["system"]
        elif context and "system_prompt" in context and self.supports_system_prompts:
            api_params["system"] = context["system_prompt"]
        
        try:
            async with self._async_client.messages.stream(**api_params) as stream:
                async for text in stream.text_stream:
                    yield text
                    
        except Exception as e:
            logger.error(f"Error in streaming response: {e}")
            raise
    
    def get_metadata(self) -> ModelMetadata:
        """Get model metadata."""
        cfg = get_model(self.model_name) or {}
        return ModelMetadata(
            name=cfg.get("display_name", self.model_name),
            description=cfg.get("description", f"Custom Anthropic-compatible model: {self.model_identifier}"),
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
        response = self._client.messages.create(
            model=self.model_identifier,
            max_tokens=min(max_tokens, self.max_output_tokens),
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text if response.content else ""
    
    async def _generate_async(self, prompt: str, max_tokens: int = 100) -> str:
        """Asynchronous generation."""
        return await self.generate_response(prompt, max_tokens=max_tokens)