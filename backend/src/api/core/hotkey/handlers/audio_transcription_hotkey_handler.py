"""Hotkey handler for audio transcription operations."""

import logging
from typing import Optional
import time
import asyncio

from api.core.hotkey.handlers.base_hotkey_handler import BaseHotkeyHandler
from api.core.models.preferences import Preferences
from api.services.websocket_events import send_transcription_status

logger = logging.getLogger(__name__)

class AudioTranscriptionHotkeyHandler(BaseHotkeyHandler):
    """Handles hotkey events for audio recording and transcription operations."""

    # Constants
    HOLD_THRESHOLD = 0.6  # seconds to consider a press a hold

    def __init__(self, preferences: Preferences, event_loop: asyncio.AbstractEventLoop):
        """Initialize the audio transcription hotkey handler.
        
        Args:
            preferences: Application preferences containing hotkey bindings
            event_loop: The asyncio event loop to use for async operations
        """
        super().__init__(preferences, event_loop)
        # Legacy attribute kept for backwards-compatibility with tests that poke it directly
        self._key_press_time: Optional[float] = None
        # Internal monotonic timestamp for press start used for accurate tap/hold detection
        self._press_started_at: Optional[float] = None
        self._is_recording = False

    async def handle_key_press(self, key: str) -> None:
        """Handle transcription key press event."""
        logger.info("Transcription hotkey pressed")
        now = time.time()
        self._key_press_time = now
        self._press_started_at = now
        
        # If already recording, stop it
        if self._is_recording:
            await self._stop_recording()
        else:
            # Start recording
            await self._start_recording()

    async def handle_key_release(self, key: str) -> None:
        """Handle transcription key release event."""
        logger.info("Transcription hotkey released")
        # Use internal press start timestamp for robust duration calculation
        if self._press_started_at is None:
            return

        press_duration = time.time() - self._press_started_at
        # Clear timestamps
        self._press_started_at = None
        self._key_press_time = None
        
        # If we're recording and it was a tap (not a hold), stop recording
        if self._is_recording and press_duration < self.HOLD_THRESHOLD:
            await self._stop_recording()

    async def _start_recording(self) -> None:
        """Start recording audio."""
        logger.info("Starting audio recording")
        self._is_recording = True
        await send_transcription_status("recording_started")

    async def _stop_recording(self) -> None:
        """Stop recording audio."""
        logger.info("Stopping audio recording")
        self._is_recording = False
        await send_transcription_status("recording_stopped")

    def cleanup(self) -> None:
        """Clean up resources."""
        if self._is_recording:
            self._is_recording = False 