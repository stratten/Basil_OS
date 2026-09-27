import os
import asyncio
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, AsyncGenerator
import base64

try:
    import google.generativeai as genai
    from google.generativeai.types import GenerateContentResponse
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


class GeminiModel(BaseReasoningModel):
    """Google Gemini model implementation."""
    SHOULD_CHECK_API_KEY = True
    
    def __init__(self, model_path: Path, required_capabilities: Set[ModelCapability]):
        super().__init__(model_path, required_capabilities)
        
        if not GENAI_AVAILABLE:
            raise ImportError("google-generativeai package is not installed. Install it with: pip install google-generativeai")
        
        self._model = None
        
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

    def _build_generation_config(self, max_output_tokens: int) -> Dict[str, Any]:
        """Build Gemini generation config while honoring registry omissions."""
        generation_config = {
            'temperature': self.temperature,
            'top_p': self.top_p,
            'top_k': self.top_k,
            'max_output_tokens': min(max_output_tokens, self.max_output_tokens),
        }
        return apply_request_parameter_omissions(
            generation_config,
            get_omitted_request_parameters(self.model_name),
        )

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
                
                # Configure the API with the key
                genai.configure(api_key=self.api_key)
                
                # Initialize the model
                self._model = genai.GenerativeModel(self.model_name)
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
        # No specific cleanup needed for API clients
        self._model = None
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
                "google-generativeai": ">=0.7.0"
            },
            memory_requirements="API-based (minimal local memory)",
            supports_gpu=False,  # API-based, no GPU required locally
            context_window=self.max_context_length,
            max_output_tokens=self.max_output_tokens
        )

    def _convert_messages_to_gemini(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Convert OpenAI-style messages to Gemini format.
        
        Args:
            messages: List of messages in OpenAI format
            
        Returns:
            List of messages in Gemini format
        """
        gemini_messages = []
        system_message = None
        
        for message in messages:
            role = message.get('role', 'user')
            content = message.get('content', '')
            
            # Handle system messages by storing them separately
            if role == 'system':
                system_message = content
                continue
            
            # Convert role names
            if role == 'assistant':
                role = 'model'
            elif role != 'user':
                role = 'user'  # Default to user for unknown roles
            
            # Handle multimodal content (text + images)
            if isinstance(content, list):
                parts = []
                for item in content:
                    if isinstance(item, dict):
                        if item.get('type') == 'text':
                            parts.append({'text': item.get('text', '')})
                        elif item.get('type') == 'image_url':
                            # Handle base64 encoded images
                            image_url = item.get('image_url', {}).get('url', '')
                            if image_url.startswith('data:image'):
                                # Extract base64 data
                                try:
                                    import base64
                                    import io
                                    from PIL import Image
                                    
                                    # Split the data URL
                                    header, data = image_url.split(',', 1)
                                    image_data = base64.b64decode(data)
                                    image = Image.open(io.BytesIO(image_data))
                                    
                                    parts.append({'inline_data': {
                                        'mime_type': 'image/jpeg',
                                        'data': data
                                    }})
                                except Exception as e:
                                    api_logger.warning(f"Failed to process image: {e}")
                    elif isinstance(item, str):
                        parts.append({'text': item})
                
                gemini_messages.append({
                    'role': role,
                    'parts': parts
                })
            else:
                # Simple text content
                gemini_messages.append({
                    'role': role,
                    'parts': [{'text': content}]
                })
        
        # Prepend system message to first user message if present
        if system_message and gemini_messages:
            for msg in gemini_messages:
                if msg['role'] == 'user':
                    # Prepend system message to first user message
                    first_part = msg['parts'][0]
                    if 'text' in first_part:
                        first_part['text'] = f"{system_message}\n\n{first_part['text']}"
                    break
        
        return gemini_messages

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
            # Handle different input formats
            if isinstance(input_data, str):
                # Simple string prompt
                response = await asyncio.to_thread(
                    self._model.generate_content,
                    input_data,
                    generation_config=self._build_generation_config(self.max_output_tokens)
                )
                return response.text
            
            elif isinstance(input_data, list):
                # List of messages (OpenAI format)
                gemini_messages = self._convert_messages_to_gemini(input_data)
                
                # For multi-turn conversations, we need to use the chat feature
                if len(gemini_messages) > 1:
                    # Create a chat session
                    chat = self._model.start_chat(history=gemini_messages[:-1])
                    last_message = gemini_messages[-1]['parts'][0]['text']
                    
                    response = await asyncio.to_thread(
                        chat.send_message,
                        last_message,
                        generation_config=self._build_generation_config(self.max_output_tokens)
                    )
                else:
                    # Single message
                    content = gemini_messages[0]['parts'][0]['text'] if gemini_messages else ""
                    response = await asyncio.to_thread(
                        self._model.generate_content,
                        content,
                        generation_config=self._build_generation_config(self.max_output_tokens)
                    )
                
                return response.text
            
            else:
                raise ValueError(f"Unsupported input_data type: {type(input_data)}")
                
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
            # Handle different input formats
            if isinstance(input_data, str):
                # Simple string prompt
                response = self._model.generate_content(
                    input_data,
                    generation_config=self._build_generation_config(self.max_output_tokens),
                    stream=True
                )
                
                for chunk in response:
                    if chunk.text:
                        yield chunk.text
            
            elif isinstance(input_data, list):
                # List of messages (OpenAI format)
                gemini_messages = self._convert_messages_to_gemini(input_data)
                
                # For multi-turn conversations
                if len(gemini_messages) > 1:
                    chat = self._model.start_chat(history=gemini_messages[:-1])
                    last_message = gemini_messages[-1]['parts'][0]['text']
                    
                    response = chat.send_message(
                        last_message,
                        generation_config=self._build_generation_config(self.max_output_tokens),
                        stream=True
                    )
                else:
                    # Single message
                    content = gemini_messages[0]['parts'][0]['text'] if gemini_messages else ""
                    response = self._model.generate_content(
                        content,
                        generation_config=self._build_generation_config(self.max_output_tokens),
                        stream=True
                    )
                
                for chunk in response:
                    if chunk.text:
                        yield chunk.text
            
            else:
                raise ValueError(f"Unsupported input_data type: {type(input_data)}")
                
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
        
        try:
            # Configure generation with max_tokens
            generation_config = self._build_generation_config(max_tokens)
            
            # Generate response using asyncio.to_thread for synchronous API
            response = await asyncio.to_thread(
                self._model.generate_content,
                prompt,
                generation_config=generation_config
            )
            
            # Check if response has valid content
            if not response.candidates:
                api_logger.error("Gemini API returned no candidates")
                raise RuntimeError("No response candidates returned by Gemini API")
            
            candidate = response.candidates[0]
            
            # Check finish reason
            finish_reason_names = {
                0: "UNSPECIFIED",
                1: "STOP",
                2: "MAX_TOKENS",
                3: "SAFETY",
                4: "RECITATION",
                5: "OTHER"
            }
            
            finish_reason = candidate.finish_reason
            finish_reason_name = finish_reason_names.get(finish_reason, f"UNKNOWN({finish_reason})")
            
            # If blocked by safety filters
            if finish_reason == 3:  # SAFETY
                safety_ratings = []
                if hasattr(candidate, 'safety_ratings'):
                    for rating in candidate.safety_ratings:
                        safety_ratings.append(f"{rating.category.name}: {rating.probability.name}")
                
                api_logger.warning(f"Content blocked by Gemini safety filters: {', '.join(safety_ratings)}")
                raise RuntimeError(f"Content was blocked by Gemini safety filters. Ratings: {', '.join(safety_ratings)}")
            
            # If blocked by recitation/copyright
            if finish_reason == 4:  # RECITATION
                api_logger.warning("Content blocked by Gemini recitation filters")
                raise RuntimeError("Content was blocked by Gemini for potential copyright/recitation issues")
            
            # If stopped due to max tokens
            if finish_reason == 2:  # MAX_TOKENS
                api_logger.warning(f"Response truncated due to max tokens ({max_tokens})")
                # Check if there's any partial content
                if candidate.content and candidate.content.parts:
                    try:
                        partial_text = response.text
                        api_logger.info(f"Returning partial response ({len(partial_text)} chars) due to max tokens")
                        return partial_text
                    except:
                        pass
                # No partial content available
                raise RuntimeError(f"Response was truncated at max tokens ({max_tokens}) with no content generated. Try increasing max_tokens or shortening your prompt.")
            
            # Normal completion or other reasons
            if not candidate.content or not candidate.content.parts:
                api_logger.error(f"No content parts in response. Finish reason: {finish_reason_name}")
                raise RuntimeError(f"No valid content returned. Finish reason: {finish_reason_name}")
            
            return response.text
            
        except RuntimeError:
            # Re-raise RuntimeError (our custom errors)
            raise
        except Exception as e:
            api_logger.error(f"Error generating Gemini response: {str(e)}")
            raise RuntimeError(f"Failed to generate response: {e}")

