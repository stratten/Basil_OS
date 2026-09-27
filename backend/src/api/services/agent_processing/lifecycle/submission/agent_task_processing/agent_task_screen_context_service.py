"""
AgentTask Screen Context Service

Handles screen context capture for agent tasks, including:
- Active application detection
- Screen capture via WebSocket
- OCR text extraction from screenshots
"""

import asyncio
import logging
import subprocess
from typing import Dict, Any
from pathlib import Path

logger = logging.getLogger(__name__)


class AgentTaskScreenContextService:
    """Service for capturing screen context (active app + OCR text) for agent tasks."""
    
    def __init__(self, websocket_manager=None, ocr_service=None):
        """
        Initialize screen context service.
        
        Args:
            websocket_manager: WebSocket manager for screen capture requests
            ocr_service: OCR service for text extraction
        """
        self.websocket_manager = websocket_manager
        self.ocr_service = ocr_service
        self.logger = logging.getLogger(__name__)
    
    def initialize_services(self, basil_services: Dict[str, Any]):
        """
        Initialize services from basil_services dict.
        
        Args:
            basil_services: Dictionary of available Basil services
        """
        if 'ocr' in basil_services:
            self.ocr_service = basil_services['ocr']
            self.logger.info("OCR service initialized")
    
    async def capture_screen_context(self, pre_captured_screenshot: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Capture current screen context (active app + OCR text).
        
        Args:
            pre_captured_screenshot: Optional pre-captured screenshot data from wake word detection
        
        Returns:
            Dictionary with screen context information
        """
        context = {
            'active_app': 'Unknown',
            'window_title': None,
            'screen_text': '',
            'screenshot_path': None,
            'capture_success': False
        }
        
        try:
            # Check if we have pre-captured screenshot data to use
            if pre_captured_screenshot and pre_captured_screenshot.get('success') and pre_captured_screenshot.get('image_path'):
                self.logger.info("📸 Using pre-captured screenshot from wake word detection")
                
                # Use app name and window title from pre-captured screenshot
                context['active_app'] = pre_captured_screenshot.get('app_name', 'Unknown')
                context['window_title'] = pre_captured_screenshot.get('window_title')
                context['screenshot_path'] = pre_captured_screenshot.get('image_path')
                
                # Extract text from the pre-captured image using OCR
                capture_result = await self._extract_text_from_image(pre_captured_screenshot['image_path'])
                
                if capture_result['success']:
                    context['screen_text'] = capture_result['text']
                    context['capture_success'] = True
                    self.logger.info(f"✅ Pre-captured screenshot OCR successful: {len(context['screen_text'])} characters")
                    self.logger.debug(f"📱 Using pre-captured app context: {context['active_app']}")
                else:
                    self.logger.warning(f"⚠️ Failed to extract text from pre-captured image: {capture_result.get('error')}")
                    
            else:
                # No pre-captured screenshot or it failed - fall back to live capture
                if pre_captured_screenshot:
                    self.logger.warning(f"⚠️ Pre-captured screenshot not usable: success={pre_captured_screenshot.get('success')}, has_path={bool(pre_captured_screenshot.get('image_path'))}")
                    self.logger.info("📸 Falling back to live screen capture")
                else:
                    self.logger.debug("📸 No pre-captured screenshot available, performing live capture")
                
                # Step 1: Request capture via WebSocket to get image path
                capture_response = await self._request_websocket_capture()
                
                if capture_response.get('success') and capture_response.get('image_path'):
                    # Step 2: OCR the captured image
                    app_name = capture_response.get('app_name', 'Unknown')
                    window_title = capture_response.get('window_title', 'Unknown')
                    context['active_app'] = app_name
                    context['window_title'] = window_title
                    context['screenshot_path'] = capture_response['image_path']
                    
                    ocr_result = await self._extract_text_from_image_with_metadata(
                        capture_response['image_path'], app_name, window_title
                    )
                    
                    if ocr_result['success']:
                        context['screen_text'] = ocr_result['text']
                        context['capture_success'] = True
                        self.logger.debug(f"✅ Fallback capture+OCR successful: {len(context['screen_text'])} characters")
                    else:
                        self.logger.warning(f"❌ Fallback OCR failed: {ocr_result.get('error', 'Unknown error')}")
                        # Still try to get active app name as fallback
                        active_app = await self._get_active_application()
                        context['active_app'] = active_app
                else:
                    self.logger.warning(f"❌ Fallback capture failed: {capture_response.get('error', 'Unknown error')}")
                    # Still try to get active app name as fallback
                    active_app = await self._get_active_application()
                    context['active_app'] = active_app
            
        except Exception as e:
            self.logger.error(f"Error capturing screen context: {e}")
            # Continue with empty context rather than failing
        
        return context
    
    async def _get_active_application(self) -> str:
        """
        Get the name of the currently active application.
        
        Returns:
            Name of active application
        """
        try:
            # Use macOS-specific method to get active app
            result = subprocess.run([
                'osascript', '-e', 
                'tell application "System Events" to get name of first application process whose frontmost is true'
            ], capture_output=True, text=True, timeout=5)
            
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception as e:
            self.logger.error(f"Error getting active application: {e}")
        
        return "Unknown"
    
    async def _request_websocket_capture(self) -> Dict[str, Any]:
        """
        Request capture via WebSocket to get image path and metadata.
        
        Returns:
            Dictionary with capture response: {success, image_path, app_name, window_title}
        """
        try:
            from api.core.config.api_settings import settings
            import httpx
            import uuid
            
            # Generate unique request ID for this capture
            request_id = str(uuid.uuid4())
            
            self.logger.debug(f"🔄 Triggering WebSocket capture request: {request_id}")
            
            # Trigger WebSocket capture by calling our new endpoint
            base_url = f"http://{settings.HOST}:{settings.PORT}"
            
            async with httpx.AsyncClient(timeout=10.0) as client:
                # Call the WebSocket capture endpoint that requests capture from frontend
                response = await client.post(f"{base_url}/capture/swift-window-immediate")
                
                if response.status_code == 200:
                    capture_data = response.json()
                    
                    if capture_data.get('success') and capture_data.get('image_path'):
                        self.logger.debug(f"✅ WebSocket capture successful: {capture_data['image_path']}")
                        
                        app_name = capture_data.get('app_name', 'Unknown')
                        window_title = capture_data.get('window_title', 'Unknown')
                        
                        return {
                            'success': True,
                            'image_path': capture_data['image_path'],
                            'app_name': app_name,
                            'window_title': window_title
                        }
                    else:
                        error_msg = capture_data.get('error', 'WebSocket capture failed')
                        self.logger.warning(f"❌ WebSocket capture failed: {error_msg}")
                        return {
                            'success': False,
                            'error': f"WebSocket capture failed: {error_msg}",
                            'image_path': ''
                        }
                else:
                    error_msg = f"WebSocket capture endpoint returned {response.status_code}"
                    self.logger.warning(f"❌ {error_msg}")
                    return {
                        'success': False,
                        'error': error_msg,
                        'image_path': ''
                    }
            
        except Exception as e:
            self.logger.error(f"❌ WebSocket capture failed: {e}")
            return {
                'success': False,
                'error': str(e),
                'image_path': ''
            }
    
    async def _extract_text_from_image(self, image_path: str) -> Dict[str, Any]:
        """
        Extract text from a pre-captured image file using OCR.
        
        Args:
            image_path: Path to the image file to process
            
        Returns:
            Dictionary with OCR results
        """
        # Try to extract app name from image file name, fallback to Unknown
        image_filename = Path(image_path).name
        app_name = "Unknown"
        if "_" in image_filename:
            parts = image_filename.split("_")
            if len(parts) >= 3:
                app_name = parts[-1].replace(".png", "").replace(".jpg", "").replace(".jpeg", "")
        
        return await self._extract_text_from_image_with_metadata(image_path, app_name, "Unknown")
    
    async def _extract_text_from_image_with_metadata(self, image_path: str, app_name: str, window_title: str) -> Dict[str, Any]:
        """
        Extract text from captured image using OCR service with metadata preservation.
        
        Args:
            image_path: Path to the captured image
            app_name: Name of the active application
            window_title: Title of the active window
            
        Returns:
            Dictionary with extracted text and metadata
        """
        try:
            # Actually perform OCR using the OCR service
            if self.ocr_service:
                self.logger.debug(f"🔍 Performing OCR on image: {image_path}")
                ocr_result_obj = await asyncio.to_thread(self.ocr_service.extract_text, image_path)
                
                # Convert OCRResult object to dictionary format
                if ocr_result_obj.status == "success":
                    return {
                        "success": True,
                        "text": ocr_result_obj.processed_text or ocr_result_obj.cleaned_text or ocr_result_obj.raw_text or "",
                        "raw_text": ocr_result_obj.raw_text or "",
                        "processed_text": ocr_result_obj.processed_text or "",
                        "processing_time_ms": ocr_result_obj.processing_time_ms or 0
                    }
                else:
                    return {
                        "success": False,
                        "error": f"OCR failed with status: {ocr_result_obj.status}",
                        "text": ""
                    }
            else:
                self.logger.warning("⚠️ OCR service not available")
                return {
                    "success": False,
                    "error": "OCR service not initialized",
                    "text": ""
                }
        except Exception as e:
            self.logger.error(f"❌ OCR extraction failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "text": ""
            }

