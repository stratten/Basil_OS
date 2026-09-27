"""Service for model initialization and selection across different features."""

import logging
from typing import Optional, Set, List, Dict, Any, Tuple

from ..core.models.model_types import ModelCapability
from ..core.models.base_model import BaseAIModel
from ..core.services.model_service import ModelService, ModelNotFoundError
from ..core.logging.api_logger import api_logger
from ..core.models.preferences import Preferences


class ModelUsageService:
    """Service for centralizing model initialization and selection across features.
    
    This service abstracts the logic for determining the best model to use for a given task,
    handling both API models and local models, and implementing preference-based selection
    and fallback mechanisms.
    """
    
    def __init__(self, model_service: ModelService) -> None:
        """Initialize the model usage service.
        
        Args:
            model_service: The underlying model service for loading models
        """
        self.model_service = model_service
        self.logger = api_logger.getChild("model_usage_service")

    def touch_model(self, model_name: str) -> None:
        """Reset the idle-unload timer for a loaded model.

        Delegates to ModelManager.touch_model via ModelService.
        Safe to call during long-running inference to prevent the model
        from being unloaded while it is still in use.
        """
        try:
            if hasattr(self.model_service, "model_manager"):
                self.model_service.model_manager.touch_model(model_name)
        except Exception:
            pass
    
    async def get_model_for_task(
        self, 
        capabilities: Set[ModelCapability] | List[ModelCapability],
        explicit_model_id: Optional[str] = None,
        prefer_api_models: Optional[bool] = None,
        required_features: Optional[Set] = None
    ) -> Optional[BaseAIModel]:
        """Get the best model for the requested capabilities.
        
        Args:
            capabilities: Set or list of required model capabilities
            explicit_model_id: Optional specific model ID to use
            prefer_api_models: Optional override to use API models
            required_features: Optional set of ModelFeature values the model must support.
                When set, models are checked against the registry BEFORE loading.
                If the user's preferred model lacks a required feature, a ValueError
                is raised immediately with an actionable message.
            
        Returns:
            Model instance if available, None otherwise
            
        Raises:
            ValueError: If the preferred model does not support a required feature
        """
        # Convert list to set if needed
        if isinstance(capabilities, list):
            capabilities = set(capabilities)
            
        self.logger.info(f"\n==== LOOKING FOR MODEL WITH CAPABILITIES: {[c.name for c in capabilities]} ====")
        
        # If an explicit model ID is provided, try to load it directly using registry lookup
        if explicit_model_id:
            self.logger.info(f"Explicit model ID requested: {explicit_model_id}")
            try:
                return await self._load_model_by_id(explicit_model_id, capabilities)
            except Exception as e:
                self.logger.error(f"Failed to load explicit model {explicit_model_id}: {e}")
                return None
        
        # We only support REASONING capability for now
        if ModelCapability.REASONING not in capabilities:
            self.logger.warning("Only REASONING capability is supported")
            capabilities = {ModelCapability.REASONING}
            
        # Get user preference
        preferences = Preferences.load()
        preferred_model_name = preferences.models.reasoning_model
        
        self.logger.info(f"User's preferred reasoning model: {preferred_model_name}")
        
        # MARK: - API-based Selection Debugging
        self.logger.debug("ModelUsageService: anthropic_enabled = \(preferences.models.anthropic_enabled), anthropic_models = \(preferences.models.anthropic_models)")
        self.logger.debug("ModelUsageService: openai_enabled = \(preferences.models.openai_enabled), openai_models = \(preferences.models.openai_models)")
        
        # Determine whether to use API models as a fallback preference
        use_api_models = prefer_api_models if prefer_api_models is not None else preferences.models.use_api_models
        self.logger.debug(f"ModelUsageService: prefer_api_models={prefer_api_models}, preferences.models.use_api_models={preferences.models.use_api_models}, use_api_models={use_api_models}")
        
        # STRATEGY: Try to honor the user's specific model choice first, regardless of use_api_models setting
        # Only use use_api_models as a fallback preference if the preferred model isn't found
        
        # Step 1: Check if preferred model is a local model that's installed
        model_result = await self._try_load_preferred_local_model(preferred_model_name, capabilities, preferences, required_features)
        if model_result:
            self.logger.info(f"Successfully loaded preferred local model: {preferred_model_name}")
            return model_result
        
        # Step 2: Check if preferred model is an API model
        model_result = await self._try_load_preferred_api_model(preferred_model_name, capabilities, preferences)
        if model_result:
            self.logger.info(f"Successfully loaded preferred API model: {preferred_model_name}")
            return model_result
        
        # Step 3: Preferred model not found - use use_api_models as fallback preference
        self.logger.warning(f"Preferred model '{preferred_model_name}' not found. Using fallback strategy based on use_api_models={use_api_models}")
        
        if use_api_models:
            # Try any API model first
            api_model = await self._get_any_api_model(capabilities, preferences)
            if api_model:
                return api_model
            self.logger.warning("No API model found or failed to load, falling back to any local model")
            # Fall back to any local model
            return await self._get_any_local_model(capabilities, preferences, required_features)
        else:
            # Try any local model first
            local_model = await self._get_any_local_model(capabilities, preferences, required_features)
            if local_model:
                return local_model
            self.logger.warning("No local model found or failed to load, falling back to any API model")
            # Fall back to any API model
            return await self._get_any_api_model(capabilities, preferences)
    
    async def _load_model_by_id(
        self,
        model_id: str,
        capabilities: Set[ModelCapability]
    ) -> Optional[BaseAIModel]:
        """Load a model by its ID using registry lookup."""
        from ..core.models.models_registry import get_custom_models
        
        # Check custom models first, then delegate to model_service
        if model_id in get_custom_models():
            self.logger.info(f"Loading custom model: {model_id}")
            return await self.model_service.load_custom_model(model_id, capabilities)
        
        # For all other models, use model_service.load_model_by_id
        self.logger.info(f"Loading model from registry: {model_id}")
        return await self.model_service.load_model_by_id(model_id, capabilities)

    async def _try_load_preferred_api_model(
        self,
        preferred_model_name: str,
        capabilities: Set[ModelCapability],
        preferences: Preferences
    ) -> Optional[BaseAIModel]:
        """Try to load the user's preferred model if it's an API model.
        
        Args:
            preferred_model_name: The user's preferred model name
            capabilities: Set of required model capabilities
            preferences: User preferences
            
        Returns:
            API model instance if the preferred model is an API model and available, None otherwise
        """
        self.logger.info(f"Checking if preferred model '{preferred_model_name}' is an API model")
        
        # Try loading via registry-based lookup first (handles custom models too)
        try:
            result = await self._load_model_by_id(preferred_model_name, capabilities)
            if result:
                return result
        except Exception as e:
            self.logger.warning(f"Registry-based load failed for '{preferred_model_name}': {e}")
        
        # Determine which provider this model belongs to
        provider = None
        model_variant = None
        
        # Check if it's an Anthropic model
        if preferences.models.anthropic_enabled and preferred_model_name in preferences.models.anthropic_models:
            if preferences.models.anthropic_models.get(preferred_model_name, False):
                provider = "claude"
                # Strip claude- prefix to avoid duplication when constructing model_id
                model_variant = preferred_model_name[len("claude-"):] if preferred_model_name.startswith("claude-") else preferred_model_name
                self.logger.info(f"Preferred model is an enabled Anthropic model: {preferred_model_name} -> variant: {model_variant}")
        
        # Check if it's an OpenAI model
        if not provider and preferences.models.openai_enabled and preferred_model_name in preferences.models.openai_models:
            if preferences.models.openai_models.get(preferred_model_name, False):
                provider = "openai"
                # Strip openai- prefix to avoid duplication when constructing model_id
                model_variant = preferred_model_name[len("openai-"):] if preferred_model_name.startswith("openai-") else preferred_model_name
                self.logger.info(f"Preferred model is an enabled OpenAI model: {preferred_model_name} -> variant: {model_variant}")
        
        # Check if it's a Gemini model
        if not provider and preferences.models.gemini_enabled and preferred_model_name in preferences.models.gemini_models:
            if preferences.models.gemini_models.get(preferred_model_name, False):
                provider = "gemini"
                # Strip gemini- prefix to avoid duplication when constructing model_id
                model_variant = preferred_model_name[len("gemini-"):] if preferred_model_name.startswith("gemini-") else preferred_model_name
                self.logger.info(f"Preferred model is an enabled Gemini model: {preferred_model_name} -> variant: {model_variant}")
        
        # Try to infer provider from model name prefix
        if not provider:
            if preferred_model_name.startswith("gpt-") and preferences.models.openai_enabled:
                provider = "openai"
                # Strip openai- prefix to avoid duplication when constructing model_id
                model_variant = preferred_model_name[len("openai-"):] if preferred_model_name.startswith("openai-") else preferred_model_name
                self.logger.info(f"Inferred preferred model as OpenAI: {model_variant}")
            elif (preferred_model_name.startswith("claude") or "anthropic" in preferred_model_name.lower()) and preferences.models.anthropic_enabled:
                provider = "claude"
                # Strip claude- prefix to avoid duplication when constructing model_id
                model_variant = preferred_model_name[len("claude-"):] if preferred_model_name.startswith("claude-") else preferred_model_name
                self.logger.info(f"Inferred preferred model as Anthropic: {model_variant}")
            elif (preferred_model_name.startswith("gemini") or "google" in preferred_model_name.lower()) and preferences.models.gemini_enabled:
                provider = "gemini"
                # Strip gemini- prefix to avoid duplication when constructing model_id
                model_variant = preferred_model_name[len("gemini-"):] if preferred_model_name.startswith("gemini-") else preferred_model_name
                self.logger.info(f"Inferred preferred model as Gemini: {model_variant}")
        
        # Try to load the API model if identified
        if provider and model_variant:
            try:
                self.logger.info(f"Loading preferred API model: {provider}/{model_variant}")
                return await self.model_service.load_model(provider, model_variant, capabilities)
            except Exception as e:
                self.logger.error(f"Failed to load preferred API model: {e}")
                import traceback
                self.logger.error(f"Traceback: {traceback.format_exc()}")
                return None
        else:
            self.logger.info(f"Preferred model '{preferred_model_name}' is not an API model")
            return None
    
    async def _get_any_api_model(
        self, 
        capabilities: Set[ModelCapability],
        preferences: Preferences
    ) -> Optional[BaseAIModel]:
        """Get any available API model (fallback when preferred model not found).
        
        Args:
            capabilities: Set of required model capabilities
            preferences: User preferences
            
        Returns:
            API model instance if available, None otherwise
        """
        self.logger.info("Looking for any available API model as fallback")
        
        provider = None
        model_variant = None
        
        # Try Anthropic first if enabled
        if preferences.models.anthropic_enabled:
            for model_id, enabled in preferences.models.anthropic_models.items():
                if enabled:
                    provider = "claude"
                    model_variant = model_id
                    self.logger.info(f"Found fallback Anthropic model: {model_variant}")
                    break
        
        # Try OpenAI if we still don't have a provider
        if not provider and preferences.models.openai_enabled:
            for model_id, enabled in preferences.models.openai_models.items():
                if enabled:
                    provider = "openai"
                    model_variant = model_id
                    self.logger.info(f"Found fallback OpenAI model: {model_variant}")
                    break
        
        # Try Gemini if we still don't have a provider
        if not provider and preferences.models.gemini_enabled:
            for model_id, enabled in preferences.models.gemini_models.items():
                if enabled:
                    provider = "gemini"
                    model_variant = model_id
                    self.logger.info(f"Found fallback Gemini model: {model_variant}")
                    break
        
        # Try to load the API model if found
        if provider and model_variant:
            try:
                self.logger.info(f"Loading fallback API model: {provider}/{model_variant}")
                return await self.model_service.load_model(provider, model_variant, capabilities)
            except Exception as e:
                self.logger.error(f"Failed to load fallback API model: {e}")
                import traceback
                self.logger.error(f"Traceback: {traceback.format_exc()}")
                return None
        else:
            self.logger.warning("No enabled API models found")
            return None
    
    async def _try_load_preferred_local_model(
        self,
        preferred_model_name: str,
        capabilities: Set[ModelCapability],
        preferences: Preferences,
        required_features: Optional[Set] = None
    ) -> Optional[BaseAIModel]:
        """Try to load the user's preferred model if it's installed locally.
        
        Args:
            preferred_model_name: The user's preferred model name
            capabilities: Set of required model capabilities
            preferences: User preferences
            required_features: Optional set of ModelFeature values the model must support
            
        Returns:
            Local model instance if the preferred model is installed, None otherwise
            
        Raises:
            ValueError: If the model matches but lacks a required feature
        """
        self.logger.info(f"Checking if preferred model '{preferred_model_name}' is installed locally")
        
        # Get installed models
        installed_models = self.model_service.get_installed_models()
        
        # Log available models for debugging
        self.logger.info(f"Available installed models: {list(installed_models.keys())}")
        
        # First, try exact display name match
        for model_type, model_info in installed_models.items():
            for variant, variant_info in model_info["variants"].items():
                display_name = variant_info.get("name", "")
                model_capabilities = variant_info.get("capabilities", [])
                has_reasoning = "reasoning" in model_capabilities
                
                if display_name.lower() == preferred_model_name.lower() and has_reasoning:
                    self.logger.info(f"Found exact local model match: {model_type}/{variant} (display name: {display_name})")
                    self._check_required_features(variant_info, model_type, variant, display_name, required_features)
                    try:
                        return await self.model_service.load_model(model_type, variant, capabilities)
                    except Exception as e:
                        self.logger.error(f"Failed to load preferred local model: {e}")
                        return None
        
        # If no exact match, try partial/substring match
        for model_type, model_info in installed_models.items():
            for variant, variant_info in model_info["variants"].items():
                display_name = variant_info.get("name", "")
                model_capabilities = variant_info.get("capabilities", [])
                has_reasoning = "reasoning" in model_capabilities
                
                if (preferred_model_name.lower() in display_name.lower() or 
                    display_name.lower() in preferred_model_name.lower() or
                    model_type.lower() in preferred_model_name.lower()) and has_reasoning:
                    
                    self.logger.info(f"Found partial local model match: {model_type}/{variant} (display name: {display_name})")
                    self._check_required_features(variant_info, model_type, variant, display_name, required_features)
                    try:
                        return await self.model_service.load_model(model_type, variant, capabilities)
                    except Exception as e:
                        self.logger.error(f"Failed to load preferred local model: {e}")
                        return None
        
        self.logger.info(f"Preferred model '{preferred_model_name}' is not installed locally")
        return None
    
    async def _get_any_local_model(
        self, 
        capabilities: Set[ModelCapability],
        preferences: Preferences,
        required_features: Optional[Set] = None
    ) -> Optional[BaseAIModel]:
        """Get any available local model (fallback when preferred model not found).
        
        Args:
            capabilities: Set of required model capabilities
            preferences: User preferences
            required_features: Optional set of ModelFeature values; models lacking these are skipped
            
        Returns:
            Local model instance if available, None otherwise
        """
        self.logger.info("Looking for any available local model as fallback")
        
        # Get installed models
        installed_models = self.model_service.get_installed_models()
        
        # Try to find any REASONING model
        for model_type, model_info in installed_models.items():
            for variant, variant_info in model_info["variants"].items():
                capabilities_list = variant_info.get("capabilities", [])
                if isinstance(capabilities_list, list) and "reasoning" in capabilities_list:
                    if required_features and not self._has_required_features(variant_info, model_type, variant, required_features):
                        display_name = variant_info.get("name", f"{model_type}/{variant}")
                        self.logger.info(f"Skipping fallback model {display_name}: missing required features")
                        continue
                    self.logger.info(f"Found fallback local model: {model_type}/{variant}")
                    try:
                        return await self.model_service.load_model(model_type, variant, capabilities)
                    except Exception as e:
                        self.logger.error(f"Failed to load fallback local model: {e}")
                        continue
        
        self.logger.error("Could not find any suitable local reasoning model")
        return None

    async def get_designated_local_fallback_model(
        self,
        capabilities: Set[ModelCapability] | List[ModelCapability],
    ) -> Optional[BaseAIModel]:
        """Load the user-designated local fallback model for reasoning-unavailability recovery.

        Returns None (never raises) when the feature is disabled, no fallback model
        is designated, or the designated model fails to load -- callers must treat
        None as "no fallback available" and surface the original error.
        """
        preferences = Preferences.load()
        if not preferences.models.reasoning_fallback_enabled:
            return None
        fallback_model_id = (preferences.models.reasoning_fallback_model_id or "").strip()
        if not fallback_model_id:
            self.logger.info("Reasoning fallback enabled but no reasoning_fallback_model_id configured")
            return None
        try:
            model = await self._load_model_by_id(fallback_model_id, set(capabilities))
            if model:
                self.logger.info(f"Loaded designated local fallback model: {fallback_model_id}")
            return model
        except Exception as e:
            self.logger.error(f"Failed to load designated local fallback model '{fallback_model_id}': {e}")
            return None

    def _check_required_features(
        self,
        variant_info: Dict[str, Any],
        model_type: str,
        variant: str,
        display_name: str,
        required_features: Optional[Set]
    ) -> None:
        """Check that a model has all required features before loading.
        
        Raises ValueError with an actionable message if the model lacks a required feature.
        """
        if not required_features:
            return
        from ..core.models.models_registry.schema import has_feature
        registry_model_id = variant_info.get("model_id", f"{model_type}-{variant}")
        for feature in required_features:
            feat_value = feature.value if hasattr(feature, "value") else feature
            if not has_feature(registry_model_id, feature):
                raise ValueError(
                    f"The model '{display_name}' does not support {feat_value}. "
                    f"AgentTasks require function calling support. "
                    f"Please switch to a supported model in Settings."
                )

    def _has_required_features(
        self,
        variant_info: Dict[str, Any],
        model_type: str,
        variant: str,
        required_features: Set
    ) -> bool:
        """Check if a model has all required features (non-raising, for fallback paths)."""
        from ..core.models.models_registry.schema import has_feature
        registry_model_id = variant_info.get("model_id", f"{model_type}-{variant}")
        for feature in required_features:
            if not has_feature(registry_model_id, feature):
                return False
        return True

    def _parse_model_id(self, model_id: str) -> Tuple[Optional[str], Optional[str]]:
        """Parse a model ID into provider and variant, checking against preferences and registry."""
        # Load preferences to check against available API models
        preferences = Preferences.load()
        
        # FIRST: Check if it's a custom model (user-defined OpenAI/Anthropic-compatible).
        try:
            from ..core.models.models_registry import get_custom_models
            custom_models = get_custom_models()
            if model_id in custom_models:
                self.logger.info(f"Identified '{model_id}' as a custom model")
                return "custom", model_id
        except Exception as e:
            self.logger.warning(f"Failed to check custom models in _parse_model_id: {e}")

        # Handle direct format like "provider/variant"
        if "/" in model_id:
            parts = model_id.split("/", 1)
            if len(parts) == 2:
                self.logger.info(f"Parsed '{model_id}' into provider='{parts[0]}', variant='{parts[1]}'")
                return parts[0], parts[1]

        # Check if the model_id is a known OpenAI model
        if preferences.models.openai_enabled and model_id in preferences.models.openai_models:
            # Strip provider prefix from variant to avoid duplication (e.g., "gpt-4o" not "openai-gpt-4o")
            variant = model_id
            if variant.startswith("openai-"):
                variant = variant[len("openai-"):]
                self.logger.info(f"Identified '{model_id}' as OpenAI model, using variant '{variant}'")
            else:
                self.logger.info(f"Identified '{model_id}' as OpenAI model")
            return "openai", variant

        # Check if the model_id is a known Anthropic model
        if preferences.models.anthropic_enabled and model_id in preferences.models.anthropic_models:
            # Strip provider prefix from variant to avoid duplication (e.g., "sonnet-4-5-20250929" not "claude-sonnet-4-5-20250929")
            variant = model_id
            if variant.startswith("claude-"):
                variant = variant[len("claude-"):]
                self.logger.info(f"Identified '{model_id}' as Anthropic model, using variant '{variant}'")
            else:
                self.logger.info(f"Identified '{model_id}' as Anthropic model")
            return "claude", variant
        
        # Check if the model_id is a known Gemini model
        if preferences.models.gemini_enabled and model_id in preferences.models.gemini_models:
            # Strip provider prefix from variant to avoid duplication (e.g., "2.5-pro" not "gemini-2.5-pro")
            variant = model_id
            if variant.startswith("gemini-"):
                variant = variant[len("gemini-"):]
                self.logger.info(f"Identified '{model_id}' as Gemini model, using variant '{variant}'")
            else:
                self.logger.info(f"Identified '{model_id}' as Gemini model")
            return "gemini", variant
        
        # Check if the model_id is a display name from the registry.
        from ..core.models.models_registry import get_downloadable_models
        for registry_model_id, model_cfg in get_downloadable_models().items():
            display_name = model_cfg.get("display_name", "")
            if display_name == model_id:
                # Parse registry_model_id to get provider and variant.
                if "-" in registry_model_id:
                    provider, variant = registry_model_id.split("-", 1)
                else:
                    provider = variant = registry_model_id
                self.logger.info(f"Identified '{model_id}' as display name for {provider}/{variant}")
                return provider, variant
        
        # Fallback for models not in preferences but with clear prefixes
        self.logger.info(f"'{model_id}' not in preference lists, attempting to infer provider from prefix.")
        if model_id.startswith("gpt-"):
            return "openai", model_id
        elif model_id.startswith("claude-"):
            return "claude", model_id
        elif model_id.startswith("gemini-"):
            return "gemini", model_id
        elif model_id.startswith("llama-"):
            return "llama", model_id.replace("llama-", "")
        elif model_id.startswith("phi-"):
            return "phi2", model_id.replace("phi-", "")
        
        # Unknown format
        self.logger.warning(f"Could not parse or identify provider for model_id: '{model_id}'")
        return None, None


def is_model_unreachable_error(error: Exception) -> bool:
    """True when `error` means the model could not be reached/authenticated at all.

    Used only to decide eligibility for the first-attempt local fallback (never for
    mid-task retries). Covers the same network-transient signal as
    agent_execution_core._is_transient_error plus authentication/authorization
    failures, since an invalid or expired API key is also "cannot reach this model"
    from the caller's perspective, but should not be retried with backoff.
    """
    error_str = str(error).lower()
    error_type = type(error).__name__
    network_indicators = (
        "timeout", "connection", "network", "broken pipe", "temporary failure",
        "service unavailable", "gateway timeout", "bad gateway", "socket",
        "dns", "name resolution", "nodename nor servname",
    )
    auth_indicators = (
        "authenticationerror", "unauthorized", "invalid api key", "invalid x-api-key",
        "incorrect api key", "api key not valid", "401",
    )
    if any(token in error_str for token in network_indicators):
        return True
    if any(token in error_str for token in auth_indicators):
        return True
    if error_type in ("AuthenticationError", "PermissionDeniedError"):
        return True
    return False