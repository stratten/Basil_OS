from typing import Dict, List, Any
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect, Depends
from pydantic import BaseModel
import json

from api.settings import get_settings
from api.dependencies import get_hardware_capability_service
from api.core.runtime.hardware_capability_service import HardwareCapabilityService
from api.services.transcription.recommendations.model_recommendation_service import (
    ModelRecommendationService, 
    UserPreference, 
    ModelRecommendation
)


router = APIRouter(prefix="/models", tags=["Model Management"])
settings = get_settings()

# Model listing (`GET /models/available`) and removal (`DELETE /models/predefined/...`)
# live in predefined_routes.py. They used to be duplicated here, shadowed by the
# earlier-registered router, and the copy here could never run correctly.


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