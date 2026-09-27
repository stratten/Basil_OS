"""Runtime model preference settings."""

from typing import Dict, Optional

from pydantic import BaseModel, Field

from .defaults import (
    _get_anthropic_model_defaults,
    _get_gemini_model_defaults,
    _get_openai_model_defaults,
    _get_openai_transcription_model_defaults,
)
from .transcription import ModelPersistenceDuration


class ModelSettings(BaseModel):
    """Model-specific settings for runtime management."""
    persistence_duration: int = Field(
        default=ModelPersistenceDuration.MINUTES_5.value,
        description="How long to keep models loaded after last use (in seconds)"
    )
    vision_model: str = Field(
        default="",
        description="Legacy vision default; empty because agent vision routing uses the active model or explicitly enabled local fallback."
    )
    local_vision_fallback_enabled: bool = Field(
        default=False,
        description=(
            "When True and the agent model has no native vision, allow analyze_with_vision "
            "using the manual-install local Qwen2.5-VL GGUF pair if present on disk."
        ),
    )
    local_vision_model_id: str = Field(
        default="Qwen-qwen25vl-7b-instruct-q4k",
        description=(
            "Registry model id for the local vision fallback (must match files in the models directory)."
        ),
    )
    reasoning_fallback_enabled: bool = Field(
        default=True,
        description=(
            "When True, if the preferred reasoning model cannot be reached at all "
            "(network unreachable, DNS failure, invalid/expired API key) on the very "
            "first request of a session/task, automatically retry once with a "
            "designated local reasoning model instead of failing outright. Does not "
            "apply once a request/task has already received at least one successful "
            "model response."
        ),
    )
    reasoning_fallback_model_id: str = Field(
        default="",
        description=(
            "Registry id of the installed local reasoning model to use for "
            "reasoning_fallback_enabled. Empty until the user designates one in "
            "Settings; fallback is skipped (treated as unavailable) when empty."
        ),
    )
    language_model: str = Field(
        default="qwen/qwen3-8b-instruct-q4km",
        description="Model to use for language processing tasks (can be either local or API model)"
    )
    reasoning_model: str = Field(
        default="qwen/qwen3-8b-instruct-q4km",
        description="Model to use for reasoning tasks (can be either local or API model)"
    )
    transcription_model: str = Field(
        default="base",
        description="Model to use for audio transcription"
    )

    # API model settings
    use_api_models: bool = Field(
        default=False,
        description="Master toggle for using API models"
    )

    # Anthropic settings.
    anthropic_enabled: bool = Field(
        default=False,
        description="Enable Anthropic API models"
    )
    anthropic_models: Dict[str, bool] = Field(
        default_factory=_get_anthropic_model_defaults,
        description="Which Anthropic models are enabled"
    )

    # OpenAI settings.
    openai_enabled: bool = Field(
        default=False,
        description="Enable OpenAI API models"
    )
    openai_models: Dict[str, bool] = Field(
        default_factory=_get_openai_model_defaults,
        description="Which OpenAI models are enabled"
    )

    # Google Gemini settings.
    gemini_enabled: bool = Field(
        default=False,
        description="Enable Google Gemini API models"
    )
    gemini_models: Dict[str, bool] = Field(
        default_factory=_get_gemini_model_defaults,
        description="Which Google Gemini models are enabled"
    )

    # API transcription model settings
    use_api_transcription_models: bool = Field(
        default=False,
        description="Master toggle for using API transcription models"
    )
    openai_transcription_enabled: bool = Field(
        default=False,
        description="Enable OpenAI API transcription models"
    )
    openai_transcription_models: Dict[str, bool] = Field(
        default_factory=_get_openai_transcription_model_defaults,
        description="Which OpenAI transcription API models are enabled"
    )

    # Special features
    api_extended_thinking: bool = Field(
        default=False,
        description="Enable extended thinking mode for supported models (like Claude 3.7)"
    )
    close_assistant_session_on_insert: bool = Field(
        default=False,
        description="Close assistant-session widget after inserting"
    )
    auto_paste_assistant_output: bool = Field(
        default=True,
        description="Automatically paste assistant output when complete"
    )
    use_region_selection: bool = Field(
        default=False,
        description="Enable manual screen region selection for assistant sessions instead of auto window capture"
    )

    @property
    def persistence_duration_enum(self) -> Optional[ModelPersistenceDuration]:
        """Get the persistence duration as an enum value."""
        return ModelPersistenceDuration.from_seconds(self.persistence_duration)

    @property
    def persistence_duration_display(self) -> str:
        """Get the human-readable persistence duration."""
        if enum_value := self.persistence_duration_enum:
            return enum_value.display_name
        return f"{self.persistence_duration} seconds"
