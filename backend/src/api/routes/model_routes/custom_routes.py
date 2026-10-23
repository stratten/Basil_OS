"""
Custom Models API Routes - Thin route layer that delegates to services.

Provides endpoints for:
- Listing custom models
- Adding new custom models
- Updating existing custom models
- Deleting custom models
- Testing connection to custom model endpoints
- Probing HuggingFace repositories for available model files
- Downloading models from HuggingFace
- Validating local model file paths
"""

import logging
import shutil
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Query

from api.core.models.models_registry import (
    get_custom_models,
    add_custom_model,
    update_custom_model as registry_update_custom_model,
    remove_custom_model,
    ModelHandler,
    PROVIDER_CUSTOM,
)
from api.core.services.custom_models import (
    # Schemas
    CustomModelCreate,
    CustomModelUpdate,
    CustomModelResponse,
    CustomModelsListResponse,
    ConnectionTestRequest,
    ConnectionTestResponse,
    HFProbeRequest,
    HFProbeResponse,
    GGUFMetadataRequest,
    HFModelMetadata,
    PathValidationRequest,
    PathValidationResponse,
    DownloadRequest,
    DownloadResponse,
    SERVER_TYPE_OLLAMA,
    # Services
    connection_tester,
    huggingface_service,
    download_service,
    validate_local_path,
    get_download_progress,
)
from config.api_keys import set_api_key


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/models/custom", tags=["Custom Models"])

# Valid handlers for custom models
VALID_HANDLERS = [
    ModelHandler.OPENAI_COMPATIBLE.value,
    ModelHandler.ANTHROPIC_COMPATIBLE.value,
    ModelHandler.LLAMA_CPP.value,
]

API_HANDLERS = [
    ModelHandler.OPENAI_COMPATIBLE.value,
    ModelHandler.ANTHROPIC_COMPATIBLE.value,
]


# =============================================================================
# CRUD ENDPOINTS
# =============================================================================


@router.get("", response_model=CustomModelsListResponse)
async def list_custom_models() -> CustomModelsListResponse:
    """List all user-defined custom models."""
    models = get_custom_models()
    return CustomModelsListResponse(models=models, count=len(models))


@router.get("/{model_id}", response_model=CustomModelResponse)
async def get_custom_model_by_id(model_id: str) -> CustomModelResponse:
    """Get a specific custom model by ID."""
    models = get_custom_models()
    if model_id not in models:
        raise HTTPException(status_code=404, detail=f"Custom model '{model_id}' not found")
    
    return CustomModelResponse(model_id=model_id, config=models[model_id])


@router.post("", response_model=CustomModelResponse)
async def create_custom_model(request: CustomModelCreate) -> CustomModelResponse:
    """Create a new custom model."""
    logger.info(f"Creating custom model: model_id={request.model_id}, handler={request.handler}")
    logger.info(f"  -> base_url={request.base_url}, model_identifier={request.model_identifier}")
    logger.info(f"  -> model_path={request.model_path}, download_url={request.download_url}")
    
    # Validate handler type.
    if request.handler not in VALID_HANDLERS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid handler. Must be one of: {VALID_HANDLERS}"
        )
    
    # Determine location based on handler type.
    is_local = request.handler == ModelHandler.LLAMA_CPP.value
    location = "local" if is_local else "cloud"
    
    # Build config.
    config: Dict[str, Any] = {
        "handler": request.handler,
        "location": location,
        "provider": PROVIDER_CUSTOM,
        "display_name": request.display_name,
        "capabilities": request.capabilities or ["reasoning"],
        "features": request.features,
        "context_window": request.context_window,
        "max_output_tokens": request.max_output_tokens,
        "requires_auth": request.requires_auth,
    }
    
    # Add API-specific fields.
    if request.handler in API_HANDLERS:
        config["base_url"] = request.base_url
        config["model_identifier"] = request.model_identifier
    if request.server_type:
        config["server_type"] = request.server_type
    
    # Add local model fields.
    if is_local:
        if request.model_path:
            config["model_path"] = request.model_path
        if request.download_url:
            config["download_url"] = request.download_url
    
    if request.description:
        config["description"] = request.description

    if request.feature_config:
        config["feature_config"] = request.feature_config
    if request.tool_rendering:
        config["tool_rendering"] = request.tool_rendering
    if request.tool_call_format:
        config["tool_call_format"] = request.tool_call_format
    
    # Handle API key storage.
    if request.requires_auth:
        api_key_name = request.api_key_name or f"custom_{request.model_id}"
        config["api_key_name"] = api_key_name
        
        if request.api_key:
            try:
                set_api_key(api_key_name, request.api_key)
                logger.info(f"Stored API key for custom model: {api_key_name}")
            except Exception as e:
                logger.error(f"Failed to store API key for {api_key_name}: {e}")
                raise HTTPException(
                    status_code=500, 
                    detail=f"Failed to store API key: {str(e)}"
                )
    
    try:
        add_custom_model(request.model_id, config)
        logger.info(f"Created custom model: {request.model_id}")
        return CustomModelResponse(model_id=request.model_id, config=config)
    except ValueError as e:
        logger.error(f"Failed to create custom model '{request.model_id}': {e}")
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/{model_id}", response_model=CustomModelResponse)
async def update_custom_model_endpoint(model_id: str, request: CustomModelUpdate) -> CustomModelResponse:
    """Update an existing custom model."""
    
    models = get_custom_models()
    if model_id not in models:
        raise HTTPException(status_code=404, detail=f"Custom model '{model_id}' not found")
    
    # Get existing config and merge updates.
    config = dict(models[model_id])
    
    if request.display_name is not None:
        config["display_name"] = request.display_name
    if request.handler is not None:
        existing_handler = config.get("handler")
        if existing_handler not in API_HANDLERS or request.handler not in API_HANDLERS:
            raise HTTPException(
                status_code=400,
                detail="Only remote custom models can switch between OpenAI-compatible and Anthropic-compatible handlers.",
            )
        config["handler"] = request.handler
    if request.base_url is not None:
        config["base_url"] = request.base_url
    if request.model_identifier is not None:
        config["model_identifier"] = request.model_identifier
    if request.model_path is not None:
        config["model_path"] = request.model_path
    if request.download_url is not None:
        config["download_url"] = request.download_url
    if request.context_window is not None:
        config["context_window"] = request.context_window
    if request.max_output_tokens is not None:
        config["max_output_tokens"] = request.max_output_tokens
    if request.requires_auth is not None:
        config["requires_auth"] = request.requires_auth
    if request.capabilities is not None:
        config["capabilities"] = request.capabilities
    if request.features is not None:
        config["features"] = request.features
    if request.feature_config is not None:
        config["feature_config"] = request.feature_config
    if request.tool_rendering is not None:
        config["tool_rendering"] = request.tool_rendering
    if request.tool_call_format is not None:
        config["tool_call_format"] = request.tool_call_format
    if request.description is not None:
        config["description"] = request.description
    if request.server_type is not None:
        config["server_type"] = request.server_type
    if config.get("server_type") == SERVER_TYPE_OLLAMA and config.get("handler") != ModelHandler.OPENAI_COMPATIBLE.value:
        if request.server_type == SERVER_TYPE_OLLAMA:
            raise HTTPException(
                status_code=400,
                detail="server_type 'ollama' requires the openai_compatible handler.",
            )
        config.pop("server_type", None)
    
    # Handle API key updates.
    if request.api_key_name is not None:
        config["api_key_name"] = request.api_key_name
    if request.api_key is not None:
        api_key_name = config.get("api_key_name") or f"custom_{model_id}"
        config["api_key_name"] = api_key_name
        try:
            set_api_key(api_key_name, request.api_key)
            logger.info(f"Updated API key for custom model: {api_key_name}")
        except Exception as e:
            logger.error(f"Failed to update API key for {api_key_name}: {e}")
            raise HTTPException(
                status_code=500, 
                detail=f"Failed to update API key: {str(e)}"
            )
    
    try:
        registry_update_custom_model(model_id, config)
        logger.info(f"Updated custom model: {model_id}")
        return CustomModelResponse(model_id=model_id, config=config)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{model_id}")
async def delete_custom_model(
    model_id: str,
    delete_files: bool = Query(False, description="Also delete model files from disk"),
    clear_hf_cache: bool = Query(False, description="Also clear HuggingFace cache for this model")
) -> Dict[str, str]:
    """Delete a custom model, optionally removing associated files and HF cache."""
    
    # Get model config before deletion to find file path and download URL.
    models = get_custom_models()
    if model_id not in models:
        raise HTTPException(status_code=404, detail=f"Custom model '{model_id}' not found")
    
    cfg = models[model_id]
    model_path = cfg.get("model_path")
    download_url = cfg.get("download_url")
    
    try:
        # Delete the registry entry.
        remove_custom_model(model_id)
        logger.info(f"Deleted custom model: {model_id}")
        
        # Optionally delete files.
        files_deleted = False
        if delete_files and model_path:
            path = Path(model_path)
            if path.exists():
                try:
                    if path.is_dir():
                        shutil.rmtree(path)
                    else:
                        path.unlink()
                    files_deleted = True
                    logger.info(f"Deleted model files at: {model_path}")
                except Exception as e:
                    logger.error(f"Failed to delete model files at {model_path}: {e}")
                    return {
                        "message": f"Custom model '{model_id}' deleted, but failed to delete files: {str(e)}"
                    }
        
        # Optionally clear HuggingFace cache.
        hf_cache_cleared = False
        if clear_hf_cache and download_url:
            try:
                # Extract repo_id from download URL (e.g., "https://huggingface.co/org/repo" -> "org/repo")
                repo_id = download_url.replace("https://huggingface.co/", "").split("/blob/")[0].split("/resolve/")[0]
                
                # HF cache uses "models--org--repo" naming convention
                cache_dir = Path.home() / ".cache" / "huggingface" / "hub"
                repo_cache_dir = cache_dir / ("models--" + repo_id.replace("/", "--"))
                
                if repo_cache_dir.exists():
                    shutil.rmtree(repo_cache_dir)
                    hf_cache_cleared = True
                    logger.info(f"Cleared HuggingFace cache at: {repo_cache_dir}")
            except Exception as e:
                logger.error(f"Failed to clear HuggingFace cache: {e}")
                # Don't fail the whole operation, just log the error
        
        # Build response message.
        parts = [f"Custom model '{model_id}' deleted"]
        if files_deleted:
            parts.append("files removed")
        if hf_cache_cleared:
            parts.append("HuggingFace cache cleared")
        
        return {"message": ", ".join(parts) + " successfully"}
        
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# =============================================================================
# CONNECTION TEST ENDPOINT
# =============================================================================


@router.post("/connection-test", response_model=ConnectionTestResponse)
async def test_connection(request: ConnectionTestRequest) -> ConnectionTestResponse:
    """Test connection to a custom model endpoint."""
    return await connection_tester.test_connection(request)


# =============================================================================
# HUGGINGFACE INTEGRATION
# =============================================================================


@router.post("/probe-hf-repo", response_model=HFProbeResponse)
async def probe_huggingface_repo(request: HFProbeRequest) -> HFProbeResponse:
    """List available model files in a HuggingFace repository."""
    return await huggingface_service.probe_repo(request)


@router.post("/gguf-metadata")
async def get_gguf_file_metadata(request: GGUFMetadataRequest):
    """Fetch GGUF file metadata via partial download.
    
    Downloads only the first 256KB of the GGUF file to extract metadata
    (context_window, architecture, etc.) without downloading the full file.
    This allows users to see model specs before committing to a multi-GB download.
    """
    metadata = await huggingface_service.get_gguf_file_metadata(
        repo_id=request.repo_id,
        filename=request.filename,
    )
    
    if metadata:
        return {
            "success": True,
            "filename": request.filename,
            "context_window": metadata.context_window,
            "architecture": metadata.architecture,
            "model_name": metadata.model_name,
            "error": None
        }
    else:
        return {
            "success": False,
            "filename": request.filename,
            "context_window": None,
            "architecture": None,
            "model_name": None,
            "error": "Could not extract metadata from GGUF file header"
        }


@router.post("/local-gguf-metadata")
async def get_local_gguf_metadata(file_path: str = Query(..., description="Path to local GGUF file")):
    """Extract metadata from a local GGUF file.
    
    Uses the gguf library to read metadata (context_window, architecture, model name)
    from a complete GGUF file on disk.
    """
    from pathlib import Path
    
    path = Path(file_path)
    
    if not path.exists():
        return {
            "success": False,
            "filename": path.name,
            "context_window": None,
            "architecture": None,
            "model_name": None,
            "error": f"File not found: {file_path}"
        }
    
    if not path.suffix.lower() == ".gguf":
        return {
            "success": False,
            "filename": path.name,
            "context_window": None,
            "architecture": None,
            "model_name": None,
            "error": "File is not a GGUF file"
        }
    
    # Extract metadata using gguf library
    metadata = download_service.extract_gguf_metadata(str(path))
    
    if metadata:
        return {
            "success": True,
            "filename": path.name,
            "context_window": metadata.get("context_window"),
            "architecture": metadata.get("architecture"),
            "model_name": metadata.get("model_name"),
            "error": None
        }
    else:
        return {
            "success": False,
            "filename": path.name,
            "context_window": None,
            "architecture": None,
            "model_name": None,
            "error": "Could not extract metadata from GGUF file"
        }


# =============================================================================
# LOCAL FILE VALIDATION
# =============================================================================


@router.post("/validate-path", response_model=PathValidationResponse)
async def validate_model_path(request: PathValidationRequest) -> PathValidationResponse:
    """Validate that a path points to a valid model file."""
    return validate_local_path(request)


# =============================================================================
# MODEL DOWNLOAD
# =============================================================================


@router.post("/{model_id}/download", response_model=DownloadResponse)
async def download_model(model_id: str, request: DownloadRequest) -> DownloadResponse:
    """Download a custom model file from HuggingFace."""
    # Check if model exists
    models = get_custom_models()
    if model_id not in models:
        raise HTTPException(status_code=404, detail=f"Custom model '{model_id}' not found")
    
    return await download_service.download_model(model_id, request)


@router.get("/{model_id}/download/progress")
async def get_model_download_progress(model_id: str) -> Dict[str, Any]:
    """Get the download progress for a custom model."""
    return get_download_progress(model_id)
