from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Type
import asyncio
import time
import weakref
from dataclasses import dataclass

from ..logging.api_logger import api_logger
from .base_model import BaseAIModel, ModelMetadata, ModelState
from .model_download.artifacts import ModelArtifactStore
from .model_types import ModelCapability
from .models_registry import get_model, is_in_registry, ModelLocation


class ModelNotFoundError(Exception):
    """Raised when a model file cannot be found."""
    pass


# How long a model stays loaded after its last use when no setting is supplied.
DEFAULT_IDLE_SECONDS = 300
# A model that is loaded or touched with no lease (for example by chat) gets at
# least this long before an "Immediately" setting may unload it, so a call that
# is about to generate is never unloaded between load and first token.
MIN_UNLEASED_GRACE_SECONDS = 30
# While a lease or an open window protects a model, the unload timer re-checks
# this often so a released lease or a changed setting takes effect promptly.
PROTECTED_RECHECK_SECONDS = 30


class ModelLease:
    """A claim that a loaded model is in use. Unloading waits until it is released."""

    def __init__(self, manager: "ModelManager", model_name: str, kind: str, owner: str) -> None:
        self._manager = manager
        self.model_name = model_name
        self.kind = kind
        self.owner = owner
        self._released = False

    @property
    def released(self) -> bool:
        return self._released

    def release(self) -> None:
        """Release the claim. Safe to call more than once."""
        if self._released:
            return
        self._released = True
        self._manager._release_lease(self)

    def __enter__(self) -> "ModelLease":
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.release()


@dataclass
class _ModelEntry:
    """Internal model entry with usage tracking and unload scheduling."""
    model: BaseAIModel
    last_used_ts: float
    unload_task: Optional[asyncio.Task] = None


class ModelManager:
    """Manages AI model lifecycle and selection with idle-based unloading.

    A model unloads after it has been idle for the configured delay, unless it
    is protected. Two things protect a model:

    * a run lease (``acquire_lease``), held for as long as a task may still use it;
    * an open window hold (``set_window_hold``), but only while the
      keep-loaded-while-a-window-is-open setting is on.
    """

    def __init__(
        self,
        models_dir: Path,
        default_idle_seconds: int = DEFAULT_IDLE_SECONDS,
        idle_seconds_provider: Optional[Callable[[], int]] = None,
        keep_for_windows_provider: Optional[Callable[[], bool]] = None,
    ):
        self.models_dir = models_dir
        self.models_dir.mkdir(parents=True, exist_ok=True)
        self._models: Dict[str, _ModelEntry] = {}
        self._model_classes: Dict[str, Type[BaseAIModel]] = {}
        self._default_idle_seconds = default_idle_seconds
        # Both providers are read every time they matter, so a settings change
        # applies without a restart.
        self._idle_seconds_provider = idle_seconds_provider
        self._keep_for_windows_provider = keep_for_windows_provider
        self._leases: Dict[str, Set[ModelLease]] = {}
        # (owner, window id) -> task id shown in that window.
        self._window_holds: Dict[Tuple[str, str], str] = {}
        self._unload_listeners: List[Callable[[str], None]] = []
        # Wrappers this manager unloaded, so a wrapper that is reloaded behind
        # our back (a paused run resuming) can be adopted again.
        self._retired_keys: "weakref.WeakKeyDictionary[BaseAIModel, str]" = weakref.WeakKeyDictionary()
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
                # Reset the idle clock (this also reschedules the unload timer).
                entry.last_used_ts = time.time()
                self._schedule_unload(model_name, entry)
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
            try:
                self._retired_keys[entry.model] = model_name
            except TypeError:
                pass  # not weak-referenceable; it simply cannot be re-adopted
            self.logger.info(f"Successfully unloaded model {model_name}")
            self._notify_unloaded(model_name)
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
    
    # MARK: - Leases and window holds

    def acquire_lease(self, model_name: str, kind: str = "run", owner: str = "") -> ModelLease:
        """Claim a model so it is not unloaded until the lease is released."""
        lease = ModelLease(self, model_name, kind, owner)
        self._leases.setdefault(model_name, set()).add(lease)
        return lease

    def acquire_lease_for_model(self, model: Any, owner: str = "") -> Optional[ModelLease]:
        """Lease a model instance this manager owns. Returns None for models it does not manage.

        A wrapper this manager already unloaded but that was loaded again by its
        holder (a paused run resuming) is adopted back first, so it is tracked
        and unloads on schedule again.
        """
        name = self.model_name_for(model)
        if name is None:
            retired_name = self._retired_keys.get(model)
            if retired_name is not None and getattr(model, "is_loaded", False):
                self.adopt_model(retired_name, model)
                name = retired_name
        if name is None:
            return None
        return self.acquire_lease(name, kind="run", owner=owner)

    def model_name_for(self, model: Any) -> Optional[str]:
        """Return the manager key for a model instance, or None if it is not managed."""
        for name, entry in self._models.items():
            if entry.model is model:
                return name
        return None

    def is_leased(self, model_name: str) -> bool:
        """True while any run lease holds the model."""
        return bool(self._leases.get(model_name))

    def is_protected(self, model_name: str) -> bool:
        """True while a lease or (when the setting is on) an open window holds the model."""
        return self.is_leased(model_name) or self._windows_protect()

    def _windows_protect(self) -> bool:
        return bool(self._window_holds) and self._keep_for_windows()

    def _release_lease(self, lease: ModelLease) -> None:
        leases = self._leases.get(lease.model_name)
        if leases is None:
            return
        leases.discard(lease)
        if leases:
            return
        self._leases.pop(lease.model_name, None)
        entry = self._models.get(lease.model_name)
        if entry is None:
            return
        # The idle clock starts when the last holder lets go.
        entry.last_used_ts = time.time()
        self._schedule_unload(lease.model_name, entry, after_release=True)

    def set_window_hold(self, owner: str, window_id: str, agent_task_id: str = "") -> None:
        """Record that a window that can use the model is open."""
        self._window_holds[(owner, window_id)] = agent_task_id

    def clear_window_hold(self, owner: str, window_id: str) -> None:
        """Record that a window closed."""
        if self._window_holds.pop((owner, window_id), None) is None:
            return
        if not self._window_holds:
            self._restart_idle_clocks()

    def clear_owner_window_holds(self, owner: str) -> None:
        """Drop every window hold from one connection (it disconnected)."""
        owned = [key for key in self._window_holds if key[0] == owner]
        for key in owned:
            self._window_holds.pop(key, None)
        if owned and not self._window_holds:
            self._restart_idle_clocks()

    def window_hold_count(self) -> int:
        return len(self._window_holds)

    def _restart_idle_clocks(self) -> None:
        """The last window closed: every loaded model's idle delay starts now."""
        for name, entry in list(self._models.items()):
            if self.is_leased(name):
                continue
            entry.last_used_ts = time.time()
            self._schedule_unload(name, entry, after_release=True)

    # MARK: - Adoption and unload notification

    def adopt_model(self, model_name: str, model: BaseAIModel) -> None:
        """Track a model that was loaded outside ``load_model`` so it gets idle unloading."""
        entry = self._models.get(model_name)
        if entry is not None and entry.model is model:
            return
        entry = _ModelEntry(model=model, last_used_ts=time.time())
        self._models[model_name] = entry
        self._schedule_unload(model_name, entry)

    def add_unload_listener(self, listener: Callable[[str], None]) -> None:
        """Call ``listener(model_name)`` after a model is unloaded."""
        self._unload_listeners.append(listener)

    def _notify_unloaded(self, model_name: str) -> None:
        for listener in list(self._unload_listeners):
            try:
                listener(model_name)
            except Exception as exc:
                self.logger.warning(f"Unload listener failed for {model_name}: {exc}")

    async def unload_if_unprotected(self, model_name: str) -> str:
        """Unload now unless the model is in use. Returns "unloaded", "in_use" or "not_loaded"."""
        if model_name not in self._models:
            return "not_loaded"
        if self.is_protected(model_name):
            return "in_use"
        return "unloaded" if await self.unload_model(model_name) else "not_loaded"

    # MARK: - Idle Unload Management

    def _idle_seconds(self) -> int:
        """The current idle delay in seconds (0 means unload as soon as nothing holds the model)."""
        if self._idle_seconds_provider is not None:
            try:
                return max(0, int(self._idle_seconds_provider()))
            except Exception as exc:
                self.logger.warning(f"Idle delay setting unavailable, using default: {exc}")
        return max(0, int(self._default_idle_seconds))

    def _keep_for_windows(self) -> bool:
        if self._keep_for_windows_provider is None:
            return False
        try:
            return bool(self._keep_for_windows_provider())
        except Exception as exc:
            self.logger.warning(f"Keep-loaded-for-windows setting unavailable: {exc}")
            return True

    def reschedule_idle_timers(self) -> None:
        """Re-arm every idle timer against the current settings.

        Called after the user changes the delay or the keep-loaded setting, so a
        shorter delay applies to models that are already loaded.
        """
        for name, entry in list(self._models.items()):
            if self.is_leased(name):
                continue
            self._schedule_unload(name, entry, after_release=True)

    def touch_model(self, model_name: str) -> None:
        """Update last-used timestamp and reset idle timer for a model."""
        if model_name in self._models:
            entry = self._models[model_name]
            entry.last_used_ts = time.time()
            self._schedule_unload(model_name, entry)
            self.logger.debug(f"Model {model_name} usage updated, idle timer reset")

    def _cancel_unload(self, entry: _ModelEntry, reason: str = "unknown") -> None:
        """Cancel any pending unload task for a model entry.

        Args:
            entry: The model entry whose unload task should be canceled
            reason: Why the unload is being canceled (for logging)
        """
        if entry.unload_task is not None and entry.unload_task is asyncio.current_task():
            # The idle timer is unloading its own model; canceling itself here would
            # abort the unload at its first await.
            entry.unload_task = None
            return
        if entry.unload_task is not None and not entry.unload_task.done():
            # Store the cancellation reason in the task for logging
            if hasattr(entry.unload_task, '_cancellation_reason'):
                entry.unload_task._cancellation_reason = reason
            entry.unload_task.cancel()
            entry.unload_task = None

    def _schedule_unload(self, model_name: str, entry: _ModelEntry, after_release: bool = False) -> None:
        """Schedule idle-based unload for a model.

        ``after_release`` marks a timer started because the last holder let go.
        With a zero delay that unloads right away; any other start (a load or a
        touch) keeps a short grace period so a model is never unloaded between
        being loaded and being used.
        """
        # Cancel any existing unload task
        self._cancel_unload(entry, reason="reschedule")

        delay = self._idle_seconds()
        if delay == 0 and not after_release:
            delay = MIN_UNLEASED_GRACE_SECONDS
        # Count time already spent idle, so re-arming a timer (for example after
        # the user shortens the delay) does not restart the full wait.
        delay = max(0.0, delay - max(0.0, time.time() - entry.last_used_ts))
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            self.logger.debug(f"No running loop; idle unload for '{model_name}' not scheduled")
            return
        entry.unload_task = asyncio.create_task(self._unload_after_delay(model_name, delay))

    async def _unload_after_delay(self, model_name: str, idle_seconds: float) -> None:
        """Unload a model once it has been idle long enough and nothing holds it."""
        try:
            start_wait = time.time()
            delay = idle_seconds
            while True:
                await asyncio.sleep(delay)

                entry = self._models.get(model_name)
                if entry is None:
                    return  # Model already unloaded

                if self.is_protected(model_name):
                    delay = PROTECTED_RECHECK_SECONDS
                    continue

                required = self._idle_seconds()
                idle_for = time.time() - entry.last_used_ts
                if idle_for < required:
                    delay = required - idle_for
                    continue

                self.logger.info(
                    f"⏰ Idle-unloading '{model_name}' after {time.time() - start_wait:.1f}s of inactivity"
                )
                await self.unload_model(model_name)
                return

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
            self.logger.debug(f"Idle unload task canceled for '{model_name}' ({reason_text})")
        except Exception as e:
            self.logger.error(f"Error unloading model '{model_name}': {e}")
