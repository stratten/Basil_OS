"""
Audio processing utilities for transcription services.

Contains functions for audio normalization and WAV file handling.
"""

from typing import Optional
from pathlib import Path
from datetime import datetime
import numpy as np
import soundfile as sf
import logging
import subprocess
import tempfile

from ....core.logging.api_logger import setup_api_logger
from ....core.config.api_settings import settings

logger = setup_api_logger(
    __name__,
    log_file=settings.STORAGE_DIR / "logs" / "api.log" if not settings.DEBUG else None,
    level=logging.DEBUG if settings.DEBUG else logging.INFO
)


def rms_normalize_audio(audio: np.ndarray, target_rms: float = 0.05, epsilon: float = 1e-8) -> np.ndarray:
    """
    Normalize audio using RMS (Root Mean Square) to improve transcription accuracy.
    
    Args:
        audio: Input audio array
        target_rms: Target RMS level (default 0.05 provides good balance)
        epsilon: Small value to prevent division by zero
        
    Returns:
        Normalized audio array
    """
    # Calculate current RMS
    current_rms = np.sqrt(np.mean(audio**2))
    
    # Avoid division by zero and very quiet audio
    if current_rms < epsilon:
        return audio
    
    # Calculate scaling factor
    scale_factor = target_rms / current_rms
    
    # Apply normalization with clipping to prevent distortion
    normalized_audio = audio * scale_factor
    normalized_audio = np.clip(normalized_audio, -1.0, 1.0)
    
    return normalized_audio


async def convert_audio_to_wav(input_path: str) -> str:
    """
    Convert an audio file to WAV format using ffmpeg.

    Args:
        input_path: Path to the input audio file

    Returns:
        str: Path to the converted WAV file
    """
    try:
        # Check if file is already a WAV file
        if input_path.lower().endswith('.wav'):
            logger.info(f"File is already in WAV format: {input_path}")
            return input_path

        # Create a temporary WAV file
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as temp_wav:
            output_path = temp_wav.name

        logger.info(f"Converting {input_path} to WAV format at {output_path}")

        # Use ffmpeg to convert to WAV format with 16kHz sample rate (expected by Whisper)
        try:
            result = subprocess.run(
                [
                    "ffmpeg",
                    "-y",  # Overwrite output file if it exists
                    "-i", input_path,  # Input file
                    "-ar", "16000",  # Sample rate: 16kHz
                    "-ac", "1",  # Audio channels: mono
                    "-c:a", "pcm_s16le",  # Codec: PCM 16-bit little-endian
                    output_path,  # Output file
                ],
                capture_output=True,
                text=True,
                check=True,
            )

            logger.info(f"Successfully converted audio file using ffmpeg: {result.stdout}")

            # Return path to the converted WAV file
            return output_path

        except subprocess.CalledProcessError as e:
            logger.error(f"Error converting audio file: {e.stderr}")
            raise ValueError(f"Failed to convert audio file: {e.stderr}")
        except FileNotFoundError:
            logger.error("ffmpeg not found. Please install ffmpeg.")
            raise ValueError("ffmpeg not installed. Cannot convert audio file.")

    except Exception as e:
        logger.error(f"Error in convert_audio_to_wav: {e}")
        raise


def save_audio_to_wav(
    audio_data: bytes,
    recordings_dir: Path,
    uploads_dir: Path,
    source: str = 'recording',
    original_filename: Optional[str] = None
) -> Path:
    """
    Save audio data to a WAV file with timestamp-based organization.
    
    Args:
        audio_data: Raw audio data
        recordings_dir: Directory for recordings
        uploads_dir: Directory for uploaded files
        source: Source of the audio ('recording', 'file_upload', or 'agent_task')
        original_filename: Original filename for uploaded files
        
    Returns:
        Path to the saved WAV file
    """
    # Create timestamp-based directory structure
    now = datetime.now()
    year_month = now.strftime("%Y_%m")
    day = now.strftime("%d")
    timestamp = now.strftime("%H%M%S")
    
    # Determine the target directory based on source
    if source == 'file_upload':
        # For uploaded files
        save_dir = uploads_dir / year_month / day
    else:
        # For recordings
        save_dir = recordings_dir / year_month / day
        
    save_dir.mkdir(parents=True, exist_ok=True)
    
    # Set up filename
    if source == 'file_upload' and original_filename:
        # Keep part of the original filename for uploaded files
        base_name = Path(original_filename).stem
        # Ensure the name is valid and not too long
        base_name = ''.join(c for c in base_name if c.isalnum() or c in '._- ')[:50]
        filename = f"upload_{timestamp}_{base_name}.wav"
    else:
        # Standard naming for recordings
        filename = f"recording_{timestamp}.wav"
    
    # Full path for the new file
    wav_path = save_dir / filename
    
    # Handle the audio data based on its format and source
    try:
        if source == 'file_upload':
            # For uploaded files, just write the bytes directly
            # These are already complete audio files with headers
            with open(wav_path, 'wb') as f:
                f.write(audio_data)
            print(f"Saved uploaded audio file to: {wav_path}")
        elif source == 'agent_task':
            # For agent_tasks, audio_data is raw Float32 PCM data from Swift AudioCaptureService
            # Convert to proper WAV file format
            if isinstance(audio_data, bytes):
                try:
                    # Convert raw Float32 bytes to numpy array
                    audio = np.frombuffer(audio_data, dtype=np.float32)
                    
                    # Basic validation
                    if len(audio) < 100:
                        print(f"Warning: AgentTask audio data is very short: {len(audio)} samples")
                    
                    # Save as proper WAV file with Float32 PCM format
                    sf.write(
                        str(wav_path), 
                        audio, 
                        16000,  # 16kHz sample rate (matches Swift AudioCaptureService)
                        subtype='FLOAT',  # Float32 format
                        format='WAV'
                    )
                    print(f"Saved agent_task as Float32 WAV: {wav_path}")
                    
                except Exception as e:
                    print(f"Could not convert agent_task audio to WAV: {e}")
                    # Fallback to writing raw bytes
                    with open(wav_path, 'wb') as f:
                        f.write(audio_data)
                    print(f"Saved raw agent_task bytes to: {wav_path}")
            else:
                raise ValueError(f"Unexpected agent_task audio data type: {type(audio_data)}")
        else:
            # For recordings, interpret as raw PCM float32 data
            if isinstance(audio_data, bytes):
                try:
                    audio = np.frombuffer(audio_data, dtype=np.float32)
                    
                    # Basic validation
                    if len(audio) < 100:  # Arbitrary small number to check if data is too short
                        print(f"Warning: Audio data is very short: {len(audio)} samples")
                    
                    # Save as WAV file
                    sf.write(
                        str(wav_path), 
                        audio, 
                        16000,  # Specify correct 16kHz sample rate
                        subtype='FLOAT',  # Use float32 format
                        format='WAV'
                    )
                    print(f"Saved recording as float32 PCM: {wav_path}")
                    if wav_path.exists():
                        logger.info(f"SUCCESS: WAV file confirmed to exist at {wav_path}")
                        logger.info(f"SUCCESS: WAV file size: {wav_path.stat().st_size} bytes")
                        if wav_path.stat().st_size == 0:
                            logger.warning(f"WARNING: WAV file at {wav_path} is 0 bytes after sf.write!")
                    else:
                        logger.error(f"FAILURE: WAV file DOES NOT EXIST at {wav_path} after sf.write attempt!")
                except Exception as e:
                    # If we can't interpret as float32, just write the raw bytes to file
                    print(f"Could not interpret audio as float32: {e}")
                    with open(wav_path, 'wb') as f:
                        f.write(audio_data)
                    print(f"Saved raw audio bytes to: {wav_path}")
            else:
                # Unexpected input type
                raise ValueError(f"Unexpected audio data type: {type(audio_data)}")
            
        return wav_path
            
    except Exception as e:
        print(f"Error saving audio to WAV: {e}")
        raise
