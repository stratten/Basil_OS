from fastapi import APIRouter, HTTPException, Depends, UploadFile, File, BackgroundTasks
from typing import Optional
import os
from datetime import datetime

from ...core.services.model_service import ModelService
from ...dependencies import get_model_service, get_model_usage_service
from ...core.services.file_storage_service import StorageService
from .image_processing_service import ImageProcessor
from .image_models import ProcessingResponse, OCRError, AnalysisError, TextAnalysisRequest
from ...settings import Settings, get_settings

router = APIRouter(
    prefix="/image",
    tags=["image"]
)

def get_image_processor(
    model_service: ModelService = Depends(get_model_service),
    model_usage_service = Depends(get_model_usage_service),
    settings: Settings = Depends(get_settings)
) -> ImageProcessor:
    """Dependency to get configured image processor."""
    # Always create a new storage service to ensure proper initialization
    storage_service = StorageService()
    return ImageProcessor(
        model_service=model_service,
        model_usage_service=model_usage_service,
        storage_service=storage_service,
        settings=settings
    )

async def cleanup_temp_file(file_path: str) -> None:
    """Background task to cleanup temporary files."""
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
    except Exception as e:
        # Log but don't raise - this is a background task
        print(f"Failed to cleanup temp file {file_path}: {e}")

@router.post("/analyze", response_model=ProcessingResponse)
async def analyze_image(
    image: UploadFile = File(...),
    app_name: Optional[str] = None,
    model_id: Optional[str] = None,
    processor: ImageProcessor = Depends(get_image_processor),
    background_tasks: BackgroundTasks = BackgroundTasks()
) -> ProcessingResponse:
    """Analyze an image using OCR and AI model analysis.
    
    Args:
        image: The image file to analyze
        app_name: Optional name of the application the screenshot was captured from
        model_id: Optional model ID to use for analysis
        processor: Image processor instance (injected)
        background_tasks: FastAPI background tasks
        
    Returns:
        ProcessingResponse containing extracted text and analysis
        
    Raises:
        HTTPException: If processing fails
    """
    try:
        # Use storage service to manage the file
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"capture_{timestamp}_{app_name or 'unknown'}.png"
        temp_path = processor.storage.get_temp_path(filename)
        
        # Ensure temp directory exists
        os.makedirs(os.path.dirname(temp_path), exist_ok=True)
        
        # Save uploaded file
        content = await image.read()
        with open(temp_path, "wb") as f:
            f.write(content)
            
        # Schedule cleanup
        background_tasks.add_task(cleanup_temp_file, temp_path)
        
        # Process the saved image file
        result = await processor.process_image(
            temp_path,
            force_text_only=False,
            model_id=model_id
        )
        
        return result
    
    except OCRError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except AnalysisError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to process image: {str(e)}")

@router.post("/analyze/text", response_model=ProcessingResponse)
async def analyze_text(
    request: TextAnalysisRequest,
    model_id: Optional[str] = None,
    processor: ImageProcessor = Depends(get_image_processor)
) -> ProcessingResponse:
    """Analyze text content without image processing.
    
    Args:
        request: Text analysis request containing text and context
        model_id: Optional model ID to use for analysis (query parameter)
        processor: Image processor instance (injected)
        
    Returns:
        ProcessingResponse containing analysis results
        
    Raises:
        HTTPException: If analysis fails
    """
    try:
        # Use model_id from request if provided, otherwise use the query parameter
        effective_model_id = request.model_id or model_id
        
        if effective_model_id:
            logger.info(f"Using explicit model ID for text analysis: {effective_model_id}")
        
        return await processor.analyze_text_only(
            request.text,
            request.app_name,
            request.custom_prompt,
            model_id=effective_model_id
        )
    
    except AnalysisError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to analyze text: {str(e)}")
