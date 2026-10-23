import asyncio
import base64
import binascii
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional, Set, Tuple

try:
    from google import genai
    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False
    genai = None

from ..base_model import ModelMetadata, ModelState
from ..model_types import ModelCapability
from config.api_keys import get_api_key
from api.core.logging.api_logger import api_logger
from .base_reasoning import BaseReasoningModel


from ..models_registry import (
    ModelFeature,
    apply_request_parameter_omissions,
    get_model,
    get_omitted_request_parameters,
    has_feature,
)


_STREAM_END = object()

_SAFETY_FINISH_REASONS = {"SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST", "SPII", "IMAGE_SAFETY"}


class GeminiModel(BaseReasoningModel):
    """Google Gemini model implementation."""
    SHOULD_CHECK_API_KEY = True
    
    def __init__(self, model_path: Path, required_capabilities: Set[ModelCapability]):
        super().__init__(model_path, required_capabilities)
        
        if not GENAI_AVAILABLE:
            raise ImportError("google-genai package is not installed. Install it with: pip install google-genai")
        
        self._client = None
        
        # Default to Gemini 3.1 Pro Preview
        self.model_name = "gemini-3.1-pro-preview"
        
        # API settings
        self.api_key = None
        self.temperature = 0.7
        self.top_p = 0.9
        self.top_k = 40
        
        # Set context window based on model
        self.max_context_length = self._get_context_window()
        
        # Set max output tokens based on model
        self.max_output_tokens = self._get_max_output_tokens()
        
        # Vision capability
        self.vision_enabled = self._supports_vision()

    def _get_context_window(self) -> int:
        """Get the context window size for the current model."""
        cfg = get_model(self.model_name)
        if cfg and "context_window" in cfg:
            return cfg["context_window"]
        # Default to 1M tokens for Gemini models
        return 1000000
        
    def _get_max_output_tokens(self) -> int:
        """Get the maximum output tokens for the current model."""
        cfg = get_model(self.model_name)
        if cfg and "max_output_tokens" in cfg:
            return cfg["max_output_tokens"]
        # Default to 8192 if model not found
        return 8192
        
    def _supports_vision(self) -> bool:
        """Check if the current model supports vision."""
        cfg = get_model(self.model_name)
        if cfg:
            caps = cfg.get("capabilities", [])
            return "vision" in [c.lower() if isinstance(c, str) else c for c in caps]
        # Default: all Gemini models support vision
        return True
        
    def _supports_extended_thinking(self) -> bool:
        """Check if the current model supports extended thinking (Deep Think Mode)."""
        return has_feature(self.model_name, ModelFeature.EXTENDED_THINKING)

    def _get_thinking_level(self) -> Optional[str]:
        """Return the registry default thinking level when the model exposes discrete levels."""
        cfg = get_model(self.model_name) or {}
        thinking = cfg.get("feature_config", {}).get("thinking")
        if not isinstance(thinking, dict):
            return None
        levels = thinking.get("levels")
        default = thinking.get("default")
        if isinstance(levels, list) and isinstance(default, str) and default in levels:
            return default
        return None

    def _build_generation_config(self, max_output_tokens: int, **overrides: Any) -> Dict[str, Any]:
        """Build a google-genai GenerateContentConfig dict while honoring registry omissions."""
        generation_config: Dict[str, Any] = {
            'temperature': self.temperature,
            'top_p': self.top_p,
            'top_k': self.top_k,
            'max_output_tokens': min(max_output_tokens, self.max_output_tokens),
        }
        generation_config = apply_request_parameter_omissions(
            generation_config,
            get_omitted_request_parameters(self.model_name),
        )
        thinking_level = self._get_thinking_level()
        if thinking_level:
            generation_config['thinking_config'] = {'thinking_level': thinking_level}
        # Basil never passes Python callables as tools, so automatic function calling only adds SDK log noise.
        generation_config['automatic_function_calling'] = {'disable': True}
        generation_config.update(overrides)
        return generation_config

    async def load(self) -> None:
        """Load the Gemini model by initializing the API client."""
        try:
            self.state = ModelState.LOADING
            api_logger.info(f"Loading Gemini model: {self.model_name}")
            
            if GeminiModel.SHOULD_CHECK_API_KEY:
                # Get API key from key manager (try both 'google' and 'gemini')
                try:
                    self.api_key = get_api_key("google")
                    api_logger.info("Loaded Google API key from key manager")
                except ValueError:
                    try:
                        self.api_key = get_api_key("gemini")
                        api_logger.info("Loaded Gemini API key from key manager")
                    except ValueError:
                        api_logger.error("No Google/Gemini API key available")
                        raise ValueError("No Google/Gemini API key available. Please set an API key in the application settings.")
                
                self._client = genai.Client(api_key=self.api_key)
            else:
                api_logger.info("API key check is disabled for GeminiModel. Skipping API key loading.")

            # Update context window size based on selected model
            self.max_context_length = self._get_context_window()
            
            # Update max output tokens
            self.max_output_tokens = self._get_max_output_tokens()
            
            # Check if model supports vision
            self.vision_enabled = self._supports_vision()
            
            # Log successful initialization
            cfg = get_model(self.model_name) or {}
            model_display_name = cfg.get("display_name", self.model_name)
            api_logger.info(f"Gemini model {model_display_name} initialized successfully")
            
            if self._supports_extended_thinking():
                api_logger.info(f"Extended thinking (Deep Think Mode) available for {model_display_name}")
            
            self.state = ModelState.READY
            
        except Exception as e:
            self.state = ModelState.ERROR
            self._error = f"Failed to load Gemini model: {str(e)}"
            api_logger.error(f"Error loading Gemini model: {str(e)}")

    async def unload(self) -> None:
        """Unload the Gemini model."""
        client = self._client
        self._client = None
        if client is not None:
            try:
                client.close()
            except Exception as e:
                api_logger.warning(f"Error closing Gemini client: {e}")
        self.state = ModelState.UNLOADED
        api_logger.info("Gemini model unloaded successfully")

    def get_metadata(self) -> ModelMetadata:
        """Get model metadata."""
        # Get the display name for the model from registry
        cfg = get_model(self.model_name) or {}
        display_name = cfg.get("display_name", self.model_name)
        description = cfg.get("description", "Cloud-based Google Gemini model for reasoning tasks")
        
        # Build parameters dictionary
        parameters = {
            "model": self.model_name,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "top_k": self.top_k,
            "max_output_tokens": self.max_output_tokens,
            "context_window": self.max_context_length,
            "vision_enabled": self.vision_enabled
        }
        
        # Determine capabilities
        capabilities = {ModelCapability.REASONING}
        if self.vision_enabled:
            capabilities.add(ModelCapability.VISION)
        
        return ModelMetadata(
            name=f"Gemini ({display_name})",
            version="1.0",
            source="gemini",
            capabilities=capabilities,
            description=description,
            parameters=parameters,
            requirements={
                "google-genai": ">=2.25.0"
            },
            memory_requirements="API-based (minimal local memory)",
            supports_gpu=False,  # API-based, no GPU required locally
            context_window=self.max_context_length,
            max_output_tokens=self.max_output_tokens
        )

    @staticmethod
    def _data_url_to_part(url: str) -> Optional[Dict[str, Any]]:
        """Convert a base64 data URL into a Gemini inline_data part."""
        if not url.startswith('data:') or ',' not in url:
            api_logger.warning("Skipping non-inline attachment for Gemini; only base64 data URLs are supported")
            return None
        header, data = url.split(',', 1)
        if ';base64' not in header:
            api_logger.warning("Skipping non-base64 data URL for Gemini")
            return None
        mime_type = header[len('data:'):].split(';', 1)[0] or 'application/octet-stream'
        try:
            raw = base64.b64decode(data, validate=True)
        except (binascii.Error, ValueError) as e:
            api_logger.warning(f"Failed to decode inline data for Gemini: {e}")
            return None
        return {'inline_data': {'mime_type': mime_type, 'data': raw}}

    def _convert_content_to_parts(self, content: Any) -> List[Dict[str, Any]]:
        """Convert one OpenAI-style message content value into Gemini parts."""
        if isinstance(content, str):
            return [{'text': content}]
        if not isinstance(content, list):
            return [] if content is None else [{'text': str(content)}]
        parts: List[Dict[str, Any]] = []
        for item in content:
            if isinstance(item, str):
                parts.append({'text': item})
            elif isinstance(item, dict):
                if item.get('type') == 'text':
                    parts.append({'text': item.get('text', '')})
                elif item.get('type') == 'image_url':
                    part = self._data_url_to_part(item.get('image_url', {}).get('url', ''))
                    if part is not None:
                        parts.append(part)
        return parts

    def _convert_messages_to_gemini(
        self, messages: List[Dict[str, Any]]
    ) -> Tuple[Optional[str], List[Dict[str, Any]]]:
        """Convert OpenAI-style messages to a Gemini system instruction and contents list."""
        contents: List[Dict[str, Any]] = []
        system_texts: List[str] = []
        
        for message in messages:
            role = message.get('role', 'user')
            content = message.get('content', '')
            
            if role == 'system':
                for part in self._convert_content_to_parts(content):
                    text = part.get('text')
                    if text:
                        system_texts.append(text)
                continue
            
            parts = self._convert_content_to_parts(content)
            if not parts:
                continue
            contents.append({
                'role': 'model' if role == 'assistant' else 'user',
                'parts': parts,
            })
        
        system_instruction = "\n\n".join(system_texts) if system_texts else None
        return system_instruction, contents

    def _prepare_request(self, input_data: Any, max_output_tokens: int) -> Tuple[Any, Dict[str, Any]]:
        """Return (contents, config) for a string prompt or an OpenAI-style message list."""
        if isinstance(input_data, str):
            return input_data, self._build_generation_config(max_output_tokens)
        if isinstance(input_data, list):
            system_instruction, contents = self._convert_messages_to_gemini(input_data)
            if not contents:
                raise ValueError("No user or assistant content to send to Gemini")
            overrides = {'system_instruction': system_instruction} if system_instruction else {}
            return contents, self._build_generation_config(max_output_tokens, **overrides)
        raise ValueError(f"Unsupported input_data type: {type(input_data)}")

    @staticmethod
    def _finish_reason_name(candidate: Any) -> str:
        raw = getattr(candidate, 'finish_reason', None)
        if raw is None:
            return "UNSPECIFIED"
        return str(getattr(raw, 'name', None) or raw)

    @staticmethod
    def _text_from_candidate(candidate: Any) -> str:
        """Join the non-thought text parts of a candidate."""
        content = getattr(candidate, 'content', None)
        parts = getattr(content, 'parts', None) or []
        return "".join(
            part.text
            for part in parts
            if getattr(part, 'text', None) and not getattr(part, 'thought', False)
        )

    def _extract_response_text(self, response: Any, max_tokens: int) -> str:
        """Return the response text or raise a descriptive RuntimeError for blocked/empty output."""
        candidates = getattr(response, 'candidates', None) or []
        if not candidates:
            feedback = getattr(response, 'prompt_feedback', None)
            block_reason = getattr(feedback, 'block_reason', None)
            if block_reason:
                reason = getattr(block_reason, 'name', None) or str(block_reason)
                api_logger.warning(f"Prompt blocked by Gemini: {reason}")
                raise RuntimeError(f"Prompt was blocked by Gemini: {reason}")
            api_logger.error("Gemini API returned no candidates")
            raise RuntimeError("No response candidates returned by Gemini API")
        
        candidate = candidates[0]
        finish_reason = self._finish_reason_name(candidate)
        text = self._text_from_candidate(candidate)
        
        if finish_reason in _SAFETY_FINISH_REASONS:
            safety_ratings = []
            for rating in getattr(candidate, 'safety_ratings', None) or []:
                category = getattr(rating.category, 'name', rating.category)
                probability = getattr(rating.probability, 'name', rating.probability)
                safety_ratings.append(f"{category}: {probability}")
            api_logger.warning(f"Content blocked by Gemini safety filters: {', '.join(safety_ratings)}")
            raise RuntimeError(f"Content was blocked by Gemini safety filters. Ratings: {', '.join(safety_ratings)}")
        
        if finish_reason == "RECITATION":
            api_logger.warning("Content blocked by Gemini recitation filters")
            raise RuntimeError("Content was blocked by Gemini for potential copyright/recitation issues")
        
        if finish_reason == "MAX_TOKENS":
            api_logger.warning(f"Response truncated due to max tokens ({max_tokens})")
            if text:
                api_logger.info(f"Returning partial response ({len(text)} chars) due to max tokens")
                return text
            raise RuntimeError(f"Response was truncated at max tokens ({max_tokens}) with no content generated. Try increasing max_tokens or shortening your prompt.")
        
        if not text:
            api_logger.error(f"No content parts in response. Finish reason: {finish_reason}")
            raise RuntimeError(f"No valid content returned. Finish reason: {finish_reason}")
        
        return text

    async def predict(self, input_data: Any) -> Any:
        """Run inference on the Gemini model.
        
        Args:
            input_data: Can be a string prompt or a list of messages in OpenAI format
            
        Returns:
            The model's response
        """
        if not self.is_loaded:
            raise RuntimeError("Model must be loaded before prediction")
        
        try:
            contents, config = self._prepare_request(input_data, self.max_output_tokens)
            response = await asyncio.to_thread(
                self._client.models.generate_content,
                model=self.model_name,
                contents=contents,
                config=config,
            )
            return self._extract_response_text(response, self.max_output_tokens)
        except Exception as e:
            api_logger.error(f"Error during Gemini prediction: {str(e)}")
            raise

    async def stream_predict(self, input_data: Any) -> AsyncGenerator[str, None]:
        """Stream predictions from the Gemini model.
        
        Args:
            input_data: Can be a string prompt or a list of messages in OpenAI format
            
        Yields:
            Chunks of the model's response
        """
        if not self.is_loaded:
            raise RuntimeError("Model must be loaded before prediction")
        
        try:
            contents, config = self._prepare_request(input_data, self.max_output_tokens)
            stream = await asyncio.to_thread(
                self._client.models.generate_content_stream,
                model=self.model_name,
                contents=contents,
                config=config,
            )
            while True:
                chunk = await asyncio.to_thread(next, stream, _STREAM_END)
                if chunk is _STREAM_END:
                    break
                candidates = getattr(chunk, 'candidates', None) or []
                if not candidates:
                    continue
                text = self._text_from_candidate(candidates[0])
                if text:
                    yield text
        except Exception as e:
            api_logger.error(f"Error during Gemini streaming: {str(e)}")
            raise

    async def validate(self) -> bool:
        """Validate that the model is working correctly."""
        try:
            if not self.is_loaded:
                return False
            
            # Simple test prompt
            test_response = await self.predict("Hi")
            return test_response is not None and len(test_response) > 0
            
        except Exception as e:
            api_logger.error(f"Model validation failed: {str(e)}")
            return False

    def _generate(self, prompt: str, max_tokens: int) -> str:
        """Synchronous generation - not implemented for Gemini (API-based)."""
        raise NotImplementedError("Synchronous generation not supported for Gemini models. Use async methods instead.")

    async def _generate_async(self, prompt: str, max_tokens: int) -> str:
        """Simple wrapper around generate_response for async generation."""
        return await self.generate_response(prompt, max_tokens=max_tokens)

    async def generate_response(
        self,
        prompt: str,
        context: Dict[str, Any] = None,
        max_tokens: Optional[int] = None,
        preserve_thinking: bool = False
    ) -> str:
        """Generate a response using the Gemini API.
        
        Args:
            prompt: The prompt to generate from
            context: Optional context dictionary
            max_tokens: Maximum number of tokens to generate
            preserve_thinking: Unused for Gemini (API models don't use <think> tags)
        """
        if not self.is_loaded:
            raise RuntimeError("Model is not loaded")
        
        # Use model's max_output_tokens when not specified
        if max_tokens is None:
            max_tokens = self.max_output_tokens
        
        system_prompt = (context or {}).get("system_prompt")
        overrides = {'system_instruction': system_prompt} if system_prompt else {}
        try:
            response = await asyncio.to_thread(
                self._client.models.generate_content,
                model=self.model_name,
                contents=prompt,
                config=self._build_generation_config(max_tokens, **overrides),
            )
            return self._extract_response_text(response, max_tokens)
            
        except RuntimeError:
            # Re-raise RuntimeError (our custom errors)
            raise
        except Exception as e:
            api_logger.error(f"Error generating Gemini response: {str(e)}")
            raise RuntimeError(f"Failed to generate response: {e}")
