"""Creates the Parakeet encoder and decoder ONNX sessions, reusing a persistent CoreML compile cache.

Creating an ``onnxruntime.InferenceSession`` holds the Python GIL for the whole call, so a load freezes every other thread in the backend process, including the event loop that answers WebSocket pings. Measured on an M-series Mac with the full-precision Parakeet bundle, creating both sessions froze the process for about 4.8 s with no cache and about 2.6 s once the CoreML provider could reuse its compiled artifacts through ``ModelCacheDirectory``. The cache therefore shortens the freeze; it does not remove it, so callers should still load the model before any live stream depends on the event loop.

The cache directory is keyed by the onnxruntime version and by the name, size, and modification time of the exact model files, so a model update or an onnxruntime upgrade starts a fresh directory instead of reusing stale artifacts.
"""

from __future__ import annotations

import hashlib
import logging
import shutil
from pathlib import Path
from typing import Any, List, Optional, Sequence, Tuple, Union

logger = logging.getLogger(__name__)

COREML_PROVIDER = "CoreMLExecutionProvider"
COREML_CACHE_OPTION = "ModelCacheDirectory"

ProviderSpec = Union[str, Tuple[str, dict]]


def coreml_cache_directory(
    storage_dir: Path,
    ort_version: str,
    bundle_dir: Path,
    model_files: Sequence[Path],
) -> Path:
    """Return the stable cache directory for these exact model files under this onnxruntime build."""
    fingerprint_parts: List[str] = []
    for model_file in model_files:
        stat = model_file.stat()
        fingerprint_parts.append(f"{model_file.name}:{stat.st_size}:{stat.st_mtime_ns}")
    digest = hashlib.sha256("|".join(fingerprint_parts).encode("utf-8")).hexdigest()[:16]
    return storage_dir / "cache" / "coreml_ep" / f"ort-{ort_version}" / f"{bundle_dir.name}-{digest}"


def providers_with_coreml_cache(
    providers: Sequence[str],
    cache_dir: Optional[Path],
) -> List[ProviderSpec]:
    """Attach the compile-cache option to the CoreML provider; every other provider is passed through unchanged."""
    if cache_dir is None:
        return list(providers)
    resolved: List[ProviderSpec] = []
    for provider in providers:
        if provider == COREML_PROVIDER:
            resolved.append((provider, {COREML_CACHE_OPTION: str(cache_dir)}))
        else:
            resolved.append(provider)
    return resolved


def _prepare_cache_directory(
    providers: Sequence[str],
    storage_dir: Path,
    ort_version: str,
    bundle_dir: Path,
    model_files: Sequence[Path],
) -> Optional[Path]:
    """Create the cache directory when the CoreML provider is requested; return None when caching does not apply or cannot be set up."""
    if COREML_PROVIDER not in providers:
        return None
    try:
        cache_dir = coreml_cache_directory(storage_dir, ort_version, bundle_dir, model_files)
        cache_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.warning("CoreML compile cache is unavailable, loading without it: %s", exc)
        return None
    return cache_dir


def create_parakeet_session_pair(
    ort: Any,
    encoder_path: Path,
    decoder_path: Path,
    sess_options: Any,
    providers: Sequence[str],
    storage_dir: Path,
    bundle_dir: Path,
) -> Tuple[Any, Any, Optional[Path]]:
    """Create the encoder and decoder sessions and return them with the cache directory that was used (None when uncached).

    If creation fails while a compile cache is in use, the cache directory is deleted and creation is retried once without it, so a corrupted cache can never prevent transcription.
    """
    cache_dir = _prepare_cache_directory(
        providers, storage_dir, str(ort.__version__), bundle_dir, (encoder_path, decoder_path)
    )

    def create(provider_specs: Sequence[ProviderSpec]) -> Tuple[Any, Any]:
        encoder = ort.InferenceSession(
            str(encoder_path), sess_options=sess_options, providers=list(provider_specs)
        )
        decoder = ort.InferenceSession(
            str(decoder_path), sess_options=sess_options, providers=list(provider_specs)
        )
        return encoder, decoder

    try:
        encoder_session, decoder_session = create(providers_with_coreml_cache(providers, cache_dir))
    except Exception:
        if cache_dir is None:
            raise
        logger.warning(
            "Creating Parakeet sessions with the CoreML compile cache at %s failed; discarding the cache and retrying without it",
            cache_dir,
            exc_info=True,
        )
        shutil.rmtree(cache_dir, ignore_errors=True)
        encoder_session, decoder_session = create(list(providers))
        return encoder_session, decoder_session, None
    return encoder_session, decoder_session, cache_dir
