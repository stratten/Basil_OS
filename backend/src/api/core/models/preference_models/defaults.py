"""Registry-backed default helpers for preference models."""

from typing import Dict, NamedTuple, Optional

from ..model_download.disk_space import (
    detected_free_disk_gb,
    download_disk_required_gb,
)


def _get_anthropic_model_defaults() -> Dict[str, bool]:
    """Get Anthropic model defaults from the unified registry."""
    try:
        from ..models_registry import get_default_enabled_for_provider, PROVIDER_ANTHROPIC
        return get_default_enabled_for_provider(PROVIDER_ANTHROPIC)
    except Exception:
        return {}


def _get_openai_model_defaults() -> Dict[str, bool]:
    """Get OpenAI model defaults from the unified registry."""
    try:
        from ..models_registry import get_default_enabled_for_provider, PROVIDER_OPENAI
        return get_default_enabled_for_provider(PROVIDER_OPENAI)
    except Exception:
        return {}


def _get_gemini_model_defaults() -> Dict[str, bool]:
    """Get Gemini model defaults from the unified registry."""
    try:
        from ..models_registry import get_default_enabled_for_provider, PROVIDER_GOOGLE
        return get_default_enabled_for_provider(PROVIDER_GOOGLE)
    except Exception:
        return {}


def _detected_total_ram_gb() -> Optional[int]:
    """Total physical memory of this machine in whole GB, or None when it cannot be read."""
    try:
        from ...runtime.hardware_capability_service import HardwareCapabilityService
        return int(HardwareCapabilityService().get_profile().total_ram_gb)
    except Exception:
        return None


#: Registry id of the first model the starter pack downloads for transcription. The default selection must be a model the first-run download actually installs, because the picker lists installed models by display name.
STARTER_TRANSCRIPTION_MODEL_REGISTRY_ID = "OpenAI-whisper-tiny.en"
_STARTER_TRANSCRIPTION_MODEL_FALLBACK_NAME = "Whisper Tiny (English)"
#: Display name of the Whisper base model, which the retired "base" default was shorthand for.
LEGACY_BASE_TRANSCRIPTION_MODEL_NAME = "Whisper Base"


def _get_default_transcription_model_name() -> str:
    """Display name of the starter transcription model, which is what the Settings picker lists and what the transcription services resolve."""
    try:
        from ..models_registry import get_model
        entry = get_model(STARTER_TRANSCRIPTION_MODEL_REGISTRY_ID)
        name = entry.get("display_name") if entry else None
        return name or _STARTER_TRANSCRIPTION_MODEL_FALLBACK_NAME
    except Exception:
        return _STARTER_TRANSCRIPTION_MODEL_FALLBACK_NAME


class LocalReasoningChoice(NamedTuple):
    """The local reasoning model chosen for this Mac, and the larger one that disk space ruled out, if any."""

    model_id: str
    #: The model this Mac's memory alone would choose. It differs from ``model_id`` only when the Mac has the memory for the larger upgrade but not the free disk space to download it.
    preferred_model_id: str
    free_disk_gb: Optional[float]
    #: Free space needed to download ``preferred_model_id``, or None when no upgrade was in play.
    required_disk_gb: Optional[float]

    @property
    def blocked_by_disk(self) -> bool:
        return self.model_id != self.preferred_model_id


def _detected_free_disk_gb() -> Optional[float]:
    """Free space in GB on the volume that holds Basil's models folder, or None when it cannot be read."""
    return detected_free_disk_gb()


def _download_disk_required_gb(size: object) -> Optional[float]:
    """Free space in GB needed to download a model whose registry size reads like "20GB" or "5.6GB", or None when the size cannot be read."""
    return download_disk_required_gb(size)


def _choose_local_reasoning_model(
    total_ram_gb: Optional[int] = None,
    free_disk_gb: Optional[float] = None,
) -> LocalReasoningChoice:
    """Choose the local reasoning model flagged recommended_for_onboarding for this Mac's memory and free disk space.

    A flagged model that declares ``onboarding_min_ram_gb`` is replaced by its ``onboarding_low_memory_fallback`` on a machine with less memory than that, so a first-run Mac is never handed a model it cannot run well. A flagged model that declares ``onboarding_high_memory_upgrade`` and ``onboarding_upgrade_min_ram_gb`` is replaced by that larger model on a machine with at least that much memory, when the upgrade is available on this runtime and the volume has the free space to download it. When memory allows the upgrade but disk space does not, the flagged model is chosen and the result records the upgrade as preferred, so setup can tell the user what to free. ``total_ram_gb`` and ``free_disk_gb`` default to this machine's values. An unreadable memory size leaves the flagged model in place, because an unknown machine is never offered the larger model, while an unreadable disk size does not block the upgrade, because the download itself reports a full disk and resumes.
    """
    empty = LocalReasoningChoice("", "", None, None)
    try:
        from ..models_registry import get_local_reasoning_models
        local_models = get_local_reasoning_models()
        flagged_id = next(
            (
                model_id
                for model_id, cfg in local_models.items()
                if cfg.get("recommended_for_onboarding") is True and "reasoning" in cfg.get("capabilities", [])
            ),
            "",
        )
        if not flagged_id:
            return empty
        cfg = local_models[flagged_id]
        ram_gb = total_ram_gb if total_ram_gb is not None else _detected_total_ram_gb()
        if ram_gb is None:
            return LocalReasoningChoice(flagged_id, flagged_id, None, None)
        upgrade_id = cfg.get("onboarding_high_memory_upgrade")
        upgrade_min_ram_gb = cfg.get("onboarding_upgrade_min_ram_gb")
        if upgrade_id in local_models and upgrade_min_ram_gb and ram_gb >= upgrade_min_ram_gb:
            required_gb = _download_disk_required_gb(local_models[upgrade_id].get("size"))
            free_gb = free_disk_gb if free_disk_gb is not None else _detected_free_disk_gb()
            if required_gb is not None and free_gb is not None and free_gb < required_gb:
                return LocalReasoningChoice(flagged_id, upgrade_id, free_gb, required_gb)
            return LocalReasoningChoice(upgrade_id, upgrade_id, free_gb, required_gb)
        min_ram_gb = cfg.get("onboarding_min_ram_gb")
        fallback_id = cfg.get("onboarding_low_memory_fallback")
        chosen_id = fallback_id if min_ram_gb and fallback_id in local_models and ram_gb < min_ram_gb else flagged_id
        return LocalReasoningChoice(chosen_id, chosen_id, None, None)
    except Exception:
        return empty


def _get_default_local_reasoning_model_id(
    total_ram_gb: Optional[int] = None,
    free_disk_gb: Optional[float] = None,
) -> str:
    """Get the registry id of the local reasoning model chosen for this Mac, or an empty string when none is flagged recommended_for_onboarding.

    This is the same selection the Setup Assistant uses, so a stored default and the model setup offers cannot disagree. An empty value means no preference, which every consumer already treats as unset. See ``_choose_local_reasoning_model`` for how memory and free disk space move the choice.
    """
    return _choose_local_reasoning_model(total_ram_gb=total_ram_gb, free_disk_gb=free_disk_gb).model_id


def _get_default_local_vision_model_id() -> str:
    """Get the registry id of the local vision model flagged default_local_vision_fallback, or an empty string when none is flagged."""
    try:
        from ..models_registry.local_vision_registry import LOCAL_VISION_MODELS
        return next(
            (model_id for model_id, cfg in LOCAL_VISION_MODELS.items() if cfg.get("default_local_vision_fallback") is True),
            "",
        )
    except Exception:
        return ""


def _get_openai_transcription_model_defaults() -> Dict[str, bool]:
    """Get OpenAI cloud transcription model defaults from the unified registry."""
    try:
        from ..models_registry import get_cloud_transcription_models
        return {
            model_id: cfg.get("default_enabled", False)
            for model_id, cfg in get_cloud_transcription_models().items()
            if cfg.get("provider") == "openai"
        }
    except Exception:
        return {}
