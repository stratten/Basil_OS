from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Type
import asyncio
import time
from dataclasses import dataclass

from ..logging.api_logger import api_logger
from .base_model import BaseAIModel, ModelMetadata, ModelState
from .model_download.artifacts import ModelArtifactStore
from .model_types import ModelCapability
from .models_registry import get_model, is_in_registry, ModelLocation


class ModelNotFoundError(Exception):
    """Raised when a model file cannot be found."""
    pass


@dataclass
class _ModelEntry:
    """Internal model entry with usage tracking and unload scheduling."""
    model: BaseAIModel
    last_used_ts: float
    unload_task: Optional[asyncio.Task] = None


class ModelManager:
    """Manages AI model lifecycle and selection with idle-based unloading."""

    def __init__(self, models_dir: Path, default_idle_seconds: int = 300):
        self.models_dir = models_dir
        self.models_dir.mkdir(parents=True, exist_ok=True)
        self._models: Dict[str, _ModelEntry] = {}
        self._model_classes: Dict[str, Type[BaseAIModel]] = {}
        self._default_idle_seconds = default_idle_seconds  # 5 minutes default
        self.logger = api_logger.getChild("model_manager")
        self.logger.info(f"ModelManager initialized with models directory: {models_dir}, idle timeout: {default_idle_seconds}s")

    def _get_model_config(self, model_name: str) -> Optional[Dict[str, Any]]:
        """
        Get model configuration from the unified registry.

        Args:
            model_name: The model ID (e.g. "Qwen-qwen3-8b-instruct-q4km" or "qwen3-8b-instruct-q4km").

        Returns:
            Model config dict if found, None otherwise.
        """
        # Check unified registry.
        registry_cfg = get_model(model_name)
        if registry_cfg:
            self.logger.info(f"📚 Found model '{model_name}' in unified registry")
            return registry_cfg

        # If not found directly, try with different provider prefixes.
        # This handles cases where model_name might not include the provider prefix.
        if "-" not in model_name or not is_in_registry(model_name):
            # Try common provider prefixes.
            from .models_registry import get_local_reasoning_models, get_transcription_models
            
            for model_id, cfg in get_local_reasoning_models().items():
                # Check if the variant part matches.
                if "-" in model_id:
                    _, variant = model_id.split("-", 1)
                    if variant == model_name or cfg.get("on_disk_name") == model_name:
                        self.logger.info(f"📚 Found model '{model_name}' as '{model_id}' in unified registry")
                        return cfg
            
            for model_id, cfg in get_transcription_models().items():
                if "-" in model_id:
                    _, variant = model_id.split("-", 1)
                    if variant == model_name or cfg.get("on_disk_name") == model_name:
                        self.logger.info(f"📚 Found model '{model_name}' as '{model_id}' in unified registry")
                        return cfg

        return None

    def register_model_class(self, model_type: str, model_class: Type[BaseAIModel]) -> None:
        """Register a model class for a specific model type."""
        self._model_classes[model_type] = model_class
        self.logger.info(f"✅ Registered model class {model_class.__name__} for type '{model_type}' (total registered: {len(self._model_classes)})")

    async def load_model(self, model_name: str, model_type: str, required_capabilities: Optional[Set[ModelCapability]] = None) -> BaseAIModel:
        """Load a model into memory and schedule idle unload."""
        start_time = time.time()
        self.logger.info(f"\n==== LOADING MODEL: {model_name} (type: {model_type}) ====")
        self.logger.info(f"Required capabilities: {[c.name for c in required_capabilities] if required_capabilities else 'None'}")
        
        # ✅ CHECK IF MODEL IS ALREADY LOADED (PERSISTENCE FIX)
        if model_name in self._models:
            entry = self._models[model_name]
            if entry.model.is_loaded and entry.model.state == ModelState.READY:
                self.logger.info(f"🚀 Model {model_name} already loaded, returning cached instance (took {time.time() - start_time:.2f}s)")
                # Cancel any pending unload and update last used timestamp
                self._cancel_unload(entry, reason="model_reused")
                entry.last_used_ts = time.time()
                return entry.model
            else:
                self.logger.info(f"Model {model_name} exists but not ready (state: {entry.model.state}), reloading...")
        
        self.logger.info(f"Models directory: {self.models_dir}")
        self.logger.info(f"Available model types: {list(self._model_classes.keys())}")
        
        if model_type not in self._model_classes:
            self.logger.error(f"❌ Unknown model type: {model_type}")
            self.logger.error(f"❌ Available model types: {list(self._model_classes.keys())}")
            raise ValueError(f"Unknown model type: {model_type}")

        # Get the model class for this type (with config override support)
        model_class = self._model_classes[model_type]
        
        # Check if model config specifies a different model_class (registry or legacy)
        model_cfg = self._get_model_config(model_name)
        if model_cfg:
            # Check for handler in registry (new) or model_class in legacy config.
            handler = model_cfg.get("handler")
            model_class_override = model_cfg.get("model_class")

            if handler:
                # New registry approach: use HANDLER_CLASS_MAP from model_service.
                try:
                    from ..services.model_service import get_handler_class
                    from .models_registry import ModelHandler

                    handler_enum = ModelHandler(handler) if isinstance(handler, str) else handler
                    model_class = get_handler_class(handler_enum)
                    self.logger.info(f"Using handler class from registry: {handler} -> {model_class.__name__}")
                except (ValueError, ImportError) as e:
                    self.logger.debug(f"Could not resolve handler '{handler}' from registry: {e}")
            elif model_class_override:
                # Legacy approach: model_class key in config (deprecated).
                if model_class_override in self._model_classes:
                    model_class = self._model_classes[model_class_override]
                    self.logger.info(f"Using model_class override from legacy config: {model_class_override} -> {model_class.__name__}")
                else:
                    self.logger.warning(f"Config specifies model_class '{model_class_override}' but it's not registered, using default: {model_class.__name__}")
        
        self.logger.info(f"Using model class: {model_class.__name__}")
        
        # Resolve an exact primary file for a declared multi-file GGUF manifest.
        artifact_files = model_cfg.get("artifact_files") if model_cfg else None
        artifact_root = model_cfg.get("artifact_root") if model_cfg else None
        primary_artifact = model_cfg.get("primary_artifact") if model_cfg else None
        if artifact_files:
            if (
                not isinstance(artifact_files, list)
                or not isinstance(artifact_root, str)
                or not isinstance(primary_artifact, str)
            ):
                raise ModelNotFoundError(
                    f"Model {model_name} has an invalid GGUF artifact manifest."
                )
            try:
                manifest_root = self.models_dir / ModelArtifactStore._safe_relative_artifact_path(
                    artifact_root
                )
                primary_path = manifest_root / ModelArtifactStore._safe_relative_artifact_path(
                    primary_artifact
                )
            except ValueError as exc:
                raise ModelNotFoundError(
                    f"Model {model_name} has an invalid GGUF artifact manifest."
                ) from exc
            missing_files: List[str] = []
            for item in artifact_files:
                if not isinstance(item, dict):
                    missing_files.append(str(item))
                    continue
                filename = str(item.get("file") or "")
                try:
                    artifact_path = manifest_root / ModelArtifactStore._safe_relative_artifact_path(
                        filename
                    )
                except ValueError:
                    missing_files.append(filename)
                    continue
                if not artifact_path.is_file():
                    missing_files.append(filename)
            if missing_files:
                raise ModelNotFoundError(
                    f"Model {model_name} is incomplete; missing manifest artifacts: "
                    f"{', '.join(missing_files)}"
                )
            if not primary_path.is_file():
                raise ModelNotFoundError(
                    f"Model {model_name} primary GGUF is missing: {primary_path}"
                )
            model_path = primary_path
            self.logger.info(f"Using manifest primary model file: {model_path}")
        else:
            search_pattern = model_name
            if model_cfg:
                on_disk_name = model_cfg.get("on_disk_name")
                if on_disk_name:
                    search_pattern = on_disk_name
                    self.logger.info(f"Using on_disk_name from config: {search_pattern}")
            self.logger.info(f"Searching for model files matching pattern: {search_pattern}*")
            model_files = list(self.models_dir.glob(f"{search_pattern}*"))
            if not model_files:
                self.logger.error(
                    f"No model files found starting with {search_pattern} in {self.models_dir}"
                )
                self.logger.info(f"Directory contents: {list(self.models_dir.glob('*'))}")
                raise ModelNotFoundError(
                    f"No model files found starting with {search_pattern} in {self.models_dir}"
                )
            model_path = model_files[0]
            self.logger.info(f"Found model file: {model_path}")
        
        # Create model instance
        self.logger.info(f"Creating model instance...")
        model = model_class(model_path, required_capabilities or set())

        # Pass registry config (context_window, max_output_tokens, etc.) to models that support it
        if model_cfg and hasattr(model, "apply_registry_config"):
            model.apply_registry_config(model_cfg)

        # If model is in error state, try to unload it first
        if model.state == ModelState.ERROR:
            self.logger.warning(f"Model is in error state, unloading first...")
            await model.unload()

        # Load the model
        self.logger.info(f"Loading model...")
        load_start = time.time()
        await model.load()
        load_duration = time.time() - load_start
        self.logger.info(f"Model loading took {load_duration:.2f} seconds")

        # Validate capabilities if specified
        if required_capabilities:
            self.logger.info(f"Validating model capabilities...")
            if not model.validate_capabilities():
                self.logger.error(f"Model {model_name} does not support required capabilities: {required_capabilities}")
                await model.unload()
                raise ValueError(f"Model {model_name} does not support required capabilities: {required_capabilities}")
            self.logger.info(f"Model capabilities validated successfully")

        # Store the loaded model in an entry with usage tracking
        entry = _ModelEntry(model=model, last_used_ts=time.time())
        self._models[model_name] = entry
        
        # Schedule idle unload
        self._schedule_unload(model_name, entry)
        
        self.logger.info(f"Model {model_name} loaded successfully (total time: {time.time() - start_time:.2f}s), will unload after {self._default_idle_seconds}s idle")
        return model

    async def load_api_model(self, model_name: str, model_type: str, required_capabilities: Optional[Set[ModelCapability]] = None) -> BaseAIModel:
        """
        Load an API-based model that doesn't require local model files.
        
        IMPORTANT: API models are NOT cached. A new instance is created for each call
        to ensure statelessness between different operations (e.g., routing vs. processing).
        """
        start_time = time.time()
        self.logger.info(f"\n==== LOADING API MODEL (non-cached): {model_name} (type: {model_type}) ====")
        self.logger.info(f"Required capabilities: {[c.name for c in required_capabilities] if required_capabilities else 'None'}")
        
        if model_type not in self._model_classes:
            self.logger.error(f"Unknown API model type: {model_type}")
            raise ValueError(f"Unknown API model type: {model_type}")

        # Get the model class for this type
        model_class = self._model_classes[model_type]
        self.logger.info(f"Using API model class: {model_class.__name__}")
        
        # API models use a dummy path since they don't need local files
        dummy_path = Path(self.models_dir) / "api_models" / model_type
        dummy_path.mkdir(parents=True, exist_ok=True)
        self.logger.info(f"Using dummy path for API model: {dummy_path}")
        
        # Extract the actual variant name from model_name (e.g., openai-gpt-4o → gpt-4o)
        # BUT: For Claude and Gemini models, keep the full name including provider prefix
        # because their APIs expect the full model ID like "claude-sonnet-4-5-20250929" or "gemini-2.5-pro"
        if model_type in ["claude", "gemini"]:
            model_variant = model_name  # Keep full name for Claude and Gemini
        else:
            model_variant = model_name.split('-', 1)[1] if '-' in model_name else model_name
        
        # Create model instance with the correct variant
        self.logger.info(f"Creating API model instance for variant: {model_variant}")
        model = model_class(dummy_path, required_capabilities or set())
        
        # Set the model name for API models
        if hasattr(model, 'model_name'):
            model.model_name = model_variant
            self.logger.info(f"Set API model variant to: {model_variant}")
        
        # If model is in error state, try to unload it first
        if model.state == ModelState.ERROR:
            self.logger.warning(f"API model is in error state, unloading first...")
            await model.unload()

        # Load the model
        self.logger.info(f"Loading API model...")
        load_start = time.time()
        await model.load()
        load_duration = time.time() - load_start
        self.logger.info(f"API model loading took {load_duration:.2f} seconds")

        # Validate capabilities if specified
        if required_capabilities:
            self.logger.info(f"Validating API model capabilities...")
            if not model.validate_capabilities():
                self.logger.error(f"API model {model_name} does not support required capabilities: {required_capabilities}")
                await model.unload()
                raise ValueError(f"API model {model_name} does not support required capabilities: {required_capabilities}")
            self.logger.info(f"API model capabilities validated successfully")

        # Do NOT store/cache the API model. Return the fresh instance directly.
        self.logger.info(f"API model {model_name} created successfully (total time: {time.time() - start_time:.2f}s). Not caching.")
        return model

    async def unload_model(self, model_name: str) -> bool:
        """Unload a model from memory."""
        if model_name not in self._models:
            self.logger.info(f"Model {model_name} not loaded, nothing to unload")
            return False

        try:
            self.logger.info(f"Unloading model {model_name}...")
            entry = self._models[model_name]
            
            # Cancel any pending unload task
            self._cancel_unload(entry, reason="explicit_unload")
            
            # Unload the model
            await entry.model.unload()
            self._models.pop(model_name)
            self.logger.info(f"Successfully unloaded model {model_name}")
            return True
        except Exception as e:
            self.logger.error(f"Error unloading model {model_name}: {str(e)}")
            return False

    async def get_model_metadata(self, model_name: str) -> Optional[ModelMetadata]:
        """Get metadata for a specific model."""
        if model_name not in self._models:
            return None
        return await self._models[model_name].model.get_metadata()

    def get_available_models(self, capabilities: Set[ModelCapability]) -> List[str]:
        """Get names of available models that support the specified capabilities."""
        return [
            name for name, entry in self._models.items()
            if all(entry.model.supports_capability(cap) for cap in capabilities)
        ]

    async def cleanup(self) -> None:
        """Unload all models and cleanup resources."""
        self.logger.info(f"Cleaning up all models...")
        for model_name in list(self._models.keys()):
            await self.unload_model(model_name)
        self.logger.info(f"All models unloaded")
    
    # MARK: - Idle Unload Management
    
    def touch_model(self, model_name: str) -> None:
        """Update last-used timestamp and reset idle timer for a model."""
        if model_name in self._models:
            entry = self._models[model_name]
            self._cancel_unload(entry, reason="model_touched")
            entry.last_used_ts = time.time()
            self._schedule_unload(model_name, entry)
            self.logger.debug(f"Model {model_name} usage updated, idle timer reset")
    
    def _cancel_unload(self, entry: _ModelEntry, reason: str = "unknown") -> None:
        """Cancel any pending unload task for a model entry.
        
        Args:
            entry: The model entry whose unload task should be cancelled
            reason: Why the unload is being cancelled (for logging)
        """
        if entry.unload_task is not None and not entry.unload_task.done():
            # Store the cancellation reason in the task for logging
            if hasattr(entry.unload_task, '_cancellation_reason'):
                entry.unload_task._cancellation_reason = reason
            entry.unload_task.cancel()
            entry.unload_task = None
    
    def _schedule_unload(self, model_name: str, entry: _ModelEntry) -> None:
        """Schedule idle-based unload for a model."""
        # Cancel any existing unload task
        self._cancel_unload(entry, reason="reschedule")
        
        # Schedule new unload task
        entry.unload_task = asyncio.create_task(
            self._unload_after_delay(model_name, self._default_idle_seconds)
        )
    
    async def _unload_after_delay(self, model_name: str, idle_seconds: int) -> None:
        """Unload a model after idle timeout if not used again."""
        try:
            start_wait = time.time()
            await asyncio.sleep(idle_seconds)
            
            if model_name not in self._models:
                return  # Model already unloaded
            
            entry = self._models[model_name]
            
            # Check if model was used again during wait
            if (time.time() - entry.last_used_ts) < idle_seconds:
                self.logger.debug(f"Skip unload for '{model_name}': used again within idle window")
                return
            
            # Unload the model
            self.logger.info(f"⏰ Idle-unloading '{model_name}' after {time.time() - start_wait:.1f}s of inactivity")
            await self.unload_model(model_name)
            
        except asyncio.CancelledError:
            # Get the cancellation reason if it was set
            reason = getattr(asyncio.current_task(), '_cancellation_reason', 'unknown')
            reason_text = {
                'model_reused': 'model was reused',
                'model_touched': 'model activity detected',  
                'explicit_unload': 'explicit unload requested',
                'reschedule': 'timer rescheduled',
                'unknown': 'reason unknown'
            }.get(reason, reason)
            self.logger.debug(f"Idle unload task cancelled for '{model_name}' ({reason_text})")
        except Exception as e:
            self.logger.error(f"Error unloading model '{model_name}': {e}") 