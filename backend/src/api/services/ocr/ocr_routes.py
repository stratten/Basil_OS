"""API routes for OCR text extraction."""

from fastapi import APIRouter, HTTPException, Depends, Body
from fastapi.responses import JSONResponse
from typing import Dict, Any
import logging
import os
import asyncio
import subprocess
from pathlib import Path
from datetime import datetime
from pydantic import BaseModel

from ...core.logging.api_logger import api_logger
from .ocr_service import OCRService
from .ocr_models import OCRResult
from ...core.services.file_storage_service import StorageService

# Configure router with properly named variable
ocr_router = APIRouter(prefix="/ocr", tags=["OCR"])

# Configure logging
logger = api_logger.getChild("ocr_routes")

# Initialize the OCR service
ocr_service = OCRService()
storage_service = StorageService()

# AppleScript for capturing the active window
CAPTURE_SCRIPT = """#!/usr/bin/osascript

tell application "System Events"
    -- Get frontmost process
    set frontProcess to first process whose frontmost is true
    set frontAppName to name of frontProcess
    
    -- Check if process has windows
    if (count of windows of frontProcess) is 0 then
        set logLine to "[INFO] No window for frontmost process"
        do shell script "echo " & quoted form of logLine & " >> /tmp/macos_capture_debug.log"
        return frontAppName & "|No Window|no_capture"
    end if
    
    -- Get window info
    set frontWindow to window 1 of frontProcess
    set winTitle to "Unknown"
    try
        set winTitle to name of frontWindow
    on error errMsg
        set logLine to "[INFO] Failed to get window title: " & errMsg
        do shell script "echo " & quoted form of logLine & " >> /tmp/macos_capture_debug.log"
    end try
    
    -- Replace pipe characters in window title to prevent parsing issues
    set AppleScript's text item delimiters to "|"
    set winTitleParts to every text item of winTitle
    set AppleScript's text item delimiters to "⎮"  -- Use a visually similar but different character
    set winTitle to winTitleParts as string
    set AppleScript's text item delimiters to ""  -- Reset delimiters
    
    -- Get window position and size
    try
        set windowPosition to position of frontWindow
        set windowSize to size of frontWindow
        
        set xPos to item 1 of windowPosition
        set yPos to item 2 of windowPosition
        set winWidth to item 1 of windowSize
        set winHeight to item 2 of windowSize
        
        set logLine to "[INFO] xPos: " & xPos
        do shell script "echo " & quoted form of logLine & " >> /tmp/macos_capture_debug.log"
        set logLine to "[INFO] yPos: " & yPos
        do shell script "echo " & quoted form of logLine & " >> /tmp/macos_capture_debug.log"
        set logLine to "[INFO] winWidth: " & winWidth
        do shell script "echo " & quoted form of logLine & " >> /tmp/macos_capture_debug.log"
        set logLine to "[INFO] winHeight: " & winHeight
        do shell script "echo " & quoted form of logLine & " >> /tmp/macos_capture_debug.log"
        
        set timestamp to do shell script "date +%Y%m%d_%H%M%S"
        set capturePath to "/tmp/capture_" & timestamp & ".png"
        set logLine to "[INFO] capturePath: " & capturePath
        do shell script "echo " & quoted form of logLine & " >> /tmp/macos_capture_debug.log"
        
        -- Use coordinates method - most reliable and non-interactive
        set captureCmd to "screencapture -x -R " & xPos & "," & yPos & "," & winWidth & "," & winHeight & " " & quoted form of capturePath
        set logLine to "[INFO] Capture instruction: " & captureCmd
        do shell script "echo " & quoted form of logLine & " >> /tmp/macos_capture_debug.log"
        try
            do shell script captureCmd
            delay 0.2
        on error captureErr
            set logLine to "[INFO] screencapture failed: " & captureErr
            do shell script "echo " & quoted form of logLine & " >> /tmp/macos_capture_debug.log"
            return frontAppName & "|" & winTitle & "|error: screencapture failed: " & captureErr
        end try
        
        -- Verify capture succeeded and has meaningful content
        set fileExists to do shell script "[ -f " & quoted form of capturePath & " ] && echo 'true' || echo 'false'"
        if fileExists is "true" then
            set fileSize to do shell script "/usr/bin/stat -f%z " & quoted form of capturePath
            set logLine to "[INFO] Capture file size: " & fileSize
            do shell script "echo " & quoted form of logLine & " >> /tmp/macos_capture_debug.log"
            -- No early return for small files; always return the capture path
            return frontAppName & "|" & winTitle & "|" & capturePath
        else
            set logLine to "[INFO] Capture file not found: " & capturePath
            do shell script "echo " & quoted form of logLine & " >> /tmp/macos_capture_debug.log"
            return frontAppName & "|" & winTitle & "|error: capture file not found"
        end if
    on error errMsg
        set logLine to "[INFO] Failed to get window position/size or capture: " & errMsg
        do shell script "echo " & quoted form of logLine & " >> /tmp/macos_capture_debug.log"
        return frontAppName & "|" & winTitle & "|error: window region capture failed: " & errMsg
    end try
end tell"""

# Request model
class OCRRequest(BaseModel):
    image_path: str

# Add new request model for file-based OCR
class OCRFileRequest(BaseModel):
    """Request model for OCR extraction from an existing file."""
    image_path: str
    app_name: str
    window_title: str

@ocr_router.post("/extract", response_model=OCRResult)
async def extract_text_from_image(request: OCRRequest = Body(...)) -> OCRResult:
    """Extract text from an image using OCR.
    
    Args:
        request: OCRRequest with image_path
        
    Returns:
        OCRResult containing the extracted text and metadata
    """
    image_path = request.image_path
    logger.info(f"OCR extract request received for image: {image_path}")
    
    # Validate the image path
    path = Path(image_path)
    if not path.exists():
        error_msg = f"Image file not found: {image_path}"
        logger.error(error_msg)
        raise HTTPException(status_code=404, detail=error_msg)
    
    try:
        # Perform OCR on the image
        result = ocr_service.extract_text(image_path)
        logger.info(f"OCR extraction completed with status: {result.status}")
        return result
        
    except Exception as e:
        error_msg = f"Error during OCR processing: {str(e)}"
        logger.error(error_msg)
        raise HTTPException(status_code=500, detail=error_msg)

@ocr_router.post("/capture", response_model=OCRResult)
async def capture_and_extract_text() -> OCRResult:
    """Capture the active window and extract text using OCR.
    
    Returns:
        OCRResult containing the extracted text, the image path, and metadata
    """
    logger.info("🔍 OCR capture request received - capturing screen and extracting text")
    
    try:
        # Create temporary script file
        script_path = storage_service.get_temp_path("capture_script.scpt")
        logger.info(f"📝 Creating AppleScript at: {script_path}")
        
        with open(script_path, "w") as f:
            f.write(CAPTURE_SCRIPT)
        
        # Make script executable
        os.chmod(script_path, 0o755)
        logger.info("🔧 AppleScript created and made executable")

        # Execute script using osascript
        logger.info("🖥️ Executing AppleScript for screen capture...")
        proc = await asyncio.create_subprocess_exec(
            "osascript", str(script_path), 
            stdout=subprocess.PIPE, 
            stderr=subprocess.PIPE
        )

        stdout, stderr = await proc.communicate()
        logger.info(f"📤 AppleScript execution completed with return code: {proc.returncode}")

        if proc.returncode != 0:
            error_msg = f"Capture failed: {stderr.decode()}"
            logger.error(f"❌ {error_msg}")
            raise HTTPException(status_code=500, detail=error_msg)

        # Parse output
        stdout_str = stdout.decode().strip()
        logger.info(f"📋 AppleScript output: {stdout_str}")
        
        app_name, window_title, temp_path = stdout_str.split("|")
        logger.info(f"🖼️ Parsed capture info:")
        logger.info(f"   - App: {app_name}")
        logger.info(f"   - Window: {window_title}")
        logger.info(f"   - Temp path: {temp_path}")

        # Handle error cases
        if temp_path.startswith("error:"):
            error_details = temp_path[6:]  # Remove "error:" prefix
            
            # Check for specific permission-related errors
            if "capture file not found" in error_details.lower():
                error_msg = "Screen recording permission required. The system was unable to capture the screen content. Please grant screen recording permission to Basil in System Settings > Privacy & Security > Screen Recording, then restart the application."
                logger.error(f"🔐 {error_msg}")
                raise HTTPException(status_code=403, detail=error_msg)
            elif "permission" in error_details.lower() or "authorization" in error_details.lower() or "denied" in error_details.lower():
                error_msg = f"Screen recording permission issue: {error_details}. Please grant screen recording permission to Basil in System Settings > Privacy & Security > Screen Recording, then restart the application."
                logger.error(f"🔐 {error_msg}")
                raise HTTPException(status_code=403, detail=error_msg)
            elif "screencapture failed" in error_details.lower():
                error_msg = f"Screen capture instruction failed: {error_details}. This may indicate a permission issue or system problem. Please check screen recording permissions in System Settings."
                logger.error(f"❌ {error_msg}")
                raise HTTPException(status_code=500, detail=error_msg)
            else:
                error_msg = f"AppleScript error: {error_details}"
                logger.error(f"❌ {error_msg}")
                raise HTTPException(status_code=500, detail=error_msg)
        elif temp_path == "no_capture":
            logger.warning(f"⚠️ No window available to capture for app: {app_name}, trying fallback full screen capture")
            # Fallback to full screen capture for apps with non-standard windows (wrappers, PWAs, etc.)
            fallback_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            fallback_path = f"/tmp/fallback_capture_{fallback_timestamp}.png"
            
            try:
                # Execute fallback full screen capture
                fallback_proc = await asyncio.create_subprocess_exec(
                    "screencapture", "-x", fallback_path,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE
                )
                _, fallback_stderr = await fallback_proc.communicate()
                
                if fallback_proc.returncode == 0 and os.path.exists(fallback_path):
                    temp_path = fallback_path
                    logger.info(f"✅ Fallback full screen capture successful for {app_name}")
                else:
                    error_msg = f"No window available to capture for app: {app_name} and fallback failed: {fallback_stderr.decode()}"
                    logger.error(f"❌ {error_msg}")
                    raise HTTPException(status_code=400, detail=error_msg)
            except Exception as e:
                error_msg = f"No window available to capture for app: {app_name} and fallback failed: {str(e)}"
                logger.error(f"❌ {error_msg}")
                raise HTTPException(status_code=400, detail=error_msg)

        # Check if capture file exists and get its size
        if not os.path.exists(temp_path):
            error_msg = f"Capture file not found at expected location: {temp_path}"
            logger.error(f"❌ {error_msg}")
            raise HTTPException(status_code=500, detail=error_msg)
        
        capture_size = os.path.getsize(temp_path)
        logger.info(f"📊 Capture file created: {capture_size} bytes ({capture_size/1024:.1f} KB)")
        
        # Analyze the capture to understand what happened
        if capture_size < 5000:
            logger.warning(f"⚠️ Small capture detected ({capture_size} bytes) - likely fell back to full screen in AppleScript")
        elif capture_size > 1000000:  # > 1MB
            logger.warning(f"⚠️ Large capture detected ({capture_size/1024/1024:.1f} MB) - likely full screen capture")
        else:
            logger.info(f"✅ Good capture size ({capture_size/1024:.1f} KB) - likely window capture")

        # Move to temp directory with proper naming
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        final_path = storage_service.get_temp_path(f"temp_capture_{timestamp}_{app_name}.png")

        os.rename(temp_path, final_path)
        logger.info(f"📁 Captured image moved to: {final_path}")
        
        # Perform OCR directly on the captured image
        logger.info("🔍 Starting OCR text extraction on captured image...")
        result = ocr_service.extract_text(str(final_path))
        logger.info(f"✅ OCR extraction completed with status: {result.status}")
        
        if result.status == "success":
            logger.info(f"📝 OCR Success Summary:")
            logger.info(f"   - Raw text length: {len(result.raw_text or '')} characters")
            logger.info(f"   - Processed text length: {len(result.processed_text or '')} characters")
            logger.info(f"   - Processing time: {result.processing_time_ms}ms")
            
            # Log a sample of the extracted text to see what we got
            if result.raw_text:
                sample_text = result.raw_text.replace('\n', ' ').strip()[:200]
                logger.info(f"📝 Text sample: {repr(sample_text)}")
        
        return result
        
    except Exception as e:
        error_msg = f"Error during capture and OCR processing: {str(e)}"
        logger.error(f"❌ {error_msg}")
        raise HTTPException(status_code=500, detail=error_msg)
    finally:
        # Clean up the script file
        if 'script_path' in locals() and os.path.exists(script_path):
            os.remove(script_path)
            logger.info("🧹 Cleaned up temporary AppleScript file") 

@ocr_router.post("/extract", response_model=OCRResult)
async def extract_text_from_file(request: OCRFileRequest) -> OCRResult:
    """Extract text from an existing image file using OCR.
    
    This endpoint accepts a file path (typically from Swift capture) and performs OCR
    without doing any screen capture itself. This eliminates the Python subprocess
    permission issues by separating capture from OCR processing.
    
    Args:
        request: OCRFileRequest containing image_path, app_name, and window_title
        
    Returns:
        OCRResult containing the extracted text, the image path, and metadata
    """
    logger.info(f"🔍 OCR file extraction request received for: {request.image_path}")
    logger.info(f"📱 App: {request.app_name}, Window: {request.window_title}")
    
    try:
        # Validate that the file exists
        if not os.path.exists(request.image_path):
            error_msg = f"Image file not found at path: {request.image_path}"
            logger.error(f"❌ {error_msg}")
            raise HTTPException(status_code=400, detail=error_msg)
        
        # Check file size to ensure it's not empty
        file_size = os.path.getsize(request.image_path)
        logger.info(f"📊 Processing image file: {file_size} bytes ({file_size/1024:.1f} KB)")
        
        if file_size == 0:
            error_msg = f"Image file is empty: {request.image_path}"
            logger.error(f"❌ {error_msg}")
            raise HTTPException(status_code=400, detail=error_msg)
        
        if file_size < 100:  # Very small files are likely not valid images
            logger.warning(f"⚠️ Very small image file ({file_size} bytes) - may not be valid")
        
        # Move to temp directory with proper naming (backend expects this pattern)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_app_name = request.app_name.replace(' ', '_').replace('/', '_')
        final_filename = f"swift_capture_{timestamp}_{safe_app_name}.png"
        final_path = storage_service.get_temp_path(final_filename)
        
        # Copy the file to our expected location (don't move original since Swift may need it)
        import shutil
        shutil.copy2(request.image_path, final_path)
        logger.info(f"📁 Copied image to processing location: {final_path}")
        
        # Perform OCR directly on the copied image
        logger.info("🔍 Starting OCR text extraction on provided image...")
        result = ocr_service.extract_text(str(final_path))
        logger.info(f"✅ OCR extraction completed with status: {result.status}")
        
        # Update the result to reflect the original capture info from Swift
        if result.status == "success":
            # Update metadata to include Swift capture information
            if not result.metadata:
                result.metadata = {}
            result.metadata["capture_source"] = "swift_windowcapture"
            result.metadata["original_app_name"] = request.app_name
            result.metadata["original_window_title"] = request.window_title
            result.metadata["original_image_path"] = request.image_path
            
            logger.info(f"📝 OCR Success Summary:")
            logger.info(f"   - Source: Swift WindowCaptureService")
            logger.info(f"   - App: {request.app_name}")
            logger.info(f"   - Window: {request.window_title}")
            logger.info(f"   - Raw text length: {len(result.raw_text or '')} characters")
            logger.info(f"   - Processed text length: {len(result.processed_text or '')} characters")
            logger.info(f"   - Processing time: {result.processing_time_ms}ms")
            
            # Log a sample of the extracted text
            if result.raw_text:
                sample_text = result.raw_text.replace('\n', ' ').strip()[:200]
                logger.info(f"📝 Text sample: {repr(sample_text)}")
        
        # Clean up the temporary copy (keep original for Swift)
        try:
            if os.path.exists(final_path):
                os.remove(final_path)
                logger.info("🧹 Cleaned up temporary processing file")
        except Exception as cleanup_error:
            logger.warning(f"⚠️ Could not clean up temporary file: {cleanup_error}")
        
        return result
        
    except HTTPException:
        # Re-raise HTTP exceptions as-is
        raise
    except Exception as e:
        error_msg = f"Error during file-based OCR processing: {str(e)}"
        logger.error(f"❌ {error_msg}")
        raise HTTPException(status_code=500, detail=error_msg) 