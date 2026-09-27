"""
Whisper Live transcription service for advanced real-time audio processing.

This service implements enhanced transcription capabilities using faster-whisper
for improved buffer management and segment stitching.
"""

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
import asyncio
import json
import logging
import math
import time
import os
from pathlib import Path
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)
TERMINATION_CONTROL_SUBSTRINGS = (
    "close",
    "terminate",
    "kill_process",
    "force_terminate",
)


def apply_native_stream_timing_control(text_data: str, audio_processor: Any) -> bool:
    """Apply a validated native capture offset from one socket control message."""
    try:
        payload = json.loads(text_data)
    except json.JSONDecodeError:
        return False
    if not isinstance(payload, dict) or payload.get("type") != "native_stream_timing":
        return False

    offset_seconds = payload.get("stream_offset_seconds")
    if (
        isinstance(offset_seconds, bool)
        or not isinstance(offset_seconds, (int, float))
        or not math.isfinite(offset_seconds)
        or not 0.0 <= offset_seconds <= 24 * 60 * 60
    ):
        return False

    audio_processor.set_native_stream_offset_seconds(float(offset_seconds))
    return True


def is_legacy_termination_control(text_data: str) -> bool:
    """Return whether a legacy text control closes the WebSocket session."""
    return any(command in text_data for command in TERMINATION_CONTROL_SUBSTRINGS)


class WhisperLiveService:
    """
    Service for integrating WhisperLive transcription within Basil.
    
    This class manages the initialization, routing, and lifecycle of the
    WhisperLive functionality within the main application.
    """
    
    def __init__(self):
        # Core components
        self.kit = None
        
        # State management
        self.is_initialized = False
        self.last_initialize_error: Optional[str] = None
        self.last_initialize_at: Optional[float] = None
        self.active_websockets = set()
        self.active_processors = {}
        
        # Configuration
        self.base_path = "/whisper-live"
        self.config = {}
        
        # Web interface
        self.web_dir = Path(__file__).parent / "web"
        
        # App reference
        self.app = None
    
    async def register_with_app(self, app: FastAPI, **config):
        """
        Register the service with the FastAPI application without initializing the model.
        
        Args:
            app: FastAPI application to add routes to
            **config: Configuration options for WhisperLiveKit (saved for later use)
            
        Returns:
            bool: Success or failure
        """
        self.app = app
        self.config = config
        
        try:
            # Add routes to the FastAPI app
            self._add_routes(app)
            
            logger.info("WhisperLive service registered with the application")
            return True
        except Exception as e:
            logger.error(f"Failed to register WhisperLive service: {e}", exc_info=True)
            return False
    
    async def initialize(self):
        """
        Initialize the TranscriptionEngine with the saved configuration.d
        This is called when needed, not at app startup.
        
        Returns:
            bool: Success or failure
        """
        if self.is_initialized:
            logger.info("WhisperLive service already initialized")
            return True
            
        try:
            # Import from upstream core
            from api.services.whisper_live_core import TranscriptionEngine
            from .config_mapper import map_basil_config_to_upstream
            
            # Map our config to upstream format
            upstream_config = map_basil_config_to_upstream(self.config)
            
            logger.info(f"Initializing TranscriptionEngine with config: backend_policy={upstream_config.get('backend_policy')}, "
                       f"model={upstream_config.get('model_size')}, diarization={upstream_config.get('diarization')}")
            
            # Initialize engine with mapped configuration. Build it OFF the event
            # loop: TranscriptionEngine.__init__ synchronously loads Whisper
            # checkpoint(s) (multi-second), and doing that on the loop would stall
            # uvicorn's keepalive ping for any already-open socket and get it
            # closed with a 1011 timeout. (__init__ creates no asyncio objects, so
            # constructing it in a worker thread is safe.)
            self.kit = await asyncio.to_thread(lambda: TranscriptionEngine(**upstream_config))
            
            # Update state
            self.is_initialized = True
            self.last_initialize_error = None
            self.last_initialize_at = time.time()
            logger.info("WhisperLive service initialized successfully with upstream TranscriptionEngine")
            return True
        except Exception as e:
            self.is_initialized = False
            self.kit = None
            self.last_initialize_error = f"{type(e).__name__}: {e}"
            logger.error(f"Failed to initialize WhisperLive service: {e}", exc_info=True)
            return False
    
    def _add_routes(self, app: FastAPI):
        """Add WhisperLive routes to the FastAPI application."""
        
        # Web interface endpoint
        @app.get(f"{self.base_path}")
        async def get_whisper_interface():
            # Lazy initialize if necessary
            if not self.is_initialized:
                await self.initialize()
                
            if not self.is_initialized or not self.kit:
                return HTMLResponse("WhisperLive service not yet initialized")
            
            # Serve our own web interface HTML
            html_file = self.web_dir / "live_transcription.html"
            if html_file.exists():
                return HTMLResponse(html_file.read_text())
            else:
                return HTMLResponse("<html><body><h1>WhisperLive Service</h1><p>Running</p></body></html>")
        
        # Pre-initialization endpoint (called when widget opens, before recording starts)
        @app.post(f"{self.base_path}/initialize")
        async def preinitialize_models():
            """
            Pre-initialize models in the background.
            Called when the Live Transcription widget opens, giving models time to load
            while the user fills out the meeting form.
            """
            if not self.is_initialized:
                logger.info("Pre-initialization requested - loading models in background...")
                success = await self.initialize()
                response = {
                    "status": "initialized" if success else "failed",
                    "is_initialized": self.is_initialized,
                    "last_initialize_error": self.last_initialize_error,
                }
                if self.last_initialize_at is not None:
                    response["last_initialize_at"] = self.last_initialize_at
                return response
            else:
                response = {"status": "already_initialized", "is_initialized": True}
                if self.last_initialize_at is not None:
                    response["last_initialize_at"] = self.last_initialize_at
                return response
        
        # WebSocket endpoint for audio processing
        @app.websocket(f"{self.base_path}/asr")
        async def whisper_live_websocket(websocket: WebSocket):
            await self._handle_websocket(websocket)
        
        logger.info(f"WhisperLive routes added at {self.base_path}")
    
    async def _handle_websocket(self, websocket: WebSocket):
        """Handle a WebSocket connection for audio processing."""
        # Lazy initialize if necessary
        if not self.is_initialized:
            await self.initialize()
            
        if not self.is_initialized:
            if self.last_initialize_error:
                logger.warning(
                    f"WhisperLive WebSocket refused; init failed with: {self.last_initialize_error}"
                )
            await websocket.close(code=1000, reason="Service not initialized")
            return
            
        # Get client type from query parameters
        params = websocket.query_params
        is_pcm = params.get("client") == "native"
        input_format = "pcm" if is_pcm else "webm"
        
        # Get meeting info from query parameters (optional - for recording)
        meeting_id = params.get("meeting_id")
        meeting_name = params.get("meeting_name")
        meeting_purpose = params.get("meeting_purpose")
        meeting_participants = params.get("meeting_participants")  # Comma-separated list
        audio_source = params.get("audio_source")  # e.g., "Zoom", "Teams", "Microphone"
        session_id = params.get("session_id")  # Shared id linking mic + system-audio members of one meeting
        # Set by the client when an in-progress socket auto-reconnects after a
        # drop. Tells the recorder to append to the existing part rather than
        # refuse (id collision guard) or truncate it.
        is_reconnect = (params.get("reconnect") or "").lower() == "true"
        
        # Resume continuation context. Defaults make a normal fresh recording; a
        # resumed part carries a timeline offset and ordering so its transcript
        # lands on the logical meeting timeline (see MeetingRecorder).
        recording_mode = params.get("recording_mode") or "fresh"
        resumed_from_meeting_id = params.get("resumed_from_meeting_id")
        try:
            timeline_offset_seconds = float(params.get("timeline_offset_seconds") or 0.0)
        except (TypeError, ValueError):
            timeline_offset_seconds = 0.0
        try:
            recording_part_index = int(params.get("recording_part_index") or 0)
        except (TypeError, ValueError):
            recording_part_index = 0
        
        logger.info(
            f"Creating AudioProcessor for {input_format} input (pcm={is_pcm}), "
            f"audio_source={audio_source or 'Microphone'}, recording_mode={recording_mode}, "
            f"timeline_offset_seconds={timeline_offset_seconds}, recording_part_index={recording_part_index}"
        )
        
        # Create meeting recorder if meeting info provided
        meeting_recorder = None
        if meeting_id and meeting_name:
            from api.services.meetings.meeting_recorder import MeetingRecorder
            meeting_recorder = MeetingRecorder(
                meeting_id=meeting_id,
                audio_source=audio_source,
                session_id=session_id,
                timeline_offset_seconds=timeline_offset_seconds,
                recording_part_index=recording_part_index,
                resumed_from_meeting_id=resumed_from_meeting_id
            )
            
            # Parse participants list
            participants = []
            if meeting_participants:
                participants = [p.strip() for p in meeting_participants.split(",") if p.strip()]
            
            # Start recording (append to the in-progress part on auto-reconnect)
            meeting_recorder.start_recording(
                meeting_name=meeting_name,
                purpose=meeting_purpose,
                participants=participants,
                resume_existing=is_reconnect,
            )
            logger.info(
                f"Started meeting recording: {meeting_id} - {meeting_name}, "
                f"source={audio_source or 'Microphone'}, reconnect={is_reconnect}"
            )
            
        # Guarantee a model is ready before the synchronous AudioProcessor
        # constructor pops one. Loading runs in a worker thread so a cold pool
        # cannot block the event loop and starve sibling WebSocket keepalives.
        asr = getattr(self.kit, "asr", None)
        if asr is not None and hasattr(asr, "ensure_model_ready"):
            await asyncio.to_thread(asr.ensure_model_ready)

        # Create audio processor with the transcription engine and optional meeting recorder.
        # audio_source is threaded through so the per-stream diagnostics (PCM/VAD
        # logs, StreamCommitWatchdog) are tagged Microphone vs System Audio instead
        # of "unknown".
        from api.services.whisper_live_core import AudioProcessor
        audio_processor = AudioProcessor(
            transcription_engine=self.kit,
            input_format=input_format,
            meeting_recorder=meeting_recorder,
            audio_source=audio_source,
        )

        # Refill the preloaded model pool in the background so the NEXT connection
        # (the sibling source, or an auto-reconnect) pops a ready model instead of
        # loading a checkpoint synchronously on the event loop. Guarded so it only
        # runs for the simulstreaming backend that exposes the pool.
        if asr is not None and hasattr(asr, "new_model_to_stack"):
            asyncio.create_task(asyncio.to_thread(asr.new_model_to_stack))

        # Track this connection
        await websocket.accept()
        self.active_websockets.add(websocket)
        processor_id = id(audio_processor)
        self.active_processors[processor_id] = audio_processor
        
        logger.info(f"WhisperLive WebSocket connection opened (id: {processor_id}, format: {input_format})")
        
        # Set up processing pipeline
        try:
            # Start processing tasks and get the results generator by awaiting create_tasks
            results_generator = await audio_processor.create_tasks()
            
            # Handle results in separate task
            results_task = asyncio.create_task(
                self._handle_websocket_results(websocket, results_generator)
            )
            
            # Process incoming audio
            while True:
                message = await websocket.receive()
                
                # Handle binary audio data
                if message["type"] == "websocket.receive" and "bytes" in message:
                    await audio_processor.process_audio(message["bytes"])
                    
                # Handle text control messages (termination, etc.)
                elif message["type"] == "websocket.receive" and "text" in message:
                    text_data = message["text"]
                    logger.info(f"Received control message: {text_data}")
                    
                    # Preserve legacy termination commands before considering
                    # structured native timing controls.
                    if is_legacy_termination_control(text_data):
                        logger.info(f"Received termination command, breaking loop")
                        break
                    apply_native_stream_timing_control(text_data, audio_processor)
                        
                # Handle disconnect
                elif message["type"] == "websocket.disconnect":
                    logger.info(f"WebSocket disconnected")
                    break
                
        except WebSocketDisconnect:
            logger.info(f"WhisperLive WebSocket disconnected (id: {processor_id})")
        except Exception as e:
            logger.error(f"Error in WhisperLive WebSocket: {e}", exc_info=True)
        finally:
            # Stop meeting recording if active
            if meeting_recorder and meeting_recorder.is_recording:
                try:
                    metadata = meeting_recorder.stop_recording()
                    if metadata:
                        logger.info(f"Stopped meeting recording: {metadata['id']}")
                        logger.info(f"Meeting duration: {metadata.get('duration_seconds', 0):.1f}s")
                        # Make the just-finished recording searchable. Best-effort:
                        # the indexer swallows its own errors so this never affects
                        # recording teardown.
                        from api.services.meetings import meeting_search_indexer
                        meeting_search_indexer.reindex(metadata['id'])
                except Exception as e:
                    logger.error(f"Error stopping meeting recording: {e}", exc_info=True)
            
            # Clean up resources
            if processor_id in self.active_processors:
                try:
                    await audio_processor.cleanup()
                except Exception as e:
                    logger.error(f"Error during audio processor cleanup: {e}", exc_info=True)
                del self.active_processors[processor_id]
            
            if websocket in self.active_websockets:
                self.active_websockets.remove(websocket)
                
            logger.info(f"WhisperLive WebSocket connection closed (id: {processor_id})")
    
    async def _handle_websocket_results(self, websocket, results_generator):
        """Process results from the audio processor and send via WebSocket."""
        try:
            sent_count = 0
            transcription_started = False
            # Use async for since results_generator is now an async generator
            async for response in results_generator:
                if websocket in self.active_websockets:
                    sent_count += 1
                    
                    # Check if the response has content (response is a FrontData object with attributes)
                    has_text = False
                    if hasattr(response, 'lines') and response.lines:
                        for line in response.lines:
                            # line is a dict with 'text' key
                            if isinstance(line, dict) and line.get("text"):
                                has_text = True
                                if not transcription_started:
                                    logger.info(f"✅ First transcription received: '{line['text']}'")
                                    transcription_started = True
                                break
                    
                    # Only log lack of transcription once every 100 packets to reduce noise
                    if not has_text and not transcription_started and sent_count % 100 == 1:
                        logger.warning(f"Still no transcription after {sent_count} packets (only silence detected)")
                    
                    # Send the response (convert FrontData to dict)
                    response_dict = response.to_dict() if hasattr(response, 'to_dict') else response
                    await websocket.send_json(response_dict)
        except Exception as e:
            logger.error(f"Error in WhisperLive results handler: {e}", exc_info=True)
    
    async def shutdown(self):
        """Clean up resources when the service is stopped."""
        if not self.is_initialized:
            return
            
        # Close all WebSocket connections
        for websocket in list(self.active_websockets):
            try:
                await websocket.close()
            except Exception:
                pass
        
        # Clean up all active processors
        for processor_id, processor in list(self.active_processors.items()):
            try:
                await processor.cleanup()
            except Exception:
                pass
        
        # Reset state
        self.active_websockets.clear()
        self.active_processors.clear()
        self.is_initialized = False
        self.kit = None
        
        logger.info("WhisperLive service shut down") 