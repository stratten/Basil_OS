"""
Core transcription processing logic.

Handles the actual transcription workflow including audio loading, model inference,
result processing, and database storage.
"""

from typing import Optional, Dict, Any
from pathlib import Path
from datetime import datetime
import numpy as np
import soundfile as sf
import librosa
import asyncio
import traceback
import logging

from .audio_utils import rms_normalize_audio
from ..local_model.model_lifecycle import ModelManager
from . import transcription_lifecycle

from ....core.logging.api_logger import setup_api_logger
from ....core.config.api_settings import settings
from ....core.knowledge.sqlite.transcription_repository import TranscriptionRepository

logger = setup_api_logger(
    __name__,
    log_file=settings.STORAGE_DIR / "logs" / "api.log" if not settings.DEBUG else None,
    level=logging.DEBUG if settings.DEBUG else logging.INFO
)


class TranscriptionProcessor:
    """
    Handles the core transcription workflow.
    
    Processes audio data through the Whisper model and handles result storage.
    """
    
    def __init__(
        self,
        model_manager: ModelManager,
        recordings_dir: Path,
        uploads_dir: Path,
        transcription_repository: TranscriptionRepository
    ):
        """
        Initialize the transcription processor.
        
        Args:
            model_manager: The ModelManager instance for accessing the loaded model
            recordings_dir: Directory for saving recordings
            uploads_dir: Directory for saving uploaded files
            transcription_repository: Repository for storing transcription records
        """
        self.model_manager = model_manager
        self.recordings_dir = recordings_dir
        self.uploads_dir = uploads_dir
        self.transcription_repository = transcription_repository
    
    async def process_transcription(
        self,
        audio_data: bytes,
        context_info: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Process audio data and return transcribed text.
        
        Args:
            audio_data: Raw audio bytes to transcribe
            context_info: Optional context information including source, language, etc.
            
        Returns:
            Transcribed text string
        """
        if not self.model_manager.is_model_loaded():
            # Lazily load the model and proceed once ready
            print("ℹ️ Transcription model not loaded; loading now before transcribing...")
            loop = asyncio.get_running_loop()
            # load_model is synchronous; run it in executor to avoid blocking event loop
            await loop.run_in_executor(None, self.model_manager.load_model)
            if not self.model_manager.is_model_loaded():
                # If loading failed, surface a clear error
                raise ValueError("Transcription model failed to load.")
        
        print("\n=== Starting Transcription Process ===")

        language = None
        if context_info and 'language' in context_info:
            language = context_info.get('language')

        pipe = self.model_manager.shared_pipe
        model_name = (
            pipe.model.config.name_or_path
            if (pipe and hasattr(pipe, 'model'))
            else "unknown"
        )

        # Persist audio and (for eligible contexts) create a pending history
        # row BEFORE running the model. A failure from here on is caught
        # below and flipped to status='failed' so the user can re-try
        # without losing their audio.
        stub = await transcription_lifecycle.begin(
            audio_data,
            context_info,
            model_name=model_name,
            language=language if language and language != 'auto' else None,
        )
        wav_path = stub.audio_path
        if stub.is_retranscription and not wav_path.exists():
            raise ValueError(f"Existing audio file not found: {wav_path}")

        try:
            if not stub.is_retranscription:
                print(f"📊 Input audio size: {len(audio_data)} bytes")
                if audio_data:
                    print("🔍 Audio data first 100 bytes (hex):", audio_data[:100].hex())
                if context_info and context_info.get('source') == 'file_upload':
                    print(f"🎵 Processing uploaded file: {context_info.get('original_filename')}")
                    for k in ('content_type', 'file_size', 'language', 'description'):
                        if context_info.get(k):
                            print(f"🎵 {k}: {context_info.get(k)}")
                print(f"✅ Audio saved to: {wav_path}")
            else:
                print(f"🔄 Retranscription mode - using existing audio file: {wav_path}")

            start_time = datetime.now()

            transcription_kwargs = {"return_timestamps": True}

            logger.info(f"⚙️ Dispatching transcription with parameters: {transcription_kwargs}")

            self._run_audio_diagnostics(wav_path)

            audio_for_whisper = None
            try:
                print("🔍 Loading audio for Whisper analysis...")
                audio_for_whisper, sr = librosa.load(str(wav_path), sr=16000, mono=True)
                print(f"📊 Audio for Whisper - Shape: {audio_for_whisper.shape}, Sample rate: {sr}")
                print(f"📊 Audio duration: {len(audio_for_whisper)/sr:.2f} seconds")

                original_rms = np.sqrt(np.mean(audio_for_whisper**2))
                print(f"📊 Original audio RMS level: {original_rms:.6f}")
                print(f"📊 Original audio max amplitude: {np.max(np.abs(audio_for_whisper)):.6f}")

                if original_rms > 1e-8:
                    audio_for_whisper = rms_normalize_audio(audio_for_whisper)
                    normalized_rms = np.sqrt(np.mean(audio_for_whisper**2))
                    print(f"🔧 Applied RMS normalization: {original_rms:.6f} → {normalized_rms:.6f}")

                    sf.write(str(wav_path), audio_for_whisper, sr, subtype='FLOAT', format='WAV')
                    print("✅ Saved normalized audio to WAV file")
                else:
                    print("⚠️ WARNING: Audio RMS level is very low - skipping normalization")

                print(f"📊 Final audio statistics - Min: {np.min(audio_for_whisper):.6f}, Max: {np.max(audio_for_whisper):.6f}")

                if len(audio_for_whisper) > sr:
                    mid_start = len(audio_for_whisper) // 3
                    mid_end = 2 * len(audio_for_whisper) // 3
                    mid_audio = audio_for_whisper[mid_start:mid_end]
                    mid_rms = np.sqrt(np.mean(mid_audio**2))
                    print(f"📊 Middle 1/3 audio RMS: {mid_rms:.6f}")

            except Exception as e:
                print(f"⚠️ Could not analyze audio for Whisper: {e}")

            print(f"⚙️ Dispatching transcription with parameters: {transcription_kwargs}")
            model = self.model_manager.shared_model
            if model:
                print(f"🎯 Whisper model config - Vocab size: {model.config.vocab_size}")

            def run_whisper_with_logging():
                print("🔄 Starting Whisper pipeline...")
                with self.model_manager.acquire_warm_pipeline(priority="live") as pipe:
                    inference_kwargs = dict(transcription_kwargs)
                    if language and language != 'auto':
                        print(f"🔤 Setting language for transcription: {language}")
                        if hasattr(pipe, 'model') and hasattr(pipe.model.config, 'lang_to_id'):
                            if language in pipe.model.config.lang_to_id:
                                inference_kwargs["language"] = language
                            else:
                                print(f"⚠️ Language '{language}' not supported by model")
                    if audio_for_whisper is not None:
                        print("🎵 Using audio array for Whisper (preferred method)")
                        whisper_input = audio_for_whisper
                    else:
                        print("🎵 Falling back to file path for Whisper (audio array not available)")
                        whisper_input = str(wav_path)
                    whisper_result = pipe(whisper_input, **inference_kwargs)
                print(f"🔍 Raw Whisper result type: {type(whisper_result)}")
                print(f"🔍 Raw Whisper result: {whisper_result}")
                return whisper_result

            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(None, run_whisper_with_logging)

            processing_time_ms = int((datetime.now() - start_time).total_seconds() * 1000)

            transcription, _ = self._process_result(result)

            print(f"\n✅ Transcription completed successfully")
            print(f"📊 Final text length: {len(transcription)} characters")
            print(f"📝 Transcribed text: {transcription}")

            await transcription_lifecycle.complete(
                stub,
                transcription,
                processing_time_ms=processing_time_ms,
                model_name=model_name,
            )

            print("=== End Transcription Process ===")
            return transcription

        except Exception as e:
            print(f"❌ Transcription failed: {e}")
            try:
                await transcription_lifecycle.fail(
                    stub,
                    str(e),
                    model_name=model_name,
                )
            except Exception as persist_exc:
                logger.warning(
                    f"Also failed to record transcription failure: {persist_exc}"
                )
            raise
    
    def _run_audio_diagnostics(self, wav_path: Path) -> None:
        """Run diagnostic checks on the audio file."""
        try:
            # Check for bundled libsndfile libraries
            if hasattr(sf, '_ffi') and hasattr(sf._ffi, 'dlopen'): 
                try:
                    # Try to access the loaded library handle  
                    handle = sf._ffi.dlopen('libsndfile.dylib')
                    logger.info(f"🩺 [DIAGNOSTIC] soundfile._ffi.dlopen handle for 'libsndfile.dylib': {handle}")
                except Exception as e_dlopen:
                    logger.info(f"🩺 [DIAGNOSTIC] sf._ffi.dlopen('libsndfile.dylib') failed: {e_dlopen}")
            
            # Try to get version info as an alternative diagnostic
            if hasattr(sf, '__version__'):
                logger.info(f"🩺 [DIAGNOSTIC] soundfile version: {sf.__version__}")
            if hasattr(sf, '_snd'):
                logger.info(f"🩺 [DIAGNOSTIC] soundfile internal _snd object available")
                
        except Exception as e_path_diag:
            logger.info(f"🩺 [DIAGNOSTIC] Soundfile library diagnostics completed with exception: {e_path_diag}")
        
        try:
            logger.info(f"🩺 [DIAGNOSTIC] Attempting to load with soundfile: {wav_path.as_posix()}")
            sf_data, sf_samplerate = sf.read(wav_path.as_posix())
            logger.info(f"🩺 [DIAGNOSTIC] Soundfile loaded successfully. Shape: {sf_data.shape}, Samplerate: {sf_samplerate}")
            # Log a tiny bit of the data if it's not empty
            if hasattr(sf_data, 'size') and sf_data.size > 0:
                logger.info(f"🩺 [DIAGNOSTIC] Soundfile data (first 5 samples): {sf_data[:5]}")
            else:
                logger.info(f"🩺 [DIAGNOSTIC] Soundfile data is empty or not as expected.")
        except Exception as e_sf:
            logger.error(f"🩺 [DIAGNOSTIC] Soundfile direct load FAILED. Exception type: {type(e_sf)}")
            logger.error(f"🩺 [DIAGNOSTIC] Exception message: {str(e_sf)}")
            detailed_traceback_sf = traceback.format_exc()
            logger.error(f"🩺 [DIAGNOSTIC] Soundfile traceback: {detailed_traceback_sf}")
        
        try:
            logger.info(f"🩺 [DIAGNOSTIC] Attempting to load with librosa: {wav_path.as_posix()}")
            # Librosa expects sr=None to preserve original sample rate.
            lr_data, lr_samplerate = librosa.load(wav_path.as_posix(), sr=None, mono=True)
            logger.info(f"🩺 [DIAGNOSTIC] Librosa loaded successfully. Shape: {lr_data.shape}, Samplerate: {lr_samplerate}")
            if hasattr(lr_data, 'size') and lr_data.size > 0:
                logger.info(f"🩺 [DIAGNOSTIC] Librosa data (first 5 samples): {lr_data[:5]}")
            else:
                logger.info(f"🩺 [DIAGNOSTIC] Librosa data is empty or not as expected.")
        except Exception as e_lr:
            logger.error(f"🩺 [DIAGNOSTIC] Librosa direct load FAILED. Exception type: {type(e_lr)}")
            logger.error(f"🩺 [DIAGNOSTIC] Exception message: {str(e_lr)}")
            detailed_traceback_lr = traceback.format_exc()
            logger.error(f"🩺 [DIAGNOSTIC] Librosa traceback: {detailed_traceback_lr}")
    
    def _process_result(self, result) -> tuple[str, Optional[float]]:
        """
        Process the Whisper result into a transcription string.
        
        Returns:
            Tuple of (transcription_text, confidence_score)
        """
        print("\n📝 Processing transcription result...")
        
        # Handle both dictionary and string results, with special handling for chunks format
        if isinstance(result, dict):
            print("🔍 Result type: Dictionary")
            
            # Handle the chunks format returned when using return_timestamps=True
            if "chunks" in result and isinstance(result["chunks"], list):
                print(f"🔍 Detected timestamp chunks format with {len(result['chunks'])} chunks")
                transcription = "".join(chunk["text"] for chunk in result["chunks"]).strip()
            elif "text" in result:
                transcription = result["text"].strip()
            else:
                print("⚠️ Unexpected result format, using string representation")
                transcription = str(result).strip()
            
            # Add a single trailing space if non-empty
            if transcription:
                transcription += " "
            
            # Extract confidence if available
            confidence_score = result.get("confidence", None)
        else:
            print("🔍 Result type: String")
            transcription = str(result).strip()
            confidence_score = None
            # Add a single trailing space if non-empty
            if transcription:
                transcription += " "
        
        return transcription, confidence_score
    
