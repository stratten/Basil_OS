"""
Configuration mapper between Basil and upstream WhisperLiveKit.

Maps our user-friendly configuration format to the upstream TranscriptionEngine
parameter format.
"""

import logging
import torch

logger = logging.getLogger(__name__)


def map_basil_config_to_upstream(basil_config: dict) -> dict:
    """
    Convert Basil configuration format to upstream TranscriptionEngine format.
    
    Basil config (from whisper_live_service initialization):
    {
        "model": "Distil-Whisper Large V3.5",  # User-friendly name
        "language": "en",
        "diarization": True,
        "transcription": True,
    }
    
    Upstream expects:
    {
        "model_size": "large-v3",              # Whisper model name
        "lan": "en",                            # Language code
        "backend_policy": "simulstreaming",     # ASR backend (NEW SOTA 2025)
        "diarization": True,
        "diarization_backend": "diart",         # Force diart, not sortformer
        "vac": True,                            # Voice Activity Detection
        "pcm_input": True,                      # PCM audio format
        "transcription": True,
    }
    
    Args:
        basil_config: Configuration dict from WhisperLiveService
        
    Returns:
        Configuration dict compatible with TranscriptionEngine
    """
    # Model name mapping (user-friendly → Whisper model name)
    model_mapping = {
        "Distil-Whisper Large V3.5": "large-v3",
        "Distil-Whisper Large V3": "large-v3",
        "Large V3": "large-v3",
        "Large V2": "large-v2",
        "Large": "large",
        "Medium": "medium",
        "Small": "small",
        "Base": "base",
        "Tiny": "tiny",
    }

    # Parakeet model mapping (user-friendly display name OR registry id
    # → Parakeet *registry id* used by ParakeetTranscriptionService /
    #   ParakeetASR.load_model). Sourced from
    #   `models_registry.get_parakeet_transcription_models` so adding a
    #   new Parakeet entry to the registry automatically lights it up
    #   for live transcription too.
    parakeet_models: dict[str, str] = {}
    try:
        from api.core.models.models_registry import get_parakeet_transcription_models
        for registry_id, cfg in get_parakeet_transcription_models().items():
            parakeet_models[registry_id] = registry_id
            display_name = cfg.get("display_name")
            if display_name:
                parakeet_models[display_name] = registry_id
    except Exception as parakeet_lookup_err:
        # We must not block the Whisper path if registry import fails --
        # just log and continue with an empty Parakeet map.
        logger.debug(
            f"config_mapper: could not enumerate Parakeet registry "
            f"({parakeet_lookup_err}); live Parakeet selection disabled."
        )

    upstream_config = {}

    # Map model name
    model = basil_config.get("model", "base")

    # Parakeet branch -- bypass the entire CTranslate2 / large-model
    # downgrade logic below. Parakeet runs on CPU (or CoreML/CUDA EP)
    # via onnxruntime regardless of MPS/CUDA availability, and the
    # Whisper sizing heuristics do not apply.
    if model in parakeet_models:
        registry_id = parakeet_models[model]
        upstream_config["model_size"] = registry_id
        upstream_config["lan"] = basil_config.get("language", "en")
        # Force LocalAgreement (Phase 1 streaming strategy). Cache-aware
        # streaming with SimulStreaming is deferred to a Phase 2
        # follow-up; for now the upstream policy slot is hard-pinned to
        # local_agreement so the engine builds an OnlineASRProcessor
        # around our ParakeetASR.
        upstream_config["backend_policy"] = "local_agreement"
        upstream_config["backend"] = "parakeet"
        upstream_config["model_cache_dir"] = None

        # Diarization knobs are still honored if the user enabled them.
        if basil_config.get("diarization", False):
            upstream_config["diarization"] = True
            upstream_config["diarization_backend"] = "diart"
            upstream_config["segmentation_model_name"] = "pyannote/segmentation-3.0"
            upstream_config["embedding_model_name"] = "pyannote/embedding"
        else:
            upstream_config["diarization"] = False

        upstream_config["transcription"] = basil_config.get("transcription", True)
        upstream_config["pcm_input"] = basil_config.get("pcm_input", True)
        upstream_config["vac"] = basil_config.get("vac", True)
        upstream_config["vad"] = basil_config.get("vad", True)
        upstream_config["task"] = basil_config.get("task", "transcribe")
        upstream_config["device"] = basil_config.get("device", "auto")
        upstream_config["compute_type"] = basil_config.get("compute_type", "default")
        upstream_config["min_chunk_size"] = basil_config.get("min_chunk_size", 0.1)

        for key, value in basil_config.items():
            if key not in upstream_config and key != "model":
                upstream_config[key] = value
                logger.debug(f"Passing through config param: {key}={value}")

        logger.info(
            f"Mapped config (Parakeet): model_size={registry_id}, "
            f"backend_policy={upstream_config['backend_policy']}, "
            f"backend={upstream_config['backend']}, "
            f"diarization={upstream_config.get('diarization', False)}, "
            f"vac={upstream_config['vac']}"
        )
        return upstream_config

    mapped_model = model_mapping.get(model, model.lower().replace(" ", "-"))
    supported_ctranslate2_sizes = {
        "tiny.en",
        "tiny",
        "base.en",
        "base",
        "small.en",
        "small",
        "medium.en",
        "medium",
        "large-v1",
        "large-v2",
        "large-v3",
        "large",
        "distil-large-v2",
        "distil-medium.en",
        "distil-small.en",
        "distil-large-v3",
        "large-v3-turbo",
        "turbo",
    }
    if mapped_model not in supported_ctranslate2_sizes:
        logger.warning(
            f"Model '{model}' mapped to unsupported Faster-Whisper size '{mapped_model}'. "
            f"Falling back to 'base' for WhisperLive compatibility."
        )
        mapped_model = "base"
    
    # Smart fallback: CTranslate2 (faster-whisper) only supports CUDA, not MPS
    # On M1/M2 Macs with MPS but no CUDA, large models will run on CPU and be extremely slow
    # We must downgrade to base model for usable live transcription performance
    has_cuda = torch.cuda.is_available()
    has_mps = torch.backends.mps.is_available()
    
    # CTranslate2 can only use CUDA, not MPS
    has_usable_gpu_for_ctranslate2 = has_cuda
    
    if not has_usable_gpu_for_ctranslate2:
        large_models = ["large-v3", "large-v2", "large-v1", "large", "medium"]
        if mapped_model in large_models:
            original_model = mapped_model
            mapped_model = "base"
            if has_mps:
                logger.warning(
                    f"CTranslate2 (faster-whisper) doesn't support Metal/MPS acceleration. "
                    f"Automatically downgrading model from '{original_model}' to '{mapped_model}' for CPU performance. "
                    f"Large models take 80+ seconds per chunk on CPU, making live transcription unusable. "
                    f"Base model processes in ~1-2 seconds per chunk."
                )
            else:
                logger.warning(
                    f"No GPU acceleration available. "
                    f"Automatically downgrading model from '{original_model}' to '{mapped_model}' for CPU performance. "
                    f"Large models take 80+ seconds per chunk on CPU, making live transcription unusable."
                )
        else:
            if has_mps:
                logger.info(f"Using model '{mapped_model}' on CPU (CTranslate2 doesn't support MPS)")
            else:
                logger.info(f"Using model '{mapped_model}' on CPU (no GPU acceleration available)")
    else:
        logger.info(f"Using model '{mapped_model}' with CUDA acceleration")
    
    upstream_config["model_size"] = mapped_model
    
    logger.info(f"Final model selection: '{mapped_model}'")
    
    # Map language (upstream uses 'lan' not 'language')
    upstream_config["lan"] = basil_config.get("language", "en")
    
    # Default to SimulStreaming for live transcription, but allow specialized
    # callers (agent-task capture termination) to request local_agreement when
    # they depend on that processor/back-end contract.
    upstream_config["backend_policy"] = basil_config.get("backend_policy", "simulstreaming")
    upstream_config["backend"] = "faster-whisper"          # Whisper implementation
    
    # Prevent any Hugging Face downloads - use only local models
    upstream_config["model_cache_dir"] = None  # Will use default ~/.cache/huggingface
    # Note: If we need to specify a local cache, we can set this to a specific path
    
    # Diarization settings
    if basil_config.get("diarization", False):
        upstream_config["diarization"] = True
        upstream_config["diarization_backend"] = "diart"  # Force diart with our local models
        # These will be picked up by diart_backend.py - note the _name suffix!
        upstream_config["segmentation_model_name"] = "pyannote/segmentation-3.0"
        upstream_config["embedding_model_name"] = "pyannote/embedding"
    else:
        upstream_config["diarization"] = False
    
    # Transcription settings
    upstream_config["transcription"] = basil_config.get("transcription", True)
    
    # Audio format - PCM for native Swift client
    # This gets set based on WebSocket query param 'client=native'
    # but we can set a default here
    upstream_config["pcm_input"] = basil_config.get("pcm_input", True)
    
    # Enable Voice Activity Detection for better silence handling
    upstream_config["vac"] = basil_config.get("vac", True)
    upstream_config["vad"] = basil_config.get("vad", True)  # Alias for vac
    
    # Task type
    upstream_config["task"] = basil_config.get("task", "transcribe")
    
    # Device selection
    upstream_config["device"] = basil_config.get("device", "auto")
    
    # Compute type (for faster-whisper)
    upstream_config["compute_type"] = basil_config.get("compute_type", "default")
    
    # Chunk size for processing
    upstream_config["min_chunk_size"] = basil_config.get("min_chunk_size", 0.1)
    
    # Pass through any other params that might be useful
    for key, value in basil_config.items():
        if key not in upstream_config and key not in ["model"]:  # Avoid duplicating 'model'
            upstream_config[key] = value
            logger.debug(f"Passing through config param: {key}={value}")
    
    logger.info(f"Mapped config: backend_policy={upstream_config['backend_policy']}, "
                f"diarization={upstream_config.get('diarization', False)}, "
                f"diarization_backend={upstream_config.get('diarization_backend', 'none')}, "
                f"vac={upstream_config['vac']}")
    
    return upstream_config


def get_default_config() -> dict:
    """
    Get default Basil configuration for WhisperLive.
    
    Note: The configuration will automatically adjust the model size based on
    available hardware acceleration:
    - With GPU/Metal: Uses the specified model (including large models)
    - CPU only: Automatically downgrades to 'base' for acceptable real-time performance
    
    Returns:
        Default configuration dict
    """
    return {
        "model": "Base",
        "language": "en",
        "diarization": False,  # Disabled for live view - too slow, will be added in post-processing
        "transcription": True,
        "task": "transcribe",
        "vac": True,
        "pcm_input": True,
        "min_chunk_size": 0.1,
    }

