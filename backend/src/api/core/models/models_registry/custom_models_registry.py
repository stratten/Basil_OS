"""
Custom Models Registry - User-defined models with persistent JSON storage.

This module provides storage and CRUD operations for user-defined custom models
that connect to OpenAI-compatible or Anthropic-compatible API endpoints.

STORAGE:
    Custom models are stored in ~/.basil/config/custom_models.json

USAGE:
    from .custom_models_registry import (
        get_custom_models,
        add_custom_model,
        update_custom_model,
        remove_custom_model,
    )
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional
from filelock import FileLock

logger = logging.getLogger(__name__)

# Storage location.
CUSTOM_MODELS_DIR = Path.home() / ".basil" / "config"
CUSTOM_MODELS_FILE = CUSTOM_MODELS_DIR / "custom_models.json"
CUSTOM_MODELS_LOCK = CUSTOM_MODELS_DIR / "custom_models.json.lock"

# In-memory cache of custom models (loaded on first access).
_custom_models_cache: Optional[Dict[str, Dict[str, Any]]] = None


def _ensure_directory() -> None:
    """Ensure the config directory exists."""
    CUSTOM_MODELS_DIR.mkdir(parents=True, exist_ok=True)


def _load_custom_models() -> Dict[str, Dict[str, Any]]:
    """Load custom models from disk.
    
    Returns:
        Dict mapping model_id to model config.
    """
    global _custom_models_cache
    
    if _custom_models_cache is not None:
        return _custom_models_cache
    
    _ensure_directory()
    
    if not CUSTOM_MODELS_FILE.exists():
        _custom_models_cache = {}
        return _custom_models_cache
    
    try:
        with FileLock(str(CUSTOM_MODELS_LOCK), timeout=5):
            with open(CUSTOM_MODELS_FILE, "r") as f:
                data = json.load(f)
                _custom_models_cache = data.get("models", {})
                logger.info(f"Loaded {len(_custom_models_cache)} custom models from {CUSTOM_MODELS_FILE}")
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse custom models JSON: {e}")
        _custom_models_cache = {}
    except Exception as e:
        logger.error(f"Failed to load custom models: {e}")
        _custom_models_cache = {}
    
    return _custom_models_cache


def _save_custom_models() -> None:
    """Save custom models to disk."""
    global _custom_models_cache
    
    if _custom_models_cache is None:
        return
    
    _ensure_directory()
    
    try:
        with FileLock(str(CUSTOM_MODELS_LOCK), timeout=5):
            data = {"models": _custom_models_cache}
            # Write to temp file first, then rename for atomicity.
            tmp_path = CUSTOM_MODELS_FILE.with_suffix(".json.tmp")
            with open(tmp_path, "w") as f:
                json.dump(data, f, indent=2)
            tmp_path.replace(CUSTOM_MODELS_FILE)
            logger.info(f"Saved {len(_custom_models_cache)} custom models to {CUSTOM_MODELS_FILE}")
    except Exception as e:
        logger.error(f"Failed to save custom models: {e}")
        raise


def _invalidate_cache() -> None:
    """Invalidate the in-memory cache to force reload from disk."""
    global _custom_models_cache
    _custom_models_cache = None


def get_custom_models() -> Dict[str, Dict[str, Any]]:
    """Get all custom models.
    
    Returns:
        Dict mapping model_id to model config. Returns a copy to prevent mutation.
    """
    return dict(_load_custom_models())


def get_custom_model(model_id: str) -> Optional[Dict[str, Any]]:
    """Get a specific custom model by ID.
    
    Args:
        model_id: The unique model identifier.
        
    Returns:
        Model config dict, or None if not found.
    """
    models = _load_custom_models()
    cfg = models.get(model_id)
    return dict(cfg) if cfg else None


def add_custom_model(model_id: str, config: Dict[str, Any]) -> None:
    """Add a new custom model.
    
    Args:
        model_id: Unique identifier for the model.
        config: Model configuration matching CustomModelConfig schema.
        
    Raises:
        ValueError: If model_id already exists or config is invalid.
    """
    models = _load_custom_models()
    
    if model_id in models:
        raise ValueError(f"Custom model '{model_id}' already exists")
    
    # Validate handler type first (needed for field validation).
    valid_handlers = ["openai_compatible", "anthropic_compatible", "llama_cpp"]
    handler = config.get("handler")
    if handler not in valid_handlers:
        raise ValueError(f"Handler must be one of: {valid_handlers}")
    
    # Validate required fields based on handler type.
    common_required = ["handler", "location", "provider", "display_name", 
                       "context_window", "max_output_tokens"]
    
    if handler in ["openai_compatible", "anthropic_compatible"]:
        # API models require base_url and model_identifier
        required_fields = common_required + ["base_url", "model_identifier"]
    else:
        # Local models require either model_path or download_url
        required_fields = common_required
        if not config.get("model_path") and not config.get("download_url"):
            raise ValueError("Local models require either 'model_path' or 'download_url'")
    
    missing = [f for f in required_fields if f not in config]
    if missing:
        raise ValueError(f"Missing required fields: {missing}")
    _validate_server_type(config)
    
    # Add the model.
    models[model_id] = config
    _save_custom_models()
    logger.info(f"Added custom model: {model_id}")


def _validate_server_type(config: Dict[str, Any]) -> None:
    server_type = config.get("server_type")
    if server_type is None:
        return
    if server_type not in ("openai_compatible", "ollama"):
        raise ValueError("server_type must be 'openai_compatible' or 'ollama'")
    if server_type == "ollama" and config.get("handler") != "openai_compatible":
        raise ValueError("server_type 'ollama' requires the openai_compatible handler")


def update_custom_model(model_id: str, config: Dict[str, Any]) -> None:
    """Update an existing custom model.
    
    Args:
        model_id: The model ID to update.
        config: New model configuration (replaces existing).
        
    Raises:
        ValueError: If model_id does not exist.
    """
    models = _load_custom_models()
    
    if model_id not in models:
        raise ValueError(f"Custom model '{model_id}' does not exist")
    
    # Validate handler type.
    valid_handlers = ["openai_compatible", "anthropic_compatible", "llama_cpp"]
    if config.get("handler") not in valid_handlers:
        raise ValueError(f"Handler must be one of: {valid_handlers}")
    _validate_server_type(config)
    
    # Update the model.
    models[model_id] = config
    _save_custom_models()
    logger.info(f"Updated custom model: {model_id}")


def remove_custom_model(model_id: str) -> None:
    """Remove a custom model.
    
    Args:
        model_id: The model ID to remove.
        
    Raises:
        ValueError: If model_id does not exist.
    """
    models = _load_custom_models()
    
    if model_id not in models:
        raise ValueError(f"Custom model '{model_id}' does not exist")
    
    del models[model_id]
    _save_custom_models()
    logger.info(f"Removed custom model: {model_id}")


def reload_custom_models() -> Dict[str, Dict[str, Any]]:
    """Force reload custom models from disk.
    
    Useful if another process may have modified the file.
    
    Returns:
        Dict mapping model_id to model config.
    """
    _invalidate_cache()
    return get_custom_models()
