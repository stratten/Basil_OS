from pathlib import Path
from typing import Any, Callable, Dict, Optional
import asyncio
import time

from ..logging.api_logger import api_logger
from .models_registry import (
    get_downloadable_models,
    get_model,
)
from .model_download.artifacts import ModelArtifactStore
from .model_download.direct_file_downloader import DirectFileDownloader
from .model_download.progress_tracker import ProgressTracker
from .model_download.snapshot_downloader import SnapshotDownloader, build_snapshot_patterns


class ModelDownloader:
    """Handles downloading and managing model files."""

    def __init__(self, models_dir: Path):
        self.models_dir = models_dir
        # Compatibility fallback for artifacts created by older callers. In
        # normal app startup, models_dir should already be ~/.basil/models.
        self.legacy_models_dir = Path.home() / ".basil" / "models"
        
        # Create directories.
        self.models_dir.mkdir(parents=True, exist_ok=True)
        self.legacy_models_dir.mkdir(parents=True, exist_ok=True)
        
        self.progress_tracker = ProgressTracker(self.models_dir)
        self.artifacts = ModelArtifactStore(self.models_dir, self.legacy_models_dir)
        self.direct_file_downloader = DirectFileDownloader(
            self.models_dir,
            self.artifacts,
            self.progress_tracker,
            self,
        )
        self.snapshot_downloader = SnapshotDownloader(self.progress_tracker, self)

    def get_available_models(self) -> Dict[str, Any]:
        """Get all downloadable models from registry, with installed status."""
        result: Dict[str, Any] = {}
        installed = self.get_installed_models()
        
        for model_id, cfg in get_downloadable_models().items():
            provider, variant = model_id.split("-", 1) if "-" in model_id else (model_id, model_id)
            
            if provider not in result:
                result[provider] = {"variants": {}}
            
            # Pass through registry config with installed status.
            # CRITICAL: Include the exact model_id so frontend doesn't need to reconstruct it.
            installed_info = installed.get(provider, {}).get("variants", {}).get(variant, {})
            result[provider]["variants"][variant] = {
                **cfg,
                "model_id": model_id,  # The canonical registry ID - frontend must use this exactly
                "name": cfg.get("display_name", model_id),
                "valid": bool(installed_info),
                "path": installed_info.get("path"),
            }
        
        return result

    def _get_model_path_for_id(self, model_id: str) -> Path:
        """Get the expected path for a model by its registry ID."""
        return self.artifacts.get_model_path_for_id(model_id)

    def _get_companion_downloads(self, model_cfg: Dict[str, Any]) -> list[Dict[str, str]]:
        """Return normalized companion file download metadata for a model."""
        return self.artifacts.get_companion_downloads(model_cfg)

    async def _download_companion_files(
        self,
        model_type: str,
        variant: str,
        model_cfg: Dict[str, Any],
        cancel_event: Optional[asyncio.Event] = None,
    ) -> None:
        """Download any required companion files into the models directory."""
        await self.direct_file_downloader.download_companion_files(
            model_type,
            variant,
            model_cfg,
            cancel_event=cancel_event,
        )

    def get_installed_models(self) -> Dict[str, Any]:
        """Get list of installed models by checking registry against disk."""
        return self.artifacts.get_installed_models()

    # Progress tracking delegation methods
    def get_download_progress(self, model_type: str, variant: str) -> float:
        """Get the current download progress for a model."""
        model_id = f"{model_type}-{variant}"
        return self.progress_tracker.get_progress(model_id)

    def _format_time(self, seconds):
        """Format seconds into human-readable time."""
        return self.progress_tracker._format_time(seconds)

    async def _update_progress(self, model_type: str, variant: str, progress: float, status: str = "downloading", metadata: dict = None):
        """Update the progress of a model download with detailed metadata."""
        return await self.progress_tracker._update_progress(model_type, variant, progress, status, metadata)

    async def _start_heartbeat(self, model_type: str, variant: str):
        """Start a heartbeat to send regular updates even when progress is static."""
        return await self.progress_tracker._start_heartbeat(model_type, variant)

    # Removed in step 1.2.6 of the Huey-removal plan:
    #   * `is_downloading(...)` — relied on `progress_*.json` files which no
    #     longer exist; callers now read `DownloadManager` state instead.
    #   * `cancel_download(...)` — file-poll cancellation is replaced by
    #     `DownloadManager.cancel(...)` which sets the per-entry asyncio
    #     `cancel_event` and `task.cancel()`s the background task.
    # Predefined model routes now talk to `app.state.download_manager`
    # (`api.core.services.model_download_manager.DownloadManager`) directly.

    def remove_all_progress_callbacks(self, model_type: str, variant: str):
        """Remove all progress callbacks for a model."""
        self.progress_tracker.remove_all_progress_callbacks(model_type, variant)

    def register_progress_callback(self, model_type: str, variant: str, callback: Callable):
        """Register a progress callback for a model."""
        self.progress_tracker.register_progress_callback(model_type, variant, callback)
    
    def unregister_progress_callback(self, model_type: str, variant: str, callback: Callable):
        """Unregister a progress callback for a model."""
        self.progress_tracker.unregister_progress_callback(model_type, variant, callback)

    def _update_progress_sync(self, model_type: str, variant: str, progress: float, status: str = "downloading", metadata: dict = None):
        """Synchronously update the progress file for a model download."""
        self.progress_tracker._update_progress_sync(model_type, variant, progress, status, metadata)

    # NOTE: the download implementations own the Hugging Face tqdm hooks now;
    # this facade keeps progress methods public for DownloadManager callbacks.

    async def download_model(
        self,
        model_type: str,
        variant: str,
        progress_callback: Optional[Callable[..., None]] = None,
        cancel_event: Optional[asyncio.Event] = None,
        tqdm_class: Optional[type] = None,
    ) -> Path:
        """Download a model repository.

        Args:
            model_type / variant: registry-keyed model identity.
            progress_callback: optional callback invoked with progress updates.
                The legacy single-float signature is still supported (the older
                code paths inside this module pass a float). The new
                `DownloadManager` callback accepts a `Dict[str, Any]` and is
                wired through `progress_tracker._update_progress` after step
                1.2.6 is in place.
            cancel_event: cooperative cancellation signal owned by the caller
                (typically `DownloadManager`). When set, the per-tick tqdm
                wrapper raises `asyncio.CancelledError` so `snapshot_download`
                / `hf_hub_download` unwind cleanly. Asyncio-level
                `task.cancel()` from the manager covers the case where no
                tqdm tick fires before cancellation.
            tqdm_class: accepted for backwards-compatible callers. The concrete
                download implementations own progress hook setup.
        """
        import traceback
        # Early diagnostic to confirm entry when called from Huey in packaged builds
        print(f"🔧 [DOWNLOAD_MODEL] Enter download_model for {model_type}-{variant}", flush=True)
        api_logger.warning(f"🔧 [DOWNLOAD_MODEL][DIAG] Enter download_model for {model_type}-{variant}")
        
        # Log where this was called from to detect duplicate downloads
        stack = traceback.extract_stack()
        caller_info = stack[-2] if len(stack) > 1 else None
        if caller_info:
            print(f"📥 [DOWNLOAD_MODEL] Called from: {caller_info.filename}:{caller_info.lineno} in {caller_info.name}", flush=True)
            api_logger.warning(f"📥 [DOWNLOAD_MODEL] Called from: {caller_info.filename}:{caller_info.lineno} in {caller_info.name}")
        print(f"📥 [DOWNLOAD_MODEL] download_model() called for {model_type}-{variant}", flush=True)
        print(f"📥 [DOWNLOAD_MODEL] Has progress_callback: {progress_callback is not None}", flush=True)
        api_logger.warning(f"📥 [DOWNLOAD_MODEL] download_model() called for {model_type}-{variant}")
        api_logger.warning(f"📥 [DOWNLOAD_MODEL] Has progress_callback: {progress_callback is not None}")
        
        # Get model config from registry.
        model_id = f"{model_type}-{variant}"
        model_cfg = get_model(model_id)
        if not model_cfg:
            raise ValueError(f"Unknown model: {model_id}")

        if model_cfg.get("manual_install_required") and not model_cfg.get(
            "download_url"
        ) and not model_cfg.get("repo_url"):
            raise ValueError(
                f"Model '{model_id}' is manual-install only; Basil does not "
                f"download it automatically. Place the required files in your "
                f"models directory."
            )

        # Build model_info from registry config.
        model_info: Dict[str, Any] = {
            "name": model_cfg.get("display_name", model_id),
            "on_disk_name": model_cfg.get("on_disk_name", variant),
        }
        
        # Add download info.
        if "download_url" in model_cfg:
            model_info["url"] = model_cfg["download_url"]
            model_info["sha256"] = model_cfg.get("sha256")
        elif "repo_url" in model_cfg:
            model_info["repo"] = {
                "url": model_cfg["repo_url"],
                "revision": model_cfg.get("revision", "main"),
            }

        snapshot_allow_patterns, snapshot_ignore_patterns = build_snapshot_patterns(
            model_id,
            model_cfg,
        )
        
        model_path = self._get_model_path_for_id(model_id)
        api_logger.info(f"Starting model download process for {model_type}-{variant}")
        api_logger.info(f"Target model path: {model_path}")
        
        # Get model ID for reference
        model_id = f"{model_type}-{variant}"

        # Resume-from-cancel state used to be reconstructed from
        # `progress_<model_id>.json` on disk so a separate Huey worker process
        # could pick up where another left off. Post-step-1.2.6 there is no
        # JSON layer and downloads never cross a process boundary; the actual
        # byte-level resume is handled by `snapshot_download(resume_download=
        # True)` against the HF cache, and UI continuity across cancel/restart
        # is owned by `DownloadManager`'s in-memory `DownloadEntry`. So we
        # always start the local progress counter at 0.0 and let the HF cache
        # short-circuit any already-downloaded blobs.
        start_progress = 0.0
        initial_metadata = {"message": "Starting download..."}

        self.progress_tracker._progress[model_id] = start_progress
        self.progress_tracker._current_operations[model_id] = "downloading"
        self.progress_tracker._download_stats[model_id] = {
            "start_time": time.time(),
            "last_progress": start_progress,
            "last_time": time.time(),
            "status": "downloading",
        }
        self._update_progress_sync(model_type, variant, start_progress, status="downloading", metadata=initial_metadata)
        await self._update_progress(model_type, variant, start_progress, status="downloading", metadata=initial_metadata)

        # Initialize progress tracking
        self.progress_tracker._current_operations[model_id] = "initializing"
        await self._update_progress(model_type, variant, start_progress, status="initializing")

        # Register progress callback if provided
        if progress_callback:
            self.register_progress_callback(model_type, variant, progress_callback)
        
        # Start heartbeat task
        heartbeat_task = asyncio.create_task(self._start_heartbeat(model_type, variant))

        try:
            if "repo" in model_info:
                return await self.snapshot_downloader.download_snapshot_model(
                    model_type,
                    variant,
                    model_id,
                    model_info,
                    model_path,
                    snapshot_allow_patterns,
                    snapshot_ignore_patterns,
                    cancel_event=cancel_event,
                )

            else:
                return await self.direct_file_downloader.download_direct_file(
                    model_type,
                    variant,
                    model_id,
                    model_cfg,
                    model_info,
                    model_path,
                    cancel_event=cancel_event,
                )
                
        except Exception as e:
            # Set error state and propagate exception
            # ADDED MORE DETAILED LOGGING FOR GENERAL EXCEPTION
            if isinstance(e, asyncio.CancelledError):
                api_logger.error(f"[CANCEL_DEBUG] Main exception handler caught asyncio.CancelledError for {model_type}-{variant}: {e}")
                # Ensure in-memory status is also updated here if not already.
                self.progress_tracker._current_operations[model_id] = "user_cancelled"
                await self._update_progress(model_type, variant, self.progress_tracker._progress.get(model_id, 0.0), status="user_cancelled", 
                                           metadata={"error": str(e), "message": "Download cancelled (main handler)."})
            else:
                api_logger.error(f"[DOWNLOAD_ERROR] General error downloading model {model_type}-{variant}: {type(e).__name__} - {e}", exc_info=True)
                await self._update_progress(model_type, variant, 0.0, status="error", 
                                           metadata={"error": str(e), "type": type(e).__name__})
            raise
        finally:
            # Clean up heartbeat task
            if 'heartbeat_task' in locals():
                heartbeat_task.cancel()
            api_logger.info(f"[DOWNLOAD_MODEL] download_model for {model_type}-{variant} is returning at {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())}")

    async def _verify_checksum(self, file_path: Path, expected_sha256: str) -> bool:
        """Verify the SHA256 checksum of a downloaded file."""
        return await self.direct_file_downloader.verify_checksum(file_path, expected_sha256)

    def remove_partial_model(self, model_type: str, variant: str) -> bool:
        """Remove incomplete or complete artifacts for one cancelled download."""
        return self.artifacts.remove_partial_artifacts(model_type, variant)

    def remove_model(self, model_type: str, variant: str) -> bool:
        """Remove a downloaded model file or directory and its HF cache if applicable."""
        # No `progress_<model_id>.json` cleanup: the JSON layer was removed in
        # step 1.2.6 of the Huey-removal plan; download state lives entirely
        # in `DownloadManager._entries` (in-memory) now.
        return self.artifacts.remove_model(model_type, variant)