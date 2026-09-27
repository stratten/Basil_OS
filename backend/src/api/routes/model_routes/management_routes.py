from typing import Dict, List, Any
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect, Depends
from pydantic import BaseModel
import json

from api.settings import get_settings
from api.dependencies import get_hardware_capability_service, get_model_service
from api.core.runtime.hardware_capability_service import HardwareCapabilityService
from api.core.services.model_service import ModelService
from api.services.transcription.recommendations.model_recommendation_service import (
    ModelRecommendationService, 
    UserPreference, 
    ModelRecommendation
)


router = APIRouter(prefix="/models", tags=["Model Management"])
settings = get_settings()

# Remove direct initialization to prevent duplicates
# model_downloader = ModelDownloader(settings.models_dir)
# model_manager = ModelManager(settings.models_dir)


class ModelInfo(BaseModel):
    """Model information response."""
    name: str
    size: str
    capabilities: List[str]
    installed: bool = False
    recommended_ram: str
    supports_gpu: bool


class ModelRecommendationRequest(BaseModel):
    """Request for model recommendations."""
    preference: str  # "speed", "balanced", or "accuracy"
    capability: str = "transcription"  # For future extension to other model types
    max_recommendations: int = 3


class ModelRecommendationResponse(BaseModel):
    """Response containing model recommendations."""
    modelId: str
    displayName: str
    size: str
    description: str
    speedRating: int
    accuracyRating: int
    recommendedRam: str
    score: float
    reasoning: List[str]
    systemCompatible: bool


class SystemInfoResponse(BaseModel):
    """Response containing system information."""
    totalRamGB: int
    isAppleSilicon: bool
    gpuAvailable: bool
    gpuBackend: str = None
    platform: str
    machine: str


@router.get("/available")
async def list_available_models(
    model_service: ModelService = Depends(get_model_service)
) -> Dict[str, Dict[str, ModelInfo]]:
    """List all available models for download."""
    model_downloader = model_service.model_downloader
    available = model_downloader.get_available_models()
    installed = model_downloader.get_installed_models()
    
    result = {}
    for model_type, model_data in available.items():
        result[model_type] = {}
        for variant_id, info in model_data["variants"].items():
            is_installed = f"{model_type}-{variant_id}" in installed
            result[model_type][variant_id] = ModelInfo(
                name=info["name"],
                size=info["size"],
                capabilities=info["capabilities"],
                installed=is_installed,
                recommended_ram=info["recommended_ram"],
                supports_gpu=info["supports_gpu"]
            )
    
    return result


@router.post("/recommendations")
async def get_model_recommendations(
    request: ModelRecommendationRequest
) -> Dict[str, Any]:
    """Get model recommendations based on user preferences and system capabilities."""
    try:
        # Create recommendation service
        recommendation_service = ModelRecommendationService()
        
        # Parse user preference
        try:
            preference = UserPreference(request.preference)
        except ValueError:
            raise HTTPException(
                status_code=400, 
                detail=f"Invalid preference '{request.preference}'. Must be one of: speed, balanced, accuracy"
            )
            
        # Get recommendations based on capability
        if request.capability == "transcription":
            recommendations = recommendation_service.recommend_transcription_models(
                preference=preference,
                max_recommendations=request.max_recommendations
            )
        elif request.capability == "reasoning":
            recommendations = recommendation_service.recommend_reasoning_models(
                preference=preference,
                max_recommendations=request.max_recommendations
            )
        else:
            raise HTTPException(
                status_code=400,
                detail="Only 'transcription' and 'reasoning' capabilities are currently supported"
            )
            
        # Convert to response format
        recommendation_responses = []
        for rec in recommendations:
            recommendation_responses.append(ModelRecommendationResponse(
                modelId=rec.model_id,
                displayName=rec.display_name,
                size=rec.size,
                description=rec.description,
                speedRating=rec.speed_rating,
                accuracyRating=rec.accuracy_rating,
                recommendedRam=rec.recommended_ram,
                score=rec.score,
                reasoning=rec.reasoning,
                systemCompatible=rec.score > 5.0  # Models with low scores likely incompatible
            ))
            
        # Get system information
        system_info = recommendation_service.get_system_info()
        
        return {
            "recommendations": recommendation_responses,
            "systemInfo": SystemInfoResponse(
                totalRamGB=system_info["total_ram_gb"],
                isAppleSilicon=system_info["is_apple_silicon"],
                gpuAvailable=system_info["gpu_available"],
                gpuBackend=system_info["gpu_backend"],
                platform=system_info["platform"],
                machine=system_info["machine"]
            ),
            "preferenceUsed": request.preference,
            "totalModelsEvaluated": len(recommendation_responses)
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating recommendations: {str(e)}")


@router.get("/system-info")
async def get_system_info(
    hardware_service: HardwareCapabilityService = Depends(get_hardware_capability_service),
) -> SystemInfoResponse:
    """Get system information for model compatibility assessment."""
    try:
        system_info = hardware_service.get_legacy_system_info()
        return SystemInfoResponse(
            totalRamGB=system_info["total_ram_gb"],
            isAppleSilicon=system_info["is_apple_silicon"],
            gpuAvailable=system_info["gpu_available"],
            gpuBackend=system_info["gpu_backend"],
            platform=system_info["platform"],
            machine=system_info["machine"],
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting system info: {str(e)}")


@router.post("/predefined/{model_type}/{variant}/download")
async def start_model_download(
    model_type: str, 
    variant: str,
) -> Dict[str, str]:
    """Deprecated predefined download endpoint.
    
    Downloads are queued through POST /models/download so every caller shares
    the single DownloadManager state, cancellation path, and progress contract.
    """
    raise HTTPException(
        status_code=410,
        detail=(
            "This endpoint is deprecated. Use POST /models/download with "
            '{"request":{"model_type":"%s","variant":"%s"}}.'
            % (model_type, variant)
        ),
    )


@router.delete("/predefined/{model_type}/{variant}")
async def remove_model(
    model_type: str, 
    variant: str,
    model_service: ModelService = Depends(get_model_service)
) -> Dict[str, str]:
    """Remove a downloaded predefined model.
    
    Path: /models/predefined/{model_type}/{variant}
    Custom models use: DELETE /models/custom/{model_id}
    """
    
    model_downloader = model_service.model_downloader
    model_manager = model_service.model_manager
    try:
        # Ensure model is unloaded first
        model_name = f"{model_type}-{variant}"
        await model_manager.unload_model(model_name)
        
        if await model_downloader.remove_model(model_type, variant):
            return {"status": "success", "message": "Model removed successfully"}
        else:
            raise HTTPException(status_code=404, detail="Model not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to remove model: {str(e)}")


@router.websocket("/predefined/{model_type}/{variant}/download-progress")
async def download_progress(
    websocket: WebSocket,
    model_type: str,
    variant: str
):
    """Deprecated predefined download-progress WebSocket endpoint."""
    await websocket.accept()

    try:
        await websocket.send_text(
            json.dumps(
                {
                    "status": "deprecated",
                    "error": (
                        "This WebSocket endpoint is deprecated. Poll "
                        f"/models/predefined/{model_type}/{variant}/download/progress instead."
                    ),
                }
            )
        )
    except WebSocketDisconnect:
        return
    except Exception as e:
        await websocket.send_text(
            json.dumps({
                "status": "error",
                "error": str(e)
            })
        )
    finally:
        await websocket.close() 