"""
Download Service for Custom Models.

Handles model downloads from HuggingFace with progress tracking,
and GGUF metadata extraction for auto-populating model configs.
"""

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

from api.core.models.models_registry import get_custom_models, update_custom_model
from api.settings import get_models_dir

from .schemas import DownloadRequest, DownloadResponse
from .huggingface_service import normalize_hf_url


logger = logging.getLogger(__name__)


# Store active download tasks
_active_downloads: Dict[str, Any] = {}


# =============================================================================
# PROGRESS TRACKING
# =============================================================================


def _get_progress_tracker():
    """Get the ProgressTracker instance from ModelService."""
    from api.dependencies import get_model_service
    model_service = get_model_service()
    return model_service.model_downloader.progress_tracker


def write_progress(model_id: str, progress: float, status: str, message: str = ""):
    """Write progress using the existing ProgressTracker infrastructure.
    
    Uses 'custom' as the model_type and model_id as the variant to match
    the existing progress file naming convention: progress_custom-{model_id}.json
    """
    try:
        progress_tracker = _get_progress_tracker()
        metadata = {"message": message} if message else None
        # Use 'custom' as model_type, model_id as variant -> progress_custom-{model_id}.json
        progress_tracker._update_progress_sync("custom", model_id, progress, status, metadata)
    except Exception as e:
        logger.error(f"[CustomDownload] Failed to write progress: {e}")


def cleanup_progress(model_id: str):
    """Remove the progress file for a custom model."""
    models_dir = get_models_dir()
    progress_file = models_dir / f"progress_custom-{model_id}.json"
    try:
        if progress_file.exists():
            progress_file.unlink()
    except Exception as e:
        logger.warning(f"[CustomDownload] Failed to cleanup progress file: {e}")


def get_download_progress(model_id: str) -> Dict[str, Any]:
    """Get the download progress for a custom model.
    
    Uses the same ProgressTracker infrastructure as predefined models.
    Progress file: progress_custom-{model_id}.json
    """
    models_dir = get_models_dir()
    # File naming matches ProgressTracker: progress_{model_type}-{variant}.json
    progress_file = models_dir / f"progress_custom-{model_id}.json"
    
    if progress_file.exists():
        try:
            with open(progress_file, "r") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to read progress file: {e}")
    
    return {
        "model_id": model_id,
        "progress": 0.0,
        "status": "not_found",
        "message": "No active download"
    }


# =============================================================================
# GGUF METADATA EXTRACTION
# =============================================================================


def extract_gguf_metadata(file_path: str) -> Dict[str, Any]:
    """Extract metadata from a GGUF file after download.
    
    Returns a dict with:
    - context_window: int (if found)
    - architecture: str (if found)
    - capabilities: list of inferred capabilities
    - model_type: str (if found)
    """
    metadata: Dict[str, Any] = {}
    
    try:
        from gguf import GGUFReader
        
        reader = GGUFReader(file_path)
        
        # Extract all available metadata
        for field in reader.fields.values():
            field_name = field.name.lower() if hasattr(field, 'name') else ""
            
            # Context length
            if 'context_length' in field_name or 'n_ctx' in field_name:
                if hasattr(field, 'parts'):
                    for part in field.parts:
                        if hasattr(part, 'tolist'):
                            values = part.tolist()
                            if values and isinstance(values[0], (int, float)):
                                metadata['context_window'] = int(values[0])
                                logger.info(f"[GGUF] Found context_window: {metadata['context_window']}")
            
            # Architecture
            if field_name == 'general.architecture':
                if hasattr(field, 'parts'):
                    for part in field.parts:
                        if hasattr(part, 'tolist'):
                            values = part.tolist()
                            if values:
                                # Convert bytes to string if needed
                                arch = values[0] if isinstance(values[0], str) else bytes(values).decode('utf-8').rstrip('\x00')
                                metadata['architecture'] = arch
                                logger.info(f"[GGUF] Found architecture: {arch}")
            
            # Model name
            if field_name == 'general.name':
                if hasattr(field, 'parts'):
                    for part in field.parts:
                        if hasattr(part, 'tolist'):
                            values = part.tolist()
                            if values:
                                name = values[0] if isinstance(values[0], str) else bytes(values).decode('utf-8').rstrip('\x00')
                                metadata['model_name'] = name
                                logger.info(f"[GGUF] Found model_name: {name}")
            
            # Chat template - crucial for capability inference
            if 'chat_template' in field_name:
                if hasattr(field, 'parts'):
                    for part in field.parts:
                        if hasattr(part, 'tolist'):
                            values = part.tolist()
                            if values:
                                template = values[0] if isinstance(values[0], str) else bytes(values).decode('utf-8').rstrip('\x00')
                                metadata['chat_template'] = template
                                logger.info(f"[GGUF] Found chat_template ({len(template)} chars)")
        
        # Infer capabilities from metadata
        capabilities = ["reasoning"]  # All GGUF models can reason
        
        # Check chat template for function/tool calling support
        chat_template = metadata.get('chat_template', '')
        if chat_template:
            template_lower = chat_template.lower()
            if '<tool' in template_lower or '<function' in template_lower or 'tool_call' in template_lower:
                capabilities.append("function_calling")
                logger.info("[GGUF] Inferred function_calling capability from chat_template")
            if 'json' in template_lower and ('output' in template_lower or 'format' in template_lower):
                capabilities.append("json_mode")
                logger.info("[GGUF] Inferred json_mode capability from chat_template")
        
        # Check architecture for known capabilities
        arch = metadata.get('architecture', '').lower()
        if arch in ['llama', 'qwen2', 'phi3']:
            if 'instruction_following' not in capabilities:
                capabilities.append("instruction_following")
        
        # Check filename for hints
        filename_lower = Path(file_path).name.lower()
        if 'instruct' in filename_lower or 'chat' in filename_lower:
            if 'instruction_following' not in capabilities:
                capabilities.append("instruction_following")
        
        metadata['inferred_capabilities'] = capabilities
        logger.info(f"[GGUF] Inferred capabilities: {capabilities}")
        
        return metadata
        
    except ImportError:
        logger.warning("[GGUF] gguf library not available, skipping metadata extraction")
        return {}
    except Exception as e:
        logger.warning(f"[GGUF] Failed to extract metadata: {e}")
        return {}


# =============================================================================
# DOWNLOAD SERVICE
# =============================================================================


class CustomModelDownloadService:
    """Handles downloading custom models from HuggingFace."""
    
    def is_downloading(self, model_id: str) -> bool:
        """Check if a model is currently being downloaded."""
        return model_id in _active_downloads
    
    async def download_model(self, model_id: str, request: DownloadRequest) -> DownloadResponse:
        """Download a custom model file from HuggingFace.
        
        Looks up the custom model config to get the download_url (repo URL),
        downloads the specified file, and updates the model config with the
        resulting model_path.
        """
        import os
        from huggingface_hub import hf_hub_download
        
        # Use HuggingFace's internal tqdm wrapper (not the standard tqdm package)
        # because hf_hub_download uses huggingface_hub.utils.tqdm internally.
        try:
            from huggingface_hub.utils import tqdm as hf_tqdm_module
            from huggingface_hub.utils.tqdm import are_progress_bars_disabled, enable_progress_bars
            
            # Enable HuggingFace progress bars (may be disabled in non-TTY environments)
            if are_progress_bars_disabled():
                logger.info("[CustomDownload] Enabling HuggingFace progress bars")
                enable_progress_bars()
            
            tqdm = hf_tqdm_module.tqdm
            logger.info("[CustomDownload] Using huggingface_hub.utils.tqdm for progress tracking")
        except (ImportError, AttributeError) as e:
            logger.warning(f"[CustomDownload] Could not import huggingface_hub.utils.tqdm, falling back to tqdm.auto: {e}")
            from tqdm.auto import tqdm
        
        # Ensure HF progress bars stay enabled
        os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "0"
        
        # Get the model config.
        models = get_custom_models()
        if model_id not in models:
            return DownloadResponse(
                success=False,
                message=f"Custom model '{model_id}' not found",
                error="Model not found"
            )
        
        cfg = models[model_id]
        download_url = cfg.get("download_url")
        
        if not download_url:
            return DownloadResponse(
                success=False,
                message="Model does not have a download_url configured",
                error="No download URL"
            )
        
        # Check if already downloading
        if model_id in _active_downloads:
            return DownloadResponse(
                success=False,
                message="Download already in progress",
                error="Download already in progress for this model"
            )
        
        try:
            # Normalize URL to repo_id.
            repo_id = normalize_hf_url(download_url)
            logger.info(f"Downloading {request.filename} from {repo_id} for model {model_id}")
            
            # Get the canonical models directory.
            models_dir = get_models_dir()
            
            # Write initial progress
            write_progress(model_id, 0.0, "initializing", f"Starting download of {request.filename}")
            _active_downloads[model_id] = True
            
            # Patch tqdm.__init__ to inject progress tracking (same technique as model_downloader.py)
            original_tqdm_init = tqdm.__init__
            target_model_id = model_id  # Capture for closure
            target_filename = request.filename
            
            def patched_tqdm_init(self, *args, **kwargs):
                # Force disable=False so tqdm.update() actually works (even in non-TTY)
                kwargs['disable'] = False
                original_tqdm_init(self, *args, **kwargs)
                original_update = self.update
                def new_update(n=1):
                    result = original_update(n)
                    try:
                        if self.total and self.total > 0:
                            progress = self.n / self.total
                            write_progress(
                                target_model_id,
                                progress,
                                "downloading",
                                f"Downloading {target_filename}: {int(progress * 100)}%"
                            )
                            logger.debug(f"[CustomDownload] Progress: {int(progress * 100)}% ({self.n}/{self.total})")
                    except Exception as e:
                        logger.error(f"Error in progress callback: {e}")
                    return result
                self.update = new_update
            
            tqdm.__init__ = patched_tqdm_init
            
            try:
                # Run download in thread to avoid blocking the event loop
                def download_file():
                    return hf_hub_download(
                        repo_id=repo_id,
                        filename=request.filename,
                        local_dir=models_dir / model_id,
                        local_dir_use_symlinks=False,
                    )
                
                downloaded_path = await asyncio.to_thread(download_file)
            finally:
                # Restore original tqdm
                tqdm.__init__ = original_tqdm_init
            
            logger.info(f"Downloaded model to: {downloaded_path}")
            
            # Update progress to completed
            write_progress(model_id, 1.0, "completed", "Download complete")
            
            # Update the model config with the new path.
            cfg["model_path"] = downloaded_path
            
            # Extract metadata from GGUF file and auto-populate missing fields
            if downloaded_path.endswith('.gguf'):
                write_progress(model_id, 1.0, "extracting_metadata", "Extracting model metadata...")
                gguf_metadata = extract_gguf_metadata(downloaded_path)
                
                # Auto-populate context_window if not set or is default
                if gguf_metadata.get('context_window') and cfg.get('context_window', 4096) == 4096:
                    cfg['context_window'] = gguf_metadata['context_window']
                    logger.info(f"[CustomDownload] Auto-set context_window to {cfg['context_window']} from GGUF")
                
                # Store extracted metadata for reference
                if gguf_metadata.get('architecture'):
                    cfg['gguf_architecture'] = gguf_metadata['architecture']
                if gguf_metadata.get('model_name'):
                    cfg['gguf_model_name'] = gguf_metadata['model_name']
                if gguf_metadata.get('inferred_capabilities'):
                    # Merge with existing capabilities
                    existing = set(cfg.get('capabilities', []))
                    existing.update(gguf_metadata['inferred_capabilities'])
                    cfg['capabilities'] = list(existing)
                    logger.info(f"[CustomDownload] Updated capabilities: {cfg['capabilities']}")
            
            update_custom_model(model_id, cfg)
            
            # Cleanup
            _active_downloads.pop(model_id, None)
            cleanup_progress(model_id)
            
            return DownloadResponse(
                success=True,
                message=f"Successfully downloaded {request.filename}",
                model_path=downloaded_path,
            )
            
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Failed to download model: {error_msg}")
            write_progress(model_id, 0.0, "error", f"Error: {error_msg}")
            _active_downloads.pop(model_id, None)
            return DownloadResponse(
                success=False,
                message=f"Download failed: {error_msg}",
                error=error_msg,
            )


# =============================================================================
# SINGLETON INSTANCE
# =============================================================================

# Pre-instantiate service for route injection
download_service = CustomModelDownloadService()
