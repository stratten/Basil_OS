import pytest
from pathlib import Path
import shutil
import os
from datetime import datetime
from PIL import Image
import pytesseract
from unittest.mock import AsyncMock, MagicMock

from api.services.window_capture.window_capture_service import WindowCaptureService
from api.services.window_capture.models import NoWindowError, CaptureFailedError
from api.core.services.file_storage_service import StorageService
from api.core.services.model_service import ModelService
from api.services.image_processing import ImageProcessor
from api.services.image_processing.image_models import ProcessingResponse
from api.core.models.model_types import ModelCapability

@pytest.fixture
def test_storage_dir(tmp_path: Path) -> Path:
    """Create a temporary storage directory for testing."""
    storage_dir = tmp_path / ".basil"
    storage_dir.mkdir(exist_ok=True)
    (storage_dir / "data" / "captures").mkdir(parents=True, exist_ok=True)
    (storage_dir / "data" / "temp").mkdir(parents=True, exist_ok=True)
    return storage_dir

@pytest.fixture
def storage_service(test_storage_dir: Path) -> StorageService:
    """Create a test instance of StorageService."""
    return StorageService(development_mode=True)

@pytest.fixture
def mock_model_service():
    """Create a mock model service."""
    return MagicMock(spec=ModelService)

@pytest.fixture
def mock_image_processor(mock_model_service):
    """Create a mock image processor."""
    processor = ImageProcessor(mock_model_service, None)
    processor.process_image = AsyncMock(return_value=ProcessingResponse(
        extracted_text="Test OCR text",
        analysis={},
        timestamp=datetime(2025, 1, 22, 18, 55, 12, 304413),
        app_name=None,
        window_title=None
    ))
    return processor

@pytest.fixture
def window_capture_service(mock_model_service: ModelService, mock_image_processor: ImageProcessor) -> WindowCaptureService:
    """Create a window capture service for testing."""
    service = WindowCaptureService(mock_model_service, mock_image_processor, test_mode=True)
    return service

@pytest.fixture
def sample_image(test_storage_dir: Path) -> Path:
    """Create a sample image with text for testing."""
    from PIL import Image, ImageDraw, ImageFont
    
    # Create a new image with white background
    img = Image.new('RGB', (800, 600), color='white')
    draw = ImageDraw.Draw(img)
    
    # Add some test text
    text = "This is a test image for OCR"
    draw.text((50, 50), text, fill='black')
    
    # Save the image
    img_path = test_storage_dir / "test_image.png"
    img.save(img_path)
    return img_path

@pytest.fixture
def mock_applescript():
    """Create a mock AppleScript that returns test data."""
    return """#!/usr/bin/osascript
tell application "System Events"
    return "%s|%s|%s"
end tell"""

@pytest.mark.asyncio
async def test_capture_temp_window_success(
    window_capture_service: WindowCaptureService,
    sample_image: Path,
    mock_applescript: str
):
    """Test successful temporary window capture with OCR processing."""
    # Mock the AppleScript execution by copying our sample image
    script_path = window_capture_service.storage.get_temp_path("capture_script.scpt")
    
    # Create a mock script that would normally capture the window
    with open(script_path, "w") as f:
        f.write(mock_applescript % ("TestApp", "Test Window", str(sample_image)))
    
    # Make script executable
    os.chmod(script_path, 0o755)
    
    try:
        # Perform the capture
        file_path, app_name, window_title, processing_result = await window_capture_service.capture_temp_window()
        
        # Verify basic capture info
        assert app_name == "TestApp"
        assert window_title == "Test Window"
        assert os.path.exists(file_path)
        assert isinstance(processing_result, dict)
        assert "extracted_text" in processing_result
        
    finally:
        # Cleanup
        if os.path.exists(file_path):
            os.remove(file_path)

@pytest.mark.asyncio
async def test_capture_active_window_success(
    window_capture_service: WindowCaptureService,
    sample_image: Path,
    mock_applescript: str
):
    """Test successful permanent window capture with OCR processing."""
    # Mock the AppleScript execution
    script_path = window_capture_service.storage.get_temp_path("capture_script.scpt")
    
    # Create a mock script
    with open(script_path, "w") as f:
        f.write(mock_applescript % ("TestApp", "Test Window", str(sample_image)))
    
    # Make script executable
    os.chmod(script_path, 0o755)
    
    try:
        # Perform the capture
        file_path, app_name, window_title, processing_result = await window_capture_service.capture_active_window()
        
        # Verify basic capture info
        assert app_name == "TestApp"
        assert window_title == "Test Window"
        assert os.path.exists(file_path)
        assert isinstance(processing_result, dict)
        assert "extracted_text" in processing_result
        
    finally:
        # Cleanup
        if os.path.exists(file_path):
            os.remove(file_path)

@pytest.mark.asyncio
async def test_capture_window_no_window(
    window_capture_service: WindowCaptureService,
    mock_applescript: str,
    monkeypatch,
):
    """Test window capture when no window is available."""
    script_path = window_capture_service.storage.get_temp_path("capture_script.scpt")
    
    # Create a mock script that returns no_capture
    with open(script_path, "w") as f:
        f.write(mock_applescript % ("TestApp", "No Window", "no_capture"))
    
    # Make script executable
    os.chmod(script_path, 0o755)
    monkeypatch.setattr(
        window_capture_service,
        "_fallback_full_screen_capture",
        AsyncMock(return_value=False),
    )
    
    with pytest.raises(NoWindowError) as exc_info:
        await window_capture_service.capture_temp_window()
    
    assert "No window available" in str(exc_info.value)
    assert exc_info.value.app_name == "TestApp"

@pytest.mark.asyncio
async def test_capture_window_error(
    window_capture_service: WindowCaptureService,
    mock_applescript: str
):
    """Test window capture when an error occurs."""
    script_path = window_capture_service.storage.get_temp_path("capture_script.scpt")
    
    # Create a mock script that returns an error
    with open(script_path, "w") as f:
        f.write(mock_applescript % ("TestApp", "Error Window", "error:Failed to capture window"))
    
    # Make script executable
    os.chmod(script_path, 0o755)
    
    with pytest.raises(CaptureFailedError) as exc_info:
        await window_capture_service.capture_temp_window()
    
    assert "Failed to capture window" in str(exc_info.value)
    assert exc_info.value.app_name == "TestApp" 