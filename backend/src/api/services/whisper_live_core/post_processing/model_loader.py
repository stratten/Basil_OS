"""
Model loading utilities for post-processing.

Handles loading of Whisper transcription models and diarization models
from local directories with automatic backend detection.
"""
import logging
import asyncio
import torch
import os
import sys
from pathlib import Path
from typing import Any, Tuple

logger = logging.getLogger(__name__)


# Backend tags returned by load_model (kept in sync with WarmWhisperPipeline /
# ModelManager.HF_BACKEND).
HF_BACKEND = "huggingface"
FASTER_WHISPER_BACKEND = "faster_whisper"


class WhisperModelLoader:
    """
    Resolves and loads Whisper models for post-processing retranscription,
    reusing the shared warm cache so the model is loaded once across both
    source files and shared with on-demand transcription.

    Backends:
    - HuggingFace transformers (safetensors/.pt) - loaded and cached via the
      shared ``ModelManager`` warm pipeline (the single HF builder).
    - faster-whisper (CTranslate2 ``model.bin``) - loaded and cached directly in
      the shared ``WarmWhisperPipeline`` (ModelManager is HF-only).

    Model name/dir resolution lives in ``whisper_source_resolver`` (single source
    of truth); this class no longer carries its own display-name->dir mapping.
    """

    @classmethod
    async def load_model(cls, model_name: str) -> Tuple[Any, str, Path]:
        """
        Resolve and load a Whisper model, reusing the shared warm cache.

        Args:
            model_name: Friendly model name or registry id.

        Returns:
            Tuple of (loaded_object, backend_tag, model_path) where
            backend_tag is "huggingface" (object is an ASR pipeline) or
            "faster_whisper" (object is a faster_whisper.WhisperModel).

        Raises:
            RuntimeError: If no supported model format is found.
        """
        from api.services.transcription.local_model.whisper_source_resolver import (
            resolve_whisper_source,
        )
        from whisperlivekit.model_paths import model_path_and_type

        source = resolve_whisper_source(model_name)
        model_path = source.local_dir

        # Detect faster-whisper (CT2) only from an existing local dir; otherwise
        # default to HuggingFace, which ModelManager can download if absent.
        has_faster_whisper = False
        if source.exists_locally:
            _, has_mlx, has_faster_whisper = model_path_and_type(model_path)
            logger.info(
                f"Model '{model_name}' -> {model_path} "
                f"(faster_whisper={has_faster_whisper}, mlx={has_mlx})"
            )
        else:
            logger.info(
                f"Model '{model_name}' not present locally at {model_path}; "
                f"using HuggingFace backend (repo: {source.repo_id})"
            )

        loop = asyncio.get_running_loop()

        if has_faster_whisper:
            model = await loop.run_in_executor(
                None, lambda: cls._load_faster_whisper_cached(source)
            )
            logger.info(f"Loaded faster-whisper model (warm-cached) from: {model_path}")
            return model, FASTER_WHISPER_BACKEND, model_path

        # HuggingFace path: reuse the single shared warm pipeline so on-demand
        # transcription and retranscription share one resident model and the
        # second source file does not trigger a reload.
        from api.services.transcription.local_model.model_lifecycle import ModelManager

        manager = ModelManager()
        pipe, _device, _cache_key = await loop.run_in_executor(
            None, lambda: manager.get_warm_pipeline(source.model_id)
        )
        logger.info(f"Using warm HuggingFace pipeline for: {source.display_name}")
        return pipe, HF_BACKEND, model_path

    @staticmethod
    def _load_faster_whisper_cached(source) -> Any:
        """Load (or reuse) a faster-whisper model via the shared warm cache."""
        from api.services.transcription.local_model.warm_whisper_pipeline import (
            WarmWhisperPipeline,
        )

        def loader():
            from faster_whisper import WhisperModel

            return WhisperModel(
                str(source.local_dir),
                device="cpu",
                compute_type="float32",
            )

        return WarmWhisperPipeline.get_or_load(
            source.cache_key, FASTER_WHISPER_BACKEND, "cpu", loader
        )


class DiarizationModelLoader:
    """
    Loads speaker diarization models from local vendor directory.
    
    Uses diart/pyannote models bundled in the application to avoid
    requiring HuggingFace authentication.
    """
    
    @classmethod
    async def load_pipeline(cls) -> Any:
        """
        Load diarization pipeline with local models.
        
        Returns:
            Configured SpeakerDiarization pipeline
            
        Raises:
            RuntimeError: If required model files are not found
        """
        # Set up local model paths BEFORE importing diart/pyannote
        cls._setup_local_paths()
        
        # Import diart after path setup
        from diart import SpeakerDiarization, SpeakerDiarizationConfig
        
        # Select best available device
        device = cls._select_device()
        
        # Create diarization pipeline
        loop = asyncio.get_running_loop()
        
        def create_pipeline():
            # Use DIHARD III benchmark parameters - optimized for challenging multi-speaker scenarios
            config = SpeakerDiarizationConfig(
                sample_rate=16000,
                device=device,
                segmentation=None,  # Triggers default loading from local files
                embedding=None,     # Triggers default loading from local files
                duration=5.0,        # 5-second chunks (default)
                step=0.5,            # 0.5-second steps (default)
                latency="max",       # Maximum aggregation for offline processing
                tau_active=0.555,    # Activity detection threshold (DIHARD III optimized)
                rho_update=0.422,    # Centroid update threshold
                delta_new=1.517,     # New speaker threshold - conservative
            )
            
            return SpeakerDiarization(config=config)
        
        pipeline = await loop.run_in_executor(None, create_pipeline)
        
        logger.info("Loaded diarization models from local vendor directory")
        return pipeline
    
    @staticmethod
    def _setup_local_paths() -> None:
        """Set up local module paths for vendor models."""
        current_dir = os.path.dirname(os.path.abspath(__file__))
        parent_dir = os.path.dirname(current_dir)  # whisper_live_core
        
        # Add to path for importing local modules
        if parent_dir not in sys.path:
            sys.path.append(parent_dir)
        
        # Import and initialize local modules setup
        from setup_local_modules import LocalModulesSetup
        
        # Set up local model paths - this hijacks pyannote model loading
        LocalModulesSetup.setup_paths()
        
        # Disable HF checks
        os.environ["PYANNOTE_DISABLE_HF_CHECKS"] = "1"
        os.environ["DIARIZATION_BACKEND"] = "diart"
        
        # Check if models are available
        if not LocalModulesSetup.check_models():
            raise RuntimeError(
                "Required pyannote model files not found in vendor directory. "
                "Diarization requires local model files to avoid HuggingFace authentication."
            )
    
    @staticmethod
    def _select_device() -> torch.device:
        """Select the best available device for diarization."""
        if torch.backends.mps.is_available():
            device = torch.device('mps')
            logger.info("Using Apple Metal (MPS) acceleration for diarization models")
        elif torch.cuda.is_available():
            device = torch.device('cuda')
            logger.info("Using CUDA acceleration for diarization models")
        else:
            device = torch.device('cpu')
            logger.info("Using CPU for diarization models")
        
        return device

