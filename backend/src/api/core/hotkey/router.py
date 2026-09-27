"""Global hotkey processor service with FastAPI integration."""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum, auto
from typing import Optional, Set, Dict, Any, Union, Callable
import asyncio
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, Body
from pydantic import BaseModel

from api.core.models.preferences import Preferences, HotkeyBinding
from api.services.window_capture.window_capture_service import WindowCaptureService
from api.services.image_processing import ImageProcessor
from api.dependencies import get_sqlite_knowledge_service
from api.core.services.file_storage_service import StorageService
from api.core.knowledge.query.activity_query_processor import ActivityQueryProcessor
from api.core.knowledge.query.query_intent_handler import QueryIntentHandler
from api.core.services.model_service import get_model_service
from api.services.websocket_events import send_history_chat_event
from api.core.hotkey.handlers.base_hotkey_handler import BaseHotkeyHandler

logger = logging.getLogger(__name__)

class OperationResponse(BaseModel):
    """Response model for hotkey operations."""
    operation: str
    status: str
    details: Optional[str] = None

class HotkeyRouter:
    """Router for handling global hotkey events."""
    
    def __init__(self, llm_service: Optional[Any] = None) -> None:
        """Initialize the hotkey router with routes and handlers."""
        self.router = APIRouter(prefix="/hotkeys", tags=["hotkeys"])
        self.preferences = Preferences.load()
        self._init_services()
        self._init_state()
        self._init_handlers()
        self._init_routes()
        
    def _init_routes(self) -> None:
        """Initialize API routes for hotkeys."""
        
        @self.router.post("/transcribe")
        async def handle_transcription() -> OperationResponse:
            """Handle audio transcription hotkey event."""
            try:
                await self.transcription_handler.handle_key_press("TRANSCRIBE")
                return OperationResponse(
                    operation="transcribe",
                    status="started",
                    details="Started audio transcription"
                )
            except Exception as e:
                logger.error(f"Transcription error: {e}")
                raise HTTPException(status_code=500, detail=str(e))
        
        @self.router.post("/transcribe/stop")
        async def stop_transcription() -> OperationResponse:
            """Handle stop transcription hotkey event."""
            try:
                await self.transcription_handler.handle_key_press("STOP")
                return OperationResponse(
                    operation="transcribe",
                    status="stopped",
                    details="Stopped audio transcription"
                )
            except Exception as e:
                logger.error(f"Transcription stop error: {e}")
                raise HTTPException(status_code=500, detail=str(e))
                
        @self.router.post("/capture")
        async def handle_capture() -> OperationResponse:
            """Handle screen capture hotkey event."""
            try:
                await self.capture_handler.handle_key_press("CAPTURE")
                return OperationResponse(
                    operation="capture",
                    status="started",
                    details="Capturing screen"
                )
            except Exception as e:
                logger.error(f"Capture error: {e}")
                raise HTTPException(status_code=500, detail=str(e))
        
        @self.router.post("/conversation")
        async def handle_conversation() -> OperationResponse:
            """Handle conversation hotkey event.
            
            This endpoint toggles the conversation UI.
            """
            try:
                await self.conversation_handler.handle_key_press("CONVERSE")
                return OperationResponse(
                    operation="conversation",
                    status="started",
                    details="Started conversation"
                )
            except Exception as e:
                logger.error(f"Conversation error: {e}")
                raise HTTPException(status_code=500, detail=str(e))
        
        @self.router.get("/bindings")
        async def get_bindings() -> Dict[str, Any]:
            """Get current hotkey bindings."""
            try:
                # Load fresh preferences to ensure we have the latest
                self.preferences = Preferences.load()
                return {
                    "transcribe_audio": self.preferences.hotkeys.transcribe_audio.dict(),
                    "capture_screen": self.preferences.hotkeys.capture_screen.dict(),
                    "conversation_toggle": self.preferences.hotkeys.conversation_toggle.dict(),
                    "insert_assistant_output": self.preferences.hotkeys.insert_assistant_output.dict(),
                    "streaming_transcription": self.preferences.hotkeys.streaming_transcription.dict(),
                    "assistant_session": self.preferences.hotkeys.assistant_session.dict(),
                }
            except Exception as e:
                logger.error(f"Error getting bindings: {e}")
                raise HTTPException(status_code=500, detail=str(e))
                
        @self.router.put("/bindings/{operation}")
        async def update_binding(operation: str, binding: HotkeyBinding) -> Dict[str, Any]:
            """Update a hotkey binding."""
            try:
                # Load fresh preferences
                self.preferences = Preferences.load()
                
                # Update the specified binding
                if hasattr(self.preferences.hotkeys, operation):
                    setattr(self.preferences.hotkeys, operation, binding)
                    self.preferences.save()
                    return {"status": "success", "message": f"Updated binding for {operation}"}
                else:
                    raise HTTPException(status_code=404, detail=f"Invalid operation: {operation}")
            except Exception as e:
                logger.error(f"Error updating binding: {e}")
                raise HTTPException(status_code=500, detail=str(e))
        
    def _init_services(self) -> None:
        """Initialize services used by hotkey handlers."""
        # Get model service first
        model_service = get_model_service()
        
        # Initialize services in the right order
        self.storage = StorageService()
        self.image_processor = ImageProcessor(model_service, self.storage)
        self.capture_service = WindowCaptureService(model_service, self.image_processor)
        self.knowledge_base = get_sqlite_knowledge_service()
        self.query_processor = ActivityQueryProcessor(
            knowledge_base=self.knowledge_base
        )
        self.intent_handler = QueryIntentHandler(
            self.query_processor,
            self.image_processor,
        )
        
    def _init_state(self) -> None:
        """Initialize state variables."""
        self.event_loop = asyncio.get_event_loop()
        
    def _init_handlers(self) -> None:
        """Initialize hotkey handlers."""
        # These are placeholders for actual handler implementations
        self.transcription_handler = BaseHotkeyHandler(self.preferences, self.event_loop)
        self.capture_handler = BaseHotkeyHandler(self.preferences, self.event_loop)
        self.suggestion_handler = BaseHotkeyHandler(self.preferences, self.event_loop)
        self.conversation_handler = BaseHotkeyHandler(self.preferences, self.event_loop)
        
        # Connect transcription handler to audio capture
        # Since we don't have actual PyQt signals/slots in FastAPI,
        # these are just placeholders for conceptual signal connections
        # In a real app, we would configure signal/slot connections here
        
        # Handle transcription start/stop
        self.transcription_handler.handle_key_press = self._handle_transcription_key_press
        
        # Handle screen capture
        self.capture_handler.handle_key_press = self._handle_capture_key_press
        
        # Handle suggestion generation
        self.suggestion_handler.handle_key_press = self._handle_suggestion_key_press
        
        # Handle conversation
        self.conversation_handler.handle_key_press = self._handle_conversation_key_press
            
    async def _handle_transcription_key_press(self, key: str) -> None:
        """Handle transcription key press."""
        if key == "TRANSCRIBE":
            # Start recording and transcription
            print(f"Starting transcription at {datetime.now()}")
        elif key == "STOP":
            # Stop recording and process transcription
            print(f"Stopping transcription at {datetime.now()}")
    
    async def _handle_capture_key_press(self, key: str) -> None:
        """Handle capture key press."""
        if key == "CAPTURE":
            # Capture screen
            print(f"Capturing screen at {datetime.now()}")
            
            # Mock capture result
            capture_result = {}
            
            # Process captured image
            await self.intent_handler.process_capture(capture_result)
    
    async def _handle_suggestion_key_press(self, key: str) -> None:
        """Handle suggestion key press."""
        if key == "SUGGEST":
            # Generate suggestions
            print(f"Generating suggestions at {datetime.now()}")
            
            # Mock suggestion input
            suggestion_input = "placeholder"
            
            # Generate suggestions
            suggestions = await self.intent_handler.generate_suggestions(suggestion_input)
            
            # Return or display suggestions
            print(f"Generated suggestions: {suggestions}")
    
    async def _handle_conversation_key_press(self, key: str) -> None:
        """Handle conversation key press."""
        if key == "CONVERSE":
            # Toggle conversation mode
            import time
            import uuid
            
            logger.info(f"Toggling conversation mode at {datetime.now()}")
            
            # Send event to toggle conversation UI
            await send_history_chat_event(True, None)
            
            # Note: The actual query processing will be handled by the websocket route
            # when the user sends a message through the conversation UI
    
    async def cleanup(self) -> None:
        """Clean up resources used by the router."""
        # Clean up handlers
        self.transcription_handler.cleanup()
        self.capture_handler.cleanup()
        self.suggestion_handler.cleanup()
        self.conversation_handler.cleanup()
        
        # Clean up services
        if hasattr(self.knowledge_base, "cleanup"):
            await self.knowledge_base.cleanup() 