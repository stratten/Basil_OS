import pytest
import asyncio
from api.core.hotkey.handlers.audio_transcription_hotkey_handler import AudioTranscriptionHotkeyHandler
from api.core.models.preferences import Preferences

@pytest.fixture
def handler():
    """Create a test instance of the hotkey handler."""
    prefs = Preferences()
    loop = asyncio.new_event_loop()
    return AudioTranscriptionHotkeyHandler(prefs, loop)

@pytest.mark.asyncio
async def test_key_press_starts_recording(handler):
    """Test that key press starts recording when not already recording."""
    assert not handler._is_recording
    await handler.handle_key_press("F8")
    assert handler._is_recording

@pytest.mark.asyncio
async def test_key_press_stops_recording_if_active(handler):
    """Test that key press stops recording when already recording."""
    # Start recording
    await handler.handle_key_press("F8")
    assert handler._is_recording
    
    # Press again should stop
    await handler.handle_key_press("F8")
    assert not handler._is_recording

@pytest.mark.asyncio
async def test_key_release_stops_recording_on_tap(handler):
    """Test that key release stops recording if it was a tap."""
    # Start recording
    await handler.handle_key_press("F8")
    handler._key_press_time = 0  # Simulate immediate release
    await handler.handle_key_release("F8")
    assert not handler._is_recording

@pytest.mark.asyncio
async def test_key_release_maintains_recording_on_hold(handler):
    """Test that key release maintains recording if it was a hold."""
    # Start recording
    await handler.handle_key_press("F8")
    handler._key_press_time = 0  # Simulate long press
    import time
    time.sleep(1)  # Ensure we exceed HOLD_THRESHOLD
    await handler.handle_key_release("F8")
    assert handler._is_recording  # Should still be recording

def test_cleanup_stops_recording(handler):
    """Test that cleanup stops recording if active."""
    handler._is_recording = True
    handler.cleanup()
    assert not handler._is_recording 