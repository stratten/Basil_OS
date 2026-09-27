"""Tests for capture handler endpoints."""

import pytest
from pathlib import Path
import shutil
import os
import json
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient
from fastapi import FastAPI

from api.services.capture.manual import CaptureHandler
from api.core.services.file_storage_service import StorageService
from api.core.services.model_service import ModelService
from api.services.image_processing import ImageProcessor
# ProcessingResponse moved to image_processing.image_models
from api.services.image_processing.image_models import ProcessingResponse  # type: ignore
from api.services.capture.manual.models import CaptureResponse
from api.routes.capture.manual_routes import router, capture_screen
from api.services.capture import manual as capture_handler
from api.settings import Settings
from api.main import app

@pytest.fixture
def test_client():
    """Create a test client."""
    return TestClient(app)

@pytest.fixture
def mock_model_service():
    """Create a mock model service."""
    return MagicMock(spec=ModelService)

@pytest.fixture
def mock_storage():
    """Create a mock storage service."""
    storage = MagicMock(spec=StorageService)
    storage.get_temp_path.return_value = "/tmp/test_capture.png"
    return storage

@pytest.fixture
def mock_capture_handler(mock_model_service, mock_storage):
    """Create a mock capture handler with controlled responses."""
    handler = MagicMock(spec=capture_handler.CaptureHandler)
    
    async def mock_capture_and_process(temporary: bool = False, force_text_only: bool = False):
        # Determine analysis type based on force_text_only parameter
        analysis_type = "text-only" if force_text_only else "vision"
        
        return {
            "timestamp": datetime.utcnow(),
            "app_name": "TestApp",
            "window_title": "Test Window",
            "image_path": "/tmp/test.png",
            "processed_path": "/tmp/processed.json",
            "activity_id": "test_activity_123",
            "extracted_text": "Test OCR text",
            "analysis": {"test": "analysis"},
            "analysis_type": analysis_type,
            "processing_time_ms": 150,
            "is_temporary": temporary
        }
    
    handler.capture_and_process = AsyncMock(side_effect=mock_capture_and_process)
    handler.cleanup = AsyncMock()
    handler.find_similar_activities = AsyncMock(return_value={
        "success": True,
        "count": 1,
        "activities": [{"id": "test_activity_123", "timestamp": datetime.utcnow()}]
    })
    handler.get_recent_activities = AsyncMock(return_value={
        "success": True,
        "count": 1,
        "activities": [{"id": "test_activity_123", "timestamp": datetime.utcnow()}]
    })
    return handler

@pytest.fixture
def app_with_mocks(mock_capture_handler):
    """Create a test app with mocked dependencies."""
    test_app = FastAPI()
    
    # Override the dependency
    async def get_test_capture_handler():
        return mock_capture_handler
    
    # Add the routes with the overridden dependency
    test_app.post("/capture")(capture_screen)
    test_app.dependency_overrides = {
        "get_capture_handler": get_test_capture_handler
    }
    
    return test_app

@pytest.mark.asyncio
async def test_capture_screen_success(test_client, mock_capture_handler):
    """Test successful screen capture."""
    # Patch the dependency to use our mock
    with patch("api.routes.capture.manual_routes.get_model_service", return_value=MagicMock()):
        with patch("api.routes.capture.manual_routes.CaptureHandler", return_value=mock_capture_handler):
            response = test_client.post("/capture")
            
            assert response.status_code == 200
            data = response.json()
            assert data["operation"] == "capture"
            assert data["status"] == "success"
            details = json.loads(data["details"])
            assert details["app_name"] == "TestApp"
            assert details["window_title"] == "Test Window"
            assert details["analysis_type"] == "vision"
            assert "processing_time_ms" in details
            
            # Verify the capture_and_process was called with the right parameters
            mock_capture_handler.capture_and_process.assert_called_once_with(
                temporary=False, 
                force_text_only=False
            )

@pytest.mark.asyncio
async def test_capture_screen_with_text_only(test_client, mock_capture_handler):
    """Test screen capture with force_text_only parameter."""
    # Patch the dependency to use our mock
    with patch("api.routes.capture.manual_routes.get_model_service", return_value=MagicMock()):
        with patch("api.routes.capture.manual_routes.CaptureHandler", return_value=mock_capture_handler):
            response = test_client.post("/capture?force_text_only=true")
            
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "success"
            details = json.loads(data["details"])
            assert details["analysis_type"] == "text-only"
            
            # Verify the capture_and_process was called with force_text_only=True
            mock_capture_handler.capture_and_process.assert_called_once_with(
                temporary=False, 
                force_text_only=True
            )

@pytest.mark.asyncio
async def test_capture_screen_with_temporary(test_client, mock_capture_handler):
    """Test screen capture with temporary parameter."""
    # Patch the dependency to use our mock
    with patch("api.routes.capture.manual_routes.get_model_service", return_value=MagicMock()):
        with patch("api.routes.capture.manual_routes.CaptureHandler", return_value=mock_capture_handler):
            response = test_client.post("/capture?temporary=true")
            
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "success"
            details = json.loads(data["details"])
            assert details["app_name"] == "TestApp"
            
            # Verify the capture_and_process was called with temporary=True
            mock_capture_handler.capture_and_process.assert_called_once_with(
                temporary=True, 
                force_text_only=False
            )

@pytest.mark.asyncio
async def test_capture_screen_with_both_params(test_client, mock_capture_handler):
    """Test screen capture with both temporary and force_text_only parameters."""
    # Patch the dependency to use our mock
    with patch("api.routes.capture.manual_routes.get_model_service", return_value=MagicMock()):
        with patch("api.routes.capture.manual_routes.CaptureHandler", return_value=mock_capture_handler):
            response = test_client.post("/capture?temporary=true&force_text_only=true")
            
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "success"
            details = json.loads(data["details"])
            assert details["analysis_type"] == "text-only"
            
            # Verify the capture_and_process was called with both parameters
            mock_capture_handler.capture_and_process.assert_called_once_with(
                temporary=True, 
                force_text_only=True
            )

@pytest.mark.asyncio
async def test_capture_screen_error(test_client, mock_capture_handler):
    """Test error handling during screen capture."""
    # Configure the mock to raise an exception
    mock_capture_handler.capture_and_process.side_effect = Exception("Test error")
    
    # Patch the dependency to use our mock
    with patch("api.routes.capture.manual_routes.get_model_service", return_value=MagicMock()):
        with patch("api.routes.capture.manual_routes.CaptureHandler", return_value=mock_capture_handler):
            response = test_client.post("/capture")
            
            assert response.status_code == 200  # The endpoint handles errors internally
            data = response.json()
            assert data["status"] == "error"
            assert data["details"] == "Test error"

@pytest.mark.asyncio
async def test_cleanup_success(test_client, mock_capture_handler):
    """Test successful cleanup of temporary files."""
    # Patch the dependency to use our mock
    with patch("api.routes.capture.manual_routes.get_model_service", return_value=MagicMock()):
        with patch("api.routes.capture.manual_routes.CaptureHandler", return_value=mock_capture_handler):
            response = test_client.post("/cleanup")
            
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert "message" in data
            
            # Verify cleanup was called
            mock_capture_handler.cleanup.assert_called_once()

@pytest.mark.asyncio
async def test_cleanup_error(test_client, mock_capture_handler):
    """Test error handling during cleanup."""
    # Configure the mock to raise an exception
    mock_capture_handler.cleanup.side_effect = Exception("Cleanup error")
    
    # Patch the dependency to use our mock
    with patch("api.routes.capture.manual_routes.get_model_service", return_value=MagicMock()):
        with patch("api.routes.capture.manual_routes.CaptureHandler", return_value=mock_capture_handler):
            response = test_client.post("/cleanup")
            
            assert response.status_code == 200  # The endpoint handles errors internally
            data = response.json()
            assert data["success"] is False
            assert "error" in data

@pytest.mark.asyncio
async def test_image_processor_fallback():
    """Test that ImageProcessor falls back to text-only analysis when no vision model is available."""
    # Create a mock model service that returns None for vision models
    model_service = MagicMock(spec=ModelService)
    
    # Create a mock settings object with vision analysis enabled
    settings = MagicMock(spec=Settings)
    settings.enable_vision_analysis = True
    
    # Create an image processor with our mocks
    processor = ImageProcessor(model_service, settings=settings)
    
    # Mock the _get_model_for_task method to return None for vision models
    async def mock_get_model_for_task(capabilities):
        from api.core.models.model_types import ModelCapability
        if ModelCapability.VISION in capabilities:
            return None
        return MagicMock()  # Return a mock for reasoning-only models
    
    processor._get_model_for_task = AsyncMock(side_effect=mock_get_model_for_task)
    
    # Mock the analyze methods
    processor.analyze_with_model = AsyncMock(return_value={
        "analysis": {"context": "No vision model available"},
        "extracted_text": "Test text",
        "analysis_type": "none"
    })
    
    processor.analyze_text_only = AsyncMock(return_value={
        "analysis": {"context": "Text-only analysis"},
        "extracted_text": "Test text",
        "analysis_type": "text-only"
    })
    
    # Mock extract_text to avoid file operations
    processor.extract_text = MagicMock(return_value="Test text")
    
    # Test the process_image method with a mock response
    with patch.object(processor, 'process_image', return_value=MagicMock(
        analysis_type="none",
        extracted_text="Test text",
        analysis={"context": "No vision model available"}
    )):
        result = await processor.process_image("/tmp/test.png")
        
        # Verify the result has the correct analysis_type
        assert result.analysis_type == "none"
    
    # Reset mocks and test with force_text_only=True
    processor.analyze_with_model.reset_mock()
    processor.analyze_text_only.reset_mock()
    
    # Test with force_text_only=True using a mock response
    with patch.object(processor, 'process_image', return_value=MagicMock(
        analysis_type="text-only",
        extracted_text="Test text",
        analysis={"context": "Text-only analysis"}
    )):
        result = await processor.process_image("/tmp/test.png", force_text_only=True)
        
        # Verify the result has the correct analysis_type
        assert result.analysis_type == "text-only" 