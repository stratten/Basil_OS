"""
Cloud Transcription Models Registry.

Contains cloud-based transcription models (OpenAI Whisper API) and
provider-level display ordering for the cloud transcription category.

Based on proven implementation from the Project Board Webapp using
OpenAI's /v1/audio/transcriptions endpoint.
"""

from typing import Any, Dict

from .schema import (
    PROVIDER_OPENAI,
    CloudTranscriptionConfig,
)


# =============================================================================
# PROVIDER DISPLAY ORDER - Controls provider group ordering in UI.
# =============================================================================

CLOUD_TRANSCRIPTION_PROVIDER_DISPLAY_ORDER: Dict[str, int] = {
    PROVIDER_OPENAI: 1,
}


# =============================================================================
# CLOUD TRANSCRIPTION MODELS.
# =============================================================================
#
CLOUD_TRANSCRIPTION_MODELS: Dict[str, CloudTranscriptionConfig] = {
    # =========================================================================
    # OPENAI MODELS
    # =========================================================================
    # Ref: https://platform.openai.com/docs/api-reference/audio/createTranscription
    # -------------------------------------------------------------------------
    # Whisper - Original hosted Whisper model, proven in production.
    # -------------------------------------------------------------------------
    "openai-whisper-1": {
        "handler": "openai_whisper_api",
        "chunk_seconds": 360.0,
        "location": "cloud",
        "provider": PROVIDER_OPENAI,
        "display_name": "Whisper (OpenAI API)",
        "api_model_name": "whisper-1",
        "capabilities": ["transcription"],
        "features": [],
        "openrouter_id": "openai/gpt-audio-mini",
        "supports_openrouter_proxy": True,
        "default_enabled": True,
        "display_order": 1,
        "description": "OpenAI's hosted Whisper model -- proven, reliable transcription",
    },
    # -------------------------------------------------------------------------
    # GPT-4o Transcribe - Newer GPT-4o-based transcription, higher accuracy.
    # -------------------------------------------------------------------------
    "openai-gpt-4o-transcribe": {
        "handler": "openai_whisper_api",
        "chunk_seconds": 360.0,
        "location": "cloud",
        "provider": PROVIDER_OPENAI,
        "display_name": "GPT-4o Transcribe (OpenAI API)",
        "api_model_name": "gpt-4o-transcribe",
        "capabilities": ["transcription"],
        "features": [],
        "openrouter_id": "openai/gpt-audio",
        "supports_openrouter_proxy": True,
        "default_enabled": True,
        "display_order": 2,
        "description": "GPT-4o-based transcription -- higher accuracy, higher cost",
    },
    # -------------------------------------------------------------------------
    # GPT-4o Mini Transcribe - Smaller/cheaper GPT-4o variant.
    # -------------------------------------------------------------------------
    "openai-gpt-4o-mini-transcribe": {
        "handler": "openai_whisper_api",
        "chunk_seconds": 360.0,
        "location": "cloud",
        "provider": PROVIDER_OPENAI,
        "display_name": "GPT-4o Mini Transcribe (OpenAI API)",
        "api_model_name": "gpt-4o-mini-transcribe",
        "capabilities": ["transcription"],
        "features": [],
        "openrouter_id": "openai/gpt-audio-mini",
        "supports_openrouter_proxy": True,
        "default_enabled": True,
        "display_order": 3,
        "description": "Smaller GPT-4o transcription -- good balance of cost and quality",
    },
    # -------------------------------------------------------------------------
    # GPT-4o Transcribe Diarize - File-oriented transcription with speakers.
    # Note: GPT Realtime Whisper uses the Realtime API session flow and should
    # be added through a dedicated live-transcription runtime, not this
    # /audio/transcriptions registry.
    # -------------------------------------------------------------------------
    "openai-gpt-4o-transcribe-diarize": {
        "handler": "openai_whisper_api",
        "chunk_seconds": 360.0,
        "location": "cloud",
        "provider": PROVIDER_OPENAI,
        "display_name": "GPT-4o Transcribe Diarize (OpenAI API)",
        "api_model_name": "gpt-4o-transcribe-diarize",
        "capabilities": ["transcription"],
        "features": ["diarization"],
        "openrouter_id": "openai/gpt-audio",
        "supports_openrouter_proxy": True,
        "default_enabled": False,
        "display_order": 4,
        "description": "GPT-4o transcription with speaker diarization for file uploads",
    },
}
