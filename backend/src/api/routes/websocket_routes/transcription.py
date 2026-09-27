import logging
import pyperclip
import os
import asyncio
from collections import OrderedDict
from hashlib import sha256
from pynput.keyboard import Key, Controller as KeyboardController
from fastapi import WebSocket
from typing import Any, Awaitable, Callable, Optional
from api.services.websocket_connection_manager import active_connections
from api.services.transcription.local_model.model_unload_scheduler import (
    cancel_model_unload,
    schedule_model_unload,
    unload_model_after_delay,
)
import traceback
from ...core.config.api_settings import settings
from ...core.services.model_service import ModelService, get_model_service
from ...services.transcription.backends.parakeet_components import (
    PARAKEET_PROGRESS_CALLBACK_CONTEXT_KEY,
    ParakeetTranscriptionProgress,
)
from ...services.transcription.output_text_replacements import (
    apply_text_replacements,
)

logger = logging.getLogger(__name__)
processed_transcription_audio_digests: OrderedDict[str, None] = OrderedDict()
maximum_processed_transcription_audio_digests = 128


def claim_transcription_audio(audio_data: bytes) -> bool:
    """Accept the same captured audio once across all connected desktop clients."""
    digest = sha256(audio_data).hexdigest()
    if digest in processed_transcription_audio_digests:
        logger.warning("Ignoring duplicate transcription audio payload: sha256=%s", digest)
        return False
    processed_transcription_audio_digests[digest] = None
    if len(processed_transcription_audio_digests) > maximum_processed_transcription_audio_digests:
        processed_transcription_audio_digests.popitem(last=False)
    return True


async def paste_transcribed_text(
    text: str,
    on_paste_dispatched: Optional[Callable[[], Awaitable[None]]] = None,
) -> None:
    """Paste text at current cursor position using system clipboard.
    Args:
        text: The text to paste
    """
    print("PRINT_DEBUG: Attempting to auto-paste transcribed text.")
    completion_callback_invoked = False
    original_clipboard: Any = None
    original_clipboard_captured = False
    clipboard_replaced = False
    restoration_finished = False

    async def publish_completion_once() -> None:
        nonlocal completion_callback_invoked
        if completion_callback_invoked or on_paste_dispatched is None:
            return
        completion_callback_invoked = True
        try:
            await on_paste_dispatched()
        except Exception as callback_error:
            logger.error(
                "Failed to publish transcription completion after paste dispatch: %s",
                callback_error,
            )

    try:
        print("PRINT_DEBUG: Storing original clipboard content (via pyperclip)...")
        original_clipboard = pyperclip.paste()
        original_clipboard_captured = True
        print(f"PRINT_DEBUG: Original clipboard content stored (type: {type(original_clipboard)}). Value: '{str(original_clipboard)[:50]}...'")

        print(f"PRINT_DEBUG: Setting new clipboard content (via pyperclip) (text: '{text[:50]}...').")
        pyperclip.copy(text)
        clipboard_replaced = True
        print("PRINT_DEBUG: New clipboard content set with transcribed text (via pyperclip).")

        # Verify pyperclip.copy by using pyperclip.paste() immediately
        current_pyperclip_content = pyperclip.paste()
        print(f"PRINT_DEBUG: Content after pyperclip.copy (verified by pyperclip.paste): '{str(current_pyperclip_content)[:50]}...'")
        if current_pyperclip_content == text:
            print("PRINT_DEBUG: pyperclip.copy seems to have worked as expected.")
        else:
            print("PRINT_DEBUG_WARN: pyperclip.copy did NOT set the clipboard content as expected when checked with pyperclip.paste().")

        print("PRINT_DEBUG: Simulating paste key press...")
        keyboard = KeyboardController()
        if os.name == 'posix':  # macOS or Linux
            print("PRINT_DEBUG: Simulating CMD+V for macOS/Linux.")
            keyboard.press(Key.cmd)
            keyboard.press('v')
            keyboard.release('v')
            keyboard.release(Key.cmd)
        elif os.name == 'nt':  # Windows
            print("PRINT_DEBUG: Simulating CTRL+V for Windows.")
            keyboard.press(Key.ctrl)
            keyboard.press('v')
            keyboard.release('v')
            keyboard.release(Key.ctrl)
        else: # Other OS (e.g. Linux X11)
            print("PRINT_DEBUG: Simulating CTRL+V for other OS (e.g. Linux X11).")
            keyboard.press(Key.ctrl)
            keyboard.press('v')
            keyboard.release('v')
            keyboard.release(Key.ctrl)
        print("PRINT_DEBUG: Paste key press simulated.")

        await publish_completion_once()
        print("PRINT_DEBUG: Adding 1.5 second clipboard restoration grace period...")
        await asyncio.sleep(1.5)
        print("PRINT_DEBUG: Delay finished.")

        current_clipboard = pyperclip.paste()
        if current_clipboard != text:
            print("PRINT_DEBUG: Clipboard changed after paste; preserving newer content.")
        elif original_clipboard is not None:
            print("PRINT_DEBUG: Restoring original clipboard content (via pyperclip)...")
            pyperclip.copy(original_clipboard)
            print("PRINT_DEBUG: Original clipboard content restored (via pyperclip).")
        else:
            print("PRINT_DEBUG: Original clipboard was None, nothing to restore.")
        restoration_finished = True
        
        print("PRINT_DEBUG: Auto-paste process completed successfully section.")
    except Exception as e:
        print(f"PRINT_DEBUG_ERROR: Error during auto-paste: {e}")
        print(f"PRINT_DEBUG_ERROR: Traceback: {traceback.format_exc()}")
    finally:
        await publish_completion_once()
        if clipboard_replaced and not restoration_finished:
            try:
                current_clipboard = pyperclip.paste()
                if (
                    current_clipboard == text
                    and original_clipboard_captured
                    and original_clipboard is not None
                ):
                    pyperclip.copy(original_clipboard)
                    print("PRINT_DEBUG: Restored original clipboard after paste error.")
            except Exception as restoration_error:
                logger.error(
                    "Failed to restore clipboard after paste error: %s",
                    restoration_error,
                )

async def send_transcription_status(event: str, data: Any = None):
    message = {
        "event": event,
        "data": data
    }
    logger.info(f"Sending transcription status: {message}")
    for connection in active_connections:
        try:
            await connection.send_json(message)
        except Exception as e:
            logger.error(f"Error sending status to client: {e}")

async def handle_init_transcription(websocket, transcription_service, send_transcription_status):
    logger = logging.getLogger(__name__)
    logger.info("\n=== Initializing Transcription ===")
    try:
        if not transcription_service.is_model_loaded():
            logger.info("Loading transcription model...")
            transcription_service.load_model()
            logger.info("Transcription model loaded successfully")
        else:
            logger.info("Transcription model already loaded")
        logger.info("Transcription model ready")
        await send_transcription_status("transcription_model_ready")
        logger.info("Sent model ready status to client")
        logger.info("=== Transcription Initialized ===\n")
    except Exception as e:
        logger.error(f"Error initializing transcription: {e}")
        await send_transcription_status("transcription_failed", str(e))

async def handle_initialize_transcription(websocket, transcription_service, send_transcription_status, cancel_model_unload, Preferences, msg_data):
    logger = logging.getLogger(__name__)
    logger.info("Initializing transcription model")
    # Cancel any scheduled unloads
    cancel_model_unload()
    # Load the transcription model
    transcription_service.load_model()
    # Notify clients that model is ready
    logger.info("Sending model_ready event")
    await send_transcription_status("model_ready")

async def handle_schedule_model_unload(websocket, msg_data, Preferences, schedule_model_unload):
    logger = logging.getLogger(__name__)
    preferences = Preferences.load()
    delay_seconds = msg_data.get("delay_seconds", preferences.transcription.model_unload_delay)
    logger.info(f"Scheduling model unload with {delay_seconds} seconds delay")
    schedule_model_unload(delay_seconds)

async def handle_cancel_model_unload(websocket, send_transcription_status, cancel_model_unload):
    logger = logging.getLogger(__name__)
    logger.info("Cancelling scheduled model unload")
    cancel_model_unload()
    await websocket.send_json({
        "status": "success",
        "message": "Model unload cancelled"
    })

async def handle_cancel_transcription(websocket, send_transcription_status):
    logger = logging.getLogger(__name__)
    logger.info("Received request to cancel transcription")
    await send_transcription_status("transcription_completed", "")
    logger.info("Transcription cancelled successfully")

async def handle_set_context_info(websocket, msg_data):
    logger = logging.getLogger(__name__)
    logger.info("Received context information (agent task or type)")
    websocket.scope["context_info"] = {
        "app_name": msg_data.get("app_name"),
        "window_title": msg_data.get("window_title"),
        "task_category": msg_data.get("task_category"),
        "flowContext": msg_data.get("flowContext"),
        "chunk_id": msg_data.get("chunk_id"),
    }
    logger.info(f"Stored context info: {websocket.scope['context_info']}")

async def handle_audio_transcription(websocket, message, transcription_service, send_transcription_status, paste_transcribed_text, Preferences):
    logger = logging.getLogger(__name__)
    # Handle binary audio data
    audio_data = message["bytes"]
    if not claim_transcription_audio(audio_data):
        return
    logger.info("\n=== Processing Audio Data ===")
    logger.info(f"Received audio data size: {len(audio_data)} bytes")
    try:
        # Notify client that we're starting transcription
        logger.info("Sending transcription_started event...")
        await send_transcription_status("transcription_started")
        # Ensure model is loaded (safety check)
        if not transcription_service.is_model_loaded():
            # Use the logger that's confirmed to be writing to the main API log
            main_api_logger = logging.getLogger("api.api.main")
            main_api_logger.info("Loading transcription model (audio processing)... (logged via 'api.api.main')")
            transcription_service.load_model()
            main_api_logger.info("Model loaded successfully (logged via 'api.api.main')")
        else:
            # Use the logger that's confirmed to be writing to the main API log
            main_api_logger = logging.getLogger("api.api.main")
            main_api_logger.info("Model already loaded (logged via 'api.api.main')")
        # Get context information if available
        context_info = dict(websocket.scope.get("context_info", {}) or {})
        logger.info(f"[DEBUG] context_info before transcription: {context_info}")
        if context_info:
            logger.info(f"Using context info: {context_info}")
        loop = asyncio.get_running_loop()

        def _broadcast_parakeet_progress(progress: ParakeetTranscriptionProgress) -> None:
            loop.call_soon_threadsafe(
                lambda: asyncio.create_task(
                    send_transcription_status(
                        "transcription_progress",
                        progress.to_payload(),
                    )
                )
            )

        context_info[PARAKEET_PROGRESS_CALLBACK_CONTEXT_KEY] = _broadcast_parakeet_progress
        # Process audio data with context
        logger.info("Starting audio transcription...")
        try:
            transcribed_text = await transcription_service.transcribe(audio_data, context_info)
            logger.info(f"Transcription completed successfully")
            logger.info(f"Transcribed text length: {len(transcribed_text)} characters")
            # Route based on presence of flowContext in the result
            if isinstance(transcribed_text, dict) and transcribed_text.get("flowContext"):
                logger.info("Routing transcription result to flow context UI only.")
                logger.info(f"[DEBUG] Transcribed text with flowContext that SKIPPED auto-paste: {transcribed_text}")
                await websocket.send_json({
                    "event": "flow_context_transcription_completed",
                    "data": transcribed_text
                })
                # Skip regular event/UI/DB updates
            else:
                # Use print for debug
                print(f"PRINT_DEBUG: Entered auto-paste decision block. Transcribed text type: {type(transcribed_text)}, value: '{str(transcribed_text)[:100]}...'")
                
                preferences = Preferences.load()
                logger.info(
                    "Loaded transcription preferences for auto-paste: "
                    "selected_model=%s auto_paste=%s auto_close_on_paste=%s",
                    preferences.models.transcription_model,
                    preferences.transcription.auto_paste,
                    preferences.transcription.auto_close_on_paste,
                )
                
                completion_published = False

                async def publish_completion() -> None:
                    nonlocal completion_published
                    if completion_published:
                        return
                    completion_published = True
                    logger.info("Sending transcription_completed event...")
                    await send_transcription_status(
                        "transcription_completed",
                        transcribed_text,
                    )

                if preferences.transcription.auto_paste:
                    print("PRINT_DEBUG: Auto-paste enabled, attempting to paste transcribed text...")
                    normalized_paste_text = apply_text_replacements(
                        transcribed_text,
                        preferences.transcription.text_replacements,
                    )
                    await paste_transcribed_text(
                        normalized_paste_text,
                        publish_completion,
                    )
                else:
                    print("PRINT_DEBUG: Auto-paste disabled, skipping paste operation.")
                    await publish_completion()
                logger.info("=== Audio Processing Complete ===\n")
        except Exception as e:
            # Check if this is a database error but transcription was successful
            if "no such table: transcriptions" in str(e) and hasattr(e, "__context__") and hasattr(e.__context__, "transcribed_text"):
                # We have the transcribed text despite the database error
                transcribed_text = e.__context__.transcribed_text
                logger.warning(f"Database error occurred but transcription was successful: {str(e)}")
                # Continue with the successful transcription
                preferences = Preferences.load()
                completion_published = False

                async def publish_completion_after_database_warning() -> None:
                    nonlocal completion_published
                    if completion_published:
                        return
                    completion_published = True
                    logger.info(
                        "Sending transcription_completed event despite database error..."
                    )
                    await send_transcription_status(
                        "transcription_completed",
                        transcribed_text,
                    )

                if preferences.transcription.auto_paste:
                    logger.info("Auto-paste enabled, attempting to paste transcribed text...")
                    normalized_paste_text = apply_text_replacements(
                        transcribed_text,
                        preferences.transcription.text_replacements,
                    )
                    await paste_transcribed_text(
                        normalized_paste_text,
                        publish_completion_after_database_warning,
                    )
                else:
                    await publish_completion_after_database_warning()
                logger.info("=== Audio Processing Complete (with database warning) ===\n")
            else:
                # This is a more serious error, re-raise
                raise
    except Exception as e:
        logger.error("\n=== Transcription Error ===")
        logger.error(f"Error type: {type(e).__name__}")
        logger.error(f"Error message: {str(e)}")
        logger.error("Traceback:")
        logger.error(traceback.format_exc())
        logger.error("=== End Error ===\n")
        await send_transcription_status("transcription_failed", str(e))

# Global variable to store the scheduled model unload task
model_unload_task: Optional[asyncio.Task] = None 