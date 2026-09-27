"""Explicit transcription model resolution for one-off retranscription jobs."""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from api.dependencies import resolve_transcription_service
from api.services.transcription.base_transcription_service import BaseTranscriptionService


class InvalidTranscriptionModelOverride(ValueError):
    """Raised when a retranscription model override cannot be resolved."""


def resolve_retranscription_transcription_service(
    model_id: Optional[str],
) -> BaseTranscriptionService:
    """Resolve a transcription service for one retranscription request.

    ``None`` preserves the existing global-preference behavior. A non-empty
    value is validated against the transcription registries and constructs a
    service bound to that model without mutating user preferences.
    """
    if model_id is None:
        return resolve_transcription_service()

    target_model_id = model_id.strip()
    if not target_model_id:
        raise InvalidTranscriptionModelOverride("model_id must not be empty")

    service_kind, canonical_model_id = _resolve_transcription_model_override(target_model_id)

    if service_kind == "openai_api":
        from api.services.transcription.backends.openai_whisper_api_service import (
            OpenAIWhisperAPITranscriptionService,
        )

        return OpenAIWhisperAPITranscriptionService(model_id=canonical_model_id)

    if service_kind == "parakeet":
        from api.services.transcription.backends.parakeet_service import (
            ParakeetTranscriptionService,
        )

        return ParakeetTranscriptionService(model_id=canonical_model_id)

    from api.services.transcription.backends.huggingface_service import (
        HuggingFaceTranscriptionService,
    )

    return HuggingFaceTranscriptionService(model_id=canonical_model_id)


def _resolve_transcription_model_override(
    target_model_id: str,
) -> Tuple[str, str]:
    from api.core.models.models_registry import (
        get_cloud_transcription_models,
        get_parakeet_transcription_models,
        get_transcription_models,
    )

    cloud_models = get_cloud_transcription_models()
    if target_model_id in cloud_models:
        return "openai_api", target_model_id

    parakeet_models = get_parakeet_transcription_models()
    parakeet_match = _match_registry_model(target_model_id, parakeet_models)
    if parakeet_match is not None:
        return "parakeet", parakeet_match

    transcription_models = get_transcription_models()
    huggingface_match = _match_registry_model(target_model_id, transcription_models)
    if huggingface_match is not None and huggingface_match not in parakeet_models:
        return "huggingface", huggingface_match

    raise InvalidTranscriptionModelOverride(
        f"Unknown transcription model id '{target_model_id}'. Must match a cloud, "
        f"Parakeet, or HuggingFace transcription registry entry."
    )


def _match_registry_model(
    target_model_id: str,
    registry: Dict[str, Dict[str, Any]],
) -> Optional[str]:
    for candidate_id, config in registry.items():
        if candidate_id == target_model_id or config.get("display_name") == target_model_id:
            return candidate_id
    return None
