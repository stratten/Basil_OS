import asyncio
from typing import Dict, Optional
from fastapi import APIRouter, Depends, WebSocket, HTTPException, Request
from pydantic import BaseModel

from ...core.services.model_download_manager import DownloadManager
from ...core.services.model_service import ModelService, ModelNotFoundError, ModelCapability
from ...dependencies import get_model_service


router = APIRouter(prefix="/test", tags=["Model Testing"])


class TestRequest(BaseModel):
    """Request body for model test endpoint."""
    model_type: str
    variant: str
    test_prompt: Optional[str] = None


class DownloadRequest(BaseModel):
    """Request body for model download endpoint."""
    model_type: str
    variant: str


class LoadRequest(BaseModel):
    """Request body for model load endpoint."""
    model_type: str
    variant: str


def _get_download_manager(request: Request) -> DownloadManager:
    manager = getattr(request.app.state, "download_manager", None)
    if manager is None:
        raise HTTPException(
            status_code=503,
            detail="Download manager not initialized; backend still starting.",
        )
    return manager


@router.get("/models/available")
async def list_available_models(
    model_service: ModelService = Depends(get_model_service)
) -> Dict:
    """List all available models and their variants."""
    return model_service.model_downloader.get_available_models()


@router.get("/models/installed")
async def list_installed_models(
    model_service: ModelService = Depends(get_model_service)
) -> Dict:
    """List all installed models and their metadata."""
    return model_service.model_downloader.get_installed_models()


@router.post("/models/download")
async def download_model(
    request: DownloadRequest,
    http_request: Request,
    model_service: ModelService = Depends(get_model_service)
) -> Dict:
    """Download a specific model variant.
    
    This endpoint will:
    1. Verify the model type and variant exist
    2. Check if the model is already downloaded
    3. Start the download if needed
    4. Return the download status
    """
    try:
        if model_service.is_model_downloaded(request.model_type, request.variant):
            return {
                "status": "success",
                "message": "Model is already downloaded",
                "path": str(model_service.models_dir / f"{request.model_type}-{request.variant}")
            }

        manager = _get_download_manager(http_request)
        entry = await manager.start(
            request.model_type,
            request.variant
        )
        
        return {
            "status": "success",
            "message": "Model download queued",
            "model_id": entry.model_id,
            "download_status": entry.status,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Download failed: {str(e)}")


@router.post("/models/load")
async def load_model(
    request: LoadRequest,
    model_service: ModelService = Depends(get_model_service)
) -> Dict:
    """Load a downloaded model into memory.
    
    This endpoint will:
    1. Check if the model is downloaded
    2. Load it into memory if not already loaded
    3. Return the load status
    """
    try:
        if not model_service.is_model_downloaded(request.model_type, request.variant):
            raise HTTPException(
                status_code=404,
                detail="Model not found. Please download the model first."
            )

        model = await model_service.load_model(
            request.model_type,
            request.variant,
            {ModelCapability.REASONING}
        )
        
        return {
            "status": "success",
            "message": "Model loaded successfully",
            "model_state": model.state.value
        }
    except ModelNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.websocket("/models/download/{model_type}/{variant}/progress")
async def download_progress(
    websocket: WebSocket,
    model_type: str,
    variant: str,
    model_service: ModelService = Depends(get_model_service)
):
    """WebSocket endpoint for test clients; bridges DownloadManager state."""
    from ...core.logging.api_logger import api_logger
    
    api_logger.warning(f"🔌 [WEBSOCKET] WebSocket connection opened for {model_type}-{variant}")
    api_logger.warning(f"🔌 [WEBSOCKET] Polling DownloadManager state")
    
    await websocket.accept()
    
    try:
        manager = getattr(websocket.app.state, "download_manager", None)
        if manager is None:
            await websocket.send_json({
                "status": "error",
                "progress": 0.0,
                "message": "Download manager not initialized",
            })
            return
        
        # Check if already downloaded
        if model_service.is_model_downloaded(model_type, variant):
            api_logger.info(f"🔌 [WEBSOCKET] Model {model_type}-{variant} already downloaded")
            await websocket.send_json({
                "status": "completed",
                "progress": 1.0,
                "message": "Model is already downloaded"
            })
            return
        
        last_progress = -1.0
        last_status = ""
        while True:
            try:
                entry = manager.get_by_pair(model_type, variant)
                if entry is None:
                    if last_progress < 0:
                        await websocket.send_json({
                            "progress": 0.0,
                            "status": "pending",
                            "message": "Waiting for download to start..."
                        })
                        last_progress = 0.0
                    await asyncio.sleep(0.5)
                    continue

                payload = entry.to_progress_payload()
                current_progress = payload.get("progress", 0.0)
                status = payload.get("status", "downloading")

                if current_progress != last_progress or status != last_status:
                    api_logger.debug(
                        f"🔌 [WEBSOCKET] Sending progress {current_progress:.2%} for {entry.model_id} (status: {status})"
                    )
                    await websocket.send_json(payload)
                    last_progress = current_progress
                    last_status = status

                if status in ["completed", "user_canceled", "failed"] or current_progress >= 1.0:
                    api_logger.info(f"🔌 [WEBSOCKET] Download finished for {entry.model_id}, status: {status}")
                    break

                await asyncio.sleep(0.5)
                
            except Exception as read_error:
                api_logger.error(f"🔌 [WEBSOCKET] Error reading progress file: {read_error}")
                await asyncio.sleep(0.5)
                continue
    except Exception as e:
        await websocket.send_json({
            "status": "error",
            "error": str(e)
        })
    finally:
        await websocket.close()


@router.post("/model/test")
async def test_model(
    request: TestRequest,
    model_service: ModelService = Depends(get_model_service)
) -> Dict:
    """Test if a model is working correctly.
    
    This endpoint will:
    1. Check if the model is downloaded
    2. Load it into memory if needed
    3. Run a simple test prompt
    4. Return the results
    """
    return await model_service.test_model(
        request.model_type,
        request.variant,
        request.test_prompt
    )


@router.get("/model/{model_type}/{variant}/status")
async def get_model_status(
    model_type: str,
    variant: str,
    model_service: ModelService = Depends(get_model_service)
) -> Dict:
    """Get detailed status of a specific model."""
    return await model_service.get_model_status(model_type, variant)
