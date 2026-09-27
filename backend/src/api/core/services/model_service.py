"""Model service for managing AI models."""

from pathlib import Path
from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Type
from functools import lru_cache

from ..models.model_manager import ModelManager
from ..models.model_downloader import ModelDownloader
from ..models.model_types import ModelCapability
from ..models.base_model import BaseAIModel, ModelState
from ..models.reasoning.llama_model import LlamaModel
from ..models.reasoning.phi_model import PhiModel
from ..models.reasoning.phi2_model import Phi2Model
from ..models.reasoning.solar_model import SolarModel
from ..models.reasoning.mistral_model import MistralModel
from ..models.reasoning.deepseek_model import DeepSeekModel
from ..models.reasoning.qwen_model import QwenModel
from ..models.reasoning.claude_model import ClaudeModel
from ..models.reasoning.openai_model import OpenAIModel
from ..models.reasoning.gemini_model import GeminiModel
from ..models.reasoning.auth_proxy_model import AuthProxyModel
from ..models.reasoning.openai_compatible_model import OpenAICompatibleModel
from ..models.reasoning.anthropic_compatible_model import AnthropicCompatibleModel
from ..logging.api_logger import api_logger
from ...settings import get_models_dir
from ..models.reasoning.llama_cpp_model import LlamaCppModel
from ...services.auth_service_client import should_route_through_auth_service
from ..models.models_registry import ModelHandler


# =============================================================================
# HANDLER CLASS MAPPING - Maps ModelHandler enum to model implementation classes.
# =============================================================================

HANDLER_CLASS_MAP: Dict[ModelHandler, Type[BaseAIModel]] = {
    # Local handlers.
    ModelHandler.LLAMA_CPP: LlamaCppModel,
    ModelHandler.HUGGINGFACE: QwenModel,  # HuggingFace transformers models use QwenModel.
    # ModelHandler.WHISPER: Handled separately in transcription/model_lifecycle.py.

    # Cloud API handlers.
    ModelHandler.OPENAI_API: OpenAIModel,
    ModelHandler.ANTHROPIC_API: ClaudeModel,
    ModelHandler.GEMINI_API: GeminiModel,
    ModelHandler.OPENROUTER: AuthProxyModel,

    # User-configurable handlers for custom models.
    ModelHandler.OPENAI_COMPATIBLE: OpenAICompatibleModel,
    ModelHandler.ANTHROPIC_COMPATIBLE: AnthropicCompatibleModel,
}


def get_handler_class(handler: ModelHandler) -> Type[BaseAIModel]:
    """
    Get the model implementation class for a given handler.

    Args:
        handler: The ModelHandler enum value.

    Returns:
        The model class that handles this handler type.

    Raises:
        ValueError: If the handler is not yet implemented in HANDLER_CLASS_MAP.
    """
    if handler not in HANDLER_CLASS_MAP:
        raise ValueError(
            f"Unknown or unimplemented handler: {handler}. "
            f"Available handlers: {list(HANDLER_CLASS_MAP.keys())}"
        )
    return HANDLER_CLASS_MAP[handler]

# In-memory storage for access token (set by Swift client via API)
_auth_access_token: Optional[str] = None

# Pending token requests (for WebSocket request/response pattern)
import asyncio
import uuid
_pending_token_requests: Dict[str, asyncio.Future] = {}
AUTH_TOKEN_REQUEST_TIMEOUT_SECONDS = 180.0


@dataclass(frozen=True)
class BasilCloudCredentials:
    """Credential state for Basil Cloud trial-first routing."""
    access_token: Optional[str]
    trial_key: Optional[str]
    label: str
    setup_agent_key: Optional[str] = None

    @property
    def has_credentials(self) -> bool:
        return (
            self.access_token is not None
            or self.trial_key is not None
            or self.setup_agent_key is not None
        )


def set_auth_access_token(token: str) -> None:
    """Set the access token for auth service routing.
    
    Called by Swift client when user authenticates.
    """
    global _auth_access_token
    _auth_access_token = token
    api_logger.info("🔐 Auth access token set for session")


def get_auth_access_token() -> Optional[str]:
    """Get the current access token."""
    return _auth_access_token


def clear_auth_access_token() -> None:
    """Clear the access token (on logout)."""
    global _auth_access_token
    _auth_access_token = None
    api_logger.info("🔐 Auth access token cleared")


# In-memory storage for trial key (set by Swift client via API)
_trial_key: Optional[str] = None


def set_trial_key(key: str) -> None:
    """Set the trial key for unauthenticated API routing.
    
    Called by Swift client on app startup for non-authenticated users.
    """
    global _trial_key
    _trial_key = key
    api_logger.info("🎫 Trial key set for session")


def get_trial_key() -> Optional[str]:
    """Get the current trial key."""
    return _trial_key


def clear_trial_key() -> None:
    """Clear the trial key."""
    global _trial_key
    _trial_key = None
    api_logger.info("🎫 Trial key cleared")


async def request_auth_token_from_swift() -> Optional[str]:
    """Request the auth token from Swift client via WebSocket.
    
    This is used when the backend needs the token but it hasn't been synced yet.
    Swift will respond with the current access token from its keychain.
    
    Returns:
        The access token, or None if request failed/timed out.
    """
    try:
        # Import WebSocket connections
        from api.services.websocket_connection_manager import active_connections
        
        if not active_connections:
            api_logger.warning("🔐 No WebSocket connections - cannot request auth token from Swift")
            return None
        
        # Generate unique request ID
        request_id = str(uuid.uuid4())
        
        # Create a future to wait for the response
        response_future: asyncio.Future = asyncio.Future()
        _pending_token_requests[request_id] = response_future
        
        # Send token request to Swift
        token_request = {
            "event_type": "auth_token_request",
            "request_id": request_id,
            "message": "Backend requires auth token for LLM request"
        }
        
        api_logger.info(f"🔐 Requesting auth token from Swift via WebSocket: {request_id}")
        
        successful_sends = 0
        for connection in active_connections:
            try:
                await connection.send_json(token_request)
                successful_sends += 1
            except Exception as e:
                api_logger.error(f"🔐 Failed to send token request: {e}")
        
        if successful_sends == 0:
            _pending_token_requests.pop(request_id, None)
            api_logger.error("🔐 Failed to send token request to any WebSocket connections")
            return None
        
        # Wait long enough for macOS Keychain prompts or manual auth approval.
        try:
            token = await asyncio.wait_for(
                response_future,
                timeout=AUTH_TOKEN_REQUEST_TIMEOUT_SECONDS,
            )
            _pending_token_requests.pop(request_id, None)
            
            if token:
                # Store the token for future use
                set_auth_access_token(token)
                api_logger.info(f"🔐 Received auth token from Swift")
                return token
            else:
                api_logger.warning("🔐 Swift returned empty token")
                return None
                
        except asyncio.TimeoutError:
            _pending_token_requests.pop(request_id, None)
            api_logger.warning(
                f"🔐 Token request timed out after {AUTH_TOKEN_REQUEST_TIMEOUT_SECONDS:.0f} seconds"
            )
            return None
            
    except Exception as e:
        api_logger.error(f"🔐 Error requesting auth token from Swift: {e}")
        return None


def resolve_pending_token_request(request_id: str, token: Optional[str]) -> bool:
    """Resolve a pending token request with the received token.
    
    Called when Swift sends the auth_token_response via WebSocket.
    
    Args:
        request_id: The request ID from the original request
        token: The access token from Swift
        
    Returns:
        True if the request was found and resolved, False otherwise.
    """
    future = _pending_token_requests.get(request_id)
    if future and not future.done():
        future.set_result(token)
        return True
    return False


async def resolve_basil_cloud_credentials(context_label: str = "Basil Cloud") -> BasilCloudCredentials:
    """Resolve trial and account credentials for Basil Cloud routes."""
    from ..models.preferences import Preferences, APIKeyPreference

    try:
        pref = Preferences.load()
        api_key_preference = pref.auth.api_key_preference
    except Exception as e:
        api_logger.warning(f"Failed to check API key preference: {e}")
        api_key_preference = APIKeyPreference.BASIL_CLOUD

    if api_key_preference not in {
        APIKeyPreference.BASIL_CLOUD,
        APIKeyPreference.TRIAL,
        APIKeyPreference.APP_KEYS,
    }:
        raise RuntimeError(
            f"Auth routing was requested for unsupported API key preference: {api_key_preference}"
        )

    trial_key = get_trial_key()
    access_token = get_auth_access_token()

    if access_token is None:
        api_logger.info(f"🔐 No account token cached, requesting from Swift for {context_label}")
        access_token = await request_auth_token_from_swift()

    if trial_key is None and access_token is None:
        api_logger.error(f"🚫 Basil Cloud selected but no usable credentials for {context_label}")
        raise RuntimeError(
            "Basil Cloud is selected, but no included-credit key or account token is available. "
            "Please restart the app, sign in, or choose another model access option."
        )

    label = "basil_cloud_trial_first" if trial_key else "basil_cloud_account"
    return BasilCloudCredentials(
        access_token=access_token,
        trial_key=trial_key,
        label=label,
    )


class ModelNotFoundError(Exception):
    """Raised when attempting to use a model that isn't downloaded."""
    pass


class ModelService:
    """Service for managing AI models."""

    def __init__(self, models_dir: str | Path) -> None:
        """Initialize model service.
        
        Args:
            models_dir: Directory for storing models
        """
        self.models_dir = Path(models_dir)
        self.model_manager = ModelManager(self.models_dir)
        self.model_downloader = ModelDownloader(self.models_dir)
        self._active_models: Dict[str, BaseAIModel] = {}

    def initialize(self) -> None:
        """Initialize the model service."""
        api_logger.info("🔧 Starting model service initialization...")
        
        # Register local model classes
        api_logger.info("🔧 Registering local model classes...")
        self.model_manager.register_model_class("llama", LlamaCppModel)  # For GGUF models via llama.cpp
        self.model_manager.register_model_class("Llama", LlamaCppModel)  # For GGUF Llama models
        self.model_manager.register_model_class("phi2", Phi2Model)  # Using Phi2Model for Phi-2 GGUF
        self.model_manager.register_model_class("phi35-mini", PhiModel)  # Using PhiModel for Phi-3.5
        self.model_manager.register_model_class("Phi", PhiModel)  # Alternative registration for Phi models
        self.model_manager.register_model_class("solar", SolarModel)  # Using SolarModel for SOLAR
        self.model_manager.register_model_class("Solar", SolarModel)  # Alternative registration for SOLAR
        self.model_manager.register_model_class("mistral-7b-v03", MistralModel)  # Using MistralModel for Mistral 7B v0.3
        self.model_manager.register_model_class("deepseek-r1-qwen-7b", DeepSeekModel)  # Using DeepSeekModel for DeepSeek-R1-Distill-Qwen-7B
        self.model_manager.register_model_class("DeepSeek", DeepSeekModel)  # Alternative registration for DeepSeek
        
        # Register Qwen models - CRITICAL FOR FIXING THE BUG
        api_logger.info("🔧 Registering Qwen model classes...")
        self.model_manager.register_model_class("Qwen", QwenModel)  # Using QwenModel for Qwen models (provider name)
        self.model_manager.register_model_class("qwen3-4b", QwenModel)  # Backward compatibility for qwen3-4b variant
        
        # Register API-based model classes
        api_logger.info("🔧 Registering API model classes...")
        self.model_manager.register_model_class("claude", ClaudeModel)  # Using ClaudeModel for Anthropic Claude models
        self.model_manager.register_model_class("openai", OpenAIModel)  # Using OpenAIModel for OpenAI GPT models
        self.model_manager.register_model_class("gemini", GeminiModel)  # Using GeminiModel for Google Gemini models
        
        # Log all registered model classes for debugging
        api_logger.info(f"🔧 Model service initialization complete. Registered model types: {list(self.model_manager._model_classes.keys())}")
        api_logger.info("Model service initialized with local and API-based models")

    def is_model_downloaded(self, model_type: str, variant: str) -> bool:
        """Check if a model is downloaded."""
        # API models don't need to be downloaded
        if model_type in ["openai", "claude", "gemini"]:
            return True
            
        installed_models = self.model_downloader.get_installed_models()
        return (
            model_type in installed_models and
            variant in installed_models[model_type]["variants"]
        )

    async def get_model_status(self, model_type: str, variant: str) -> Dict:
        """Get detailed status of a specific model."""
        model_id = f"{model_type}-{variant}"
        
        # API models are always "downloaded"
        if model_type in ["openai", "claude", "gemini"]:
            is_downloaded = True
            api_logger.info(f"Checking status of API model: {model_id}")
        else:
            is_downloaded = self.is_model_downloaded(model_type, variant)
            
        is_loaded = model_id in self._active_models
        
        status = {
            "downloaded": is_downloaded,
            "loaded": is_loaded,
            "state": "not_available"
        }

        if is_loaded:
            model = self._active_models[model_id]
            status["state"] = model.state.value
            if model.error:
                status["error"] = model.error

        return status

    def touch_model(self, model_type: str, variant: str) -> None:
        """Update last-used timestamp for a model to reset its idle timer."""
        model_id = f"{model_type}-{variant}"
        self.model_manager.touch_model(model_id)
    
    async def load_model(
        self,
        model_type: str,
        variant: str,
        capabilities: Set[ModelCapability],
        registry_model_id: Optional[str] = None,
    ) -> BaseAIModel:
        """Load a downloaded model into memory and reset idle timer."""
        # Special handling for API-based models which don't need to be downloaded
        if model_type in ["openai", "claude", "gemini"]:
            api_logger.info(f"Loading API model: {model_type}-{variant}")
            model_id = f"{model_type}-{variant}"
            
            # Check if we should route through auth service
            requires_auth_routing = should_route_through_auth_service()
            
            if requires_auth_routing:
                credentials = await resolve_basil_cloud_credentials(model_id)
                access_token_to_use = credentials.access_token
                trial_key_to_use = credentials.trial_key
                auth_type = credentials.label
                
                auth_proxy_model_id = registry_model_id or model_id
                api_logger.info(f"🔐 Auth proxy required for {auth_proxy_model_id} ({auth_type})")
                proxy_model_id = f"auth_proxy-{auth_proxy_model_id}"
                
                # FIRST: Check if proxy model is already loaded and has valid auth
                # The cached model has the token/key embedded from when it was created
                if proxy_model_id in self._active_models:
                    model = self._active_models[proxy_model_id]
                    if model.state == ModelState.READY:
                        if isinstance(model, AuthProxyModel):
                            if access_token_to_use and not model.access_token:
                                model.access_token = access_token_to_use
                            if trial_key_to_use and not model.trial_key:
                                model.trial_key = trial_key_to_use
                        api_logger.info(f"🔐 Returning cached AuthProxyModel for {auth_proxy_model_id}")
                        return model
                    await self.model_manager.unload_model(proxy_model_id)
                    del self._active_models[proxy_model_id]
                
                # Create new AuthProxyModel instance
                api_logger.info(f"🔐 Creating new AuthProxyModel for {auth_proxy_model_id} (token={access_token_to_use is not None}, trial={trial_key_to_use is not None})")
                try:
                    model = AuthProxyModel(
                        model_id=auth_proxy_model_id,
                        access_token=access_token_to_use,
                        trial_key=trial_key_to_use,
                        required_capabilities=capabilities
                    )
                    await model.load()
                    self._active_models[proxy_model_id] = model
                    return model
                except Exception as e:
                    api_logger.error(f"Failed to create AuthProxyModel for {auth_proxy_model_id}: {e}")
                    raise
            
            # Standard direct provider access (own keys or no auth)
            # Check if model is already loaded and ready
            if model_id in self._active_models:
                model = self._active_models[model_id]
                if model.state == ModelState.READY:
                    # Touch the model to reset idle timer (if applicable for API models)
                    self.model_manager.touch_model(model_id)
                    return model
                # If model exists but isn't ready, unload it
                await self.unload_model(model_type, variant)
            
            # Load the API model
            try:
                api_logger.info(f"Creating new instance of API model {model_id}")
                model = await self.model_manager.load_api_model(
                    model_id,
                    model_type,
                    capabilities
                )
                if not model:
                    raise RuntimeError(f"Failed to load API model {model_id}")
                
                self._active_models[model_id] = model
                return model
            except Exception as e:
                api_logger.error(f"Failed to load API model {model_id}: {e}")
                raise

        # For local models, check if they're downloaded
        if not self.is_model_downloaded(model_type, variant):
            raise ModelNotFoundError(
                f"Model {model_type}-{variant} is not downloaded. "
                "Please download the model first."
            )

        model_id = f"{model_type}-{variant}"
        
        # Check if model is already loaded and ready
        if model_id in self._active_models:
            model = self._active_models[model_id]
            if model.state == ModelState.READY:
                # Touch the model to reset idle timer
                self.model_manager.touch_model(model_id)
                return model
            # If model exists but isn't ready, unload it
            await self.unload_model(model_type, variant)

        # Load the model (which also schedules idle unload)
        try:
            model = await self.model_manager.load_model(
                model_id,
                model_type,
                capabilities
            )
            if not model:
                raise RuntimeError(f"Failed to load model {model_id}")
            
            self._active_models[model_id] = model
            return model
        except Exception as e:
            api_logger.error(f"Failed to load model {model_id}: {e}")
            raise

    async def unload_model(self, model_type: str, variant: str) -> bool:
        """Unload a model from memory."""
        model_id = f"{model_type}-{variant}"
        if model_id in self._active_models:
            try:
                await self.model_manager.unload_model(model_id)
                del self._active_models[model_id]
                return True
            except Exception as e:
                api_logger.error(f"Error unloading model {model_id}: {e}")
                return False
        return True

    async def load_model_by_id(
        self,
        model_id: str,
        capabilities: Set[ModelCapability]
    ) -> BaseAIModel:
        """Load any model by its registry ID. Routes to appropriate loader based on handler."""
        from ..models.models_registry import get_model, find_model_by_display_name, ModelHandler

        cfg = get_model(model_id)
        if not cfg and "/" in model_id:
            # Translate the slash-form preference id (e.g. "qwen/qwen3-8b-instruct-q4km")
            # to the registry's canonical dash-form (e.g. "Qwen-qwen3-8b-instruct-q4km").
            # Upstream callers like ModelUsageService accept the slash form because they
            # match against installed_models display data, but get_model() requires the
            # canonical id, so callers that come straight here (e.g. SkillEvaluator via
            # PostTaskEvaluatorOrchestrator) used to fail with "not found in registry".
            provider_slug, _, variant = model_id.partition("/")
            if provider_slug and variant:
                canonical_id = f"{provider_slug.capitalize()}-{variant}"
                canonical_cfg = get_model(canonical_id)
                if canonical_cfg:
                    api_logger.info(
                        f"Resolved slash-form model id '{model_id}' to registry id '{canonical_id}'"
                    )
                    model_id = canonical_id
                    cfg = canonical_cfg

        if not cfg:
            # Self-heal callers/preferences that were persisted with a model's
            # human-readable display_name instead of its canonical registry id
            # (a client-side bug where Settings tabs stored `variant.name`
            # instead of `variant.model_id` when populating model pickers).
            # Without this, an already-saved bad preference value would keep
            # failing here even after the client-side bug is fixed, since the
            # bad value is already on disk and won't be re-picked until the
            # user manually reselects it in Settings.
            match = find_model_by_display_name(model_id)
            if match:
                candidate_id, candidate_cfg = match
                api_logger.warning(
                    f"Model id '{model_id}' not found in registry, but matched "
                    f"display_name of '{candidate_id}' - resolving by display_name. "
                    f"This usually means a stale preference was saved with a "
                    f"display name instead of a canonical model id."
                )
                model_id = candidate_id
                cfg = candidate_cfg

        if not cfg:
            raise ValueError(f"Model '{model_id}' not found in registry")

        handler = cfg.get("handler")
        provider = cfg.get("provider")
        api_logger.info(f"Loading model '{model_id}' via handler '{handler}'")
        
        # Route to appropriate loader based on handler
        # Strip provider prefix from model_id since load_model will add it back
        if handler in (ModelHandler.OPENAI_API.value, ModelHandler.OPENAI_API):
            variant = model_id[7:] if model_id.startswith("openai-") else model_id
            return await self.load_model("openai", variant, capabilities, registry_model_id=model_id)
        elif handler in (ModelHandler.ANTHROPIC_API.value, ModelHandler.ANTHROPIC_API):
            variant = model_id[7:] if model_id.startswith("claude-") else model_id
            return await self.load_model("claude", variant, capabilities, registry_model_id=model_id)
        elif handler in (ModelHandler.GEMINI_API.value, ModelHandler.GEMINI_API):
            variant = model_id[7:] if model_id.startswith("gemini-") else model_id
            return await self.load_model("gemini", variant, capabilities, registry_model_id=model_id)
        elif handler in (ModelHandler.LLAMA_CPP.value, ModelHandler.LLAMA_CPP):
            # Local model - split model_id into provider/variant
            parts = model_id.split("-", 1) if "-" in model_id else (model_id, model_id)
            return await self.load_model(parts[0], parts[1], capabilities)
        elif handler in (ModelHandler.LLAMA_CPP_VISION.value, ModelHandler.LLAMA_CPP_VISION):
            if model_id in self._active_models:
                model = self._active_models[model_id]
                if model.is_loaded:
                    return model
            from api.services.agent_processing.tools.vision.local_qwen_vl_loader import (
                load_local_qwen25_vl_wrapper,
            )

            model, error = load_local_qwen25_vl_wrapper(
                self.models_dir,
                model_id,
                required_capabilities=capabilities,
            )
            if model is None or error:
                raise RuntimeError(error or f"Failed to load vision model '{model_id}'")
            self._active_models[model_id] = model
            return model
        elif handler in (ModelHandler.OPENAI_COMPATIBLE.value, ModelHandler.OPENAI_COMPATIBLE,
                        ModelHandler.ANTHROPIC_COMPATIBLE.value, ModelHandler.ANTHROPIC_COMPATIBLE):
            return await self.load_custom_model(model_id, capabilities)
        else:
            raise ValueError(f"Unknown handler '{handler}' for model '{model_id}'")

    async def load_custom_model(
        self,
        model_id: str,
        capabilities: Set[ModelCapability]
    ) -> BaseAIModel:
        """Load a user-defined custom model by its registry ID.
        
        Args:
            model_id: The custom model ID from the custom models registry.
            capabilities: Required model capabilities.
            
        Returns:
            The loaded model instance.
            
        Raises:
            ValueError: If the model is not found in the custom models registry.
            RuntimeError: If the model fails to load.
        """
        from ..models.models_registry import get_custom_models, ModelHandler
        
        api_logger.info(f"Loading custom model: {model_id}")
        
        # Check if already loaded.
        if model_id in self._active_models:
            model = self._active_models[model_id]
            if model.state == ModelState.READY:
                api_logger.info(f"Returning cached custom model: {model_id}")
                return model
        
        # Look up the model config from registry.
        custom_models = get_custom_models()
        if model_id not in custom_models:
            raise ValueError(f"Custom model '{model_id}' not found in registry")
        
        cfg = custom_models[model_id]
        handler_str = cfg.get("handler", "")
        
        # Determine which handler class to use.
        if handler_str == ModelHandler.OPENAI_COMPATIBLE.value:
            handler_class = OpenAICompatibleModel
        elif handler_str == ModelHandler.ANTHROPIC_COMPATIBLE.value:
            handler_class = AnthropicCompatibleModel
        elif handler_str == ModelHandler.LLAMA_CPP.value:
            handler_class = LlamaCppModel
        else:
            raise ValueError(f"Unknown handler type for custom model: {handler_str}")
        
        api_logger.info(f"Instantiating custom model with handler: {handler_str}")
        
        try:
            # Handle local models (llama_cpp) differently from API models.
            if handler_str == ModelHandler.LLAMA_CPP.value:
                # Local model - requires a valid model_path.
                model_path_str = cfg.get("model_path")
                if not model_path_str:
                    raise ValueError(f"Local custom model '{model_id}' has no model_path configured")
                
                model_path = Path(model_path_str)
                if not model_path.exists():
                    raise ValueError(f"Model file not found: {model_path}")
                
                api_logger.info(f"Loading local custom model from: {model_path}")
                
                # Create the model instance with the actual model path.
                model = handler_class(
                    model_path=model_path,
                    required_capabilities=capabilities
                )
                
                # Set the model name to load any additional config from registry.
                model.set_model_name(model_id)
                
            else:
                # API models don't need a real path, but the base class requires one.
                model = handler_class(
                    model_path=self.models_dir,
                    required_capabilities=capabilities
                )
                
                # Set the model name to load config from registry.
                model.set_model_name(model_id)
            
            # Load/initialize the model (sets up API client or loads local model).
            await model.load()
            
            # Cache the loaded model.
            self._active_models[model_id] = model
            
            api_logger.info(f"Successfully loaded custom model: {model_id}")
            return model
            
        except Exception as e:
            api_logger.error(f"Failed to load custom model {model_id}: {e}")
            raise RuntimeError(f"Failed to load custom model: {e}")

    async def test_model(
        self,
        model_type: str,
        variant: str,
        test_prompt: str = "Respond with 'OK' if you can understand this."
    ) -> Dict:
        """Test if a model is working correctly."""
        # API models don't need to be downloaded
        is_api_model = model_type in ["openai", "claude", "gemini"]
        
        if not is_api_model and not self.is_model_downloaded(model_type, variant):
            return {
                "status": "error",
                "error": "Model not downloaded",
                "error_type": "model_not_found"
            }

        try:
            model = await self.load_model(
                model_type,
                variant,
                {ModelCapability.REASONING}
            )
            
            response = await model.generate_response(
                test_prompt,
                max_tokens=50
            )
            
            return {
                "status": "success",
                "response": response,
                "model_state": model.state.value
            }
        except Exception as e:
            return {
                "status": "error",
                "error": str(e),
                "model_state": model.state.value if 'model' in locals() else "unknown"
            }

    async def cleanup(self) -> None:
        """Cleanup all loaded models."""
        for model_id in list(self._active_models.keys()):
            model_type, variant = model_id.split("-", 1)
            await self.unload_model(model_type, variant)

    def get_available_models(self) -> Dict:
        """Get list of available models."""
        return self.model_downloader.get_available_models()

    def get_installed_models(self) -> Dict:
        """Get list of installed models."""
        return self.model_downloader.get_installed_models()

@lru_cache()
def get_model_service() -> ModelService:
    """Get or create model service singleton."""
    models_directory = get_models_dir()

    api_logger.info(f"[ModelService Singleton] Initializing with models_dir: {models_directory}")
    service = ModelService(models_directory)
    # Make sure to initialize the service with model classes
    service.initialize()
    return service 