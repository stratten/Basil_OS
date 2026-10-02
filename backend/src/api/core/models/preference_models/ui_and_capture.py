"""UI, widget, capture, and general preference models."""

from typing import List, Literal, Optional, Tuple

from pydantic import BaseModel, Field, model_validator

# Processing-bubble color defaults are sourced from a single Swift literal
# in client/Sources/Support/AestheticSystem.swift. The canonical asset
# builder (scripts/build-agent-task-assets.sh)
# regenerates `generated_processing_colors.py` from that Swift source as its
# STEP 0 so this import always reflects the current Royal Purple values
# without any manual edit on the Python side.
from ..generated_processing_colors import (
    DEFAULT_PROCESSING_BASE,
    DEFAULT_PROCESSING_ACCENT,
)


class ConversationWidgetPreferences(BaseModel):
    """Conversation widget preferences."""
    widget_size: Tuple[int, int] = Field(
        default=(700, 600),
        description="Size of the conversation widget window (width, height)"
    )
    widget_position: Optional[Tuple[float, float, int]] = Field(
        default=None,
        description="Position of the conversation widget (x, y, screenID)"
    )
    is_sidebar_collapsed: bool = Field(
        default=False,
        description="Whether the conversation history sidebar is collapsed"
    )
    default_conversation_only: bool = Field(
        default=False,
        description="Whether new conversations start with Conversation only enabled, which keeps replies inline instead of delegating to an agent task"
    )


class AgentTaskPreferences(BaseModel):
    """Agent-task widget preferences."""
    widget_position: Optional[Tuple[float, float, int]] = Field(
        default=None,
        description="Position of the agent-task widget (x, y, screenID) - applies to all phases"
    )
    result_widget_size: Tuple[int, int] = Field(
        default=(320, 180),
        description="Size of the agent-task result widget (width, height) - capture widget uses fixed 140x140"
    )

    # Push-to-talk settings
    enable_push_to_talk: bool = Field(
        default=False,
        description="Enable push-to-talk mode for agent tasks (auto-process on key release after threshold)"
    )
    push_to_talk_threshold_ms: int = Field(
        default=750,
        description="Duration in milliseconds to trigger auto-process on key release (500-5000)"
    )

    # Default interaction modality
    default_input_modality: Literal["voice", "text"] = Field(
        default="voice",
        description="Default input modality when initiating an agent task (initial capture and new-agent task overlay). 'voice' starts mic capture; 'text' opens the text entry editor without starting the mic."
    )
    auto_reopen_on_completion: bool = Field(
        default=True,
        description="Whether a collapsed agent-task result window reopens when its focused task reaches a terminal outcome"
    )


class AssistantSessionPreferences(BaseModel):
    """Assistant-session preferences."""
    # Push-to-talk settings
    enable_push_to_talk: bool = Field(
        default=False,
        description="Enable push-to-talk mode for assistant-session output (auto-process on key release after threshold)"
    )
    push_to_talk_threshold_ms: int = Field(
        default=750,
        description="Duration in milliseconds to trigger auto-process on key release (500-5000)"
    )

    # Default interaction modality for the unified assistant-session widget.
    # Mirrors AgentTaskPreferences.default_input_modality structurally; the wire
    # string the client decodes here ("speak"/"type") differs from agent-task's
    # ("voice"/"text") because the client-side enum uses speak/type
    # which uses speak/type to read more naturally in the widget toggle.
    default_input_modality: Literal["speak", "type"] = Field(
        default="speak",
        description="Default input modality when initiating an assistant session. 'speak' starts mic capture immediately; 'type' opens the typed-input field without starting the mic. Either modality may be flipped at runtime via the widget header toggle."
    )


class ActivityCaptureSettings(BaseModel):
    """Activity capture configuration settings."""
    enabled: bool = Field(
        default=False,
        description="Whether activity capture is enabled (shows menu item)"
    )
    start_at_startup: bool = Field(
        default=False,
        description="Whether to start the automatic capture scheduler when Basil launches"
    )
    frequency_minutes: float = Field(
        default=5.0,
        description="Frequency of automatic captures in minutes (0.5-1440, supports fractional)"
    )
    processing_model: str = Field(
        default="upstage/SOLAR-10.7B-Instruct-v1.0",
        description="Model to use for processing captured activities"
    )
    processing_mode: str = Field(
        default="scheduled",
        description="Processing mode: 'real_time' or 'scheduled'"
    )
    scheduled_processing_time: str = Field(
        default="01:00",
        description="Time of day to process pending activities in scheduled mode (HH:MM format, default 01:00)"
    )
    processing_max_records: int = Field(
        default=0,
        ge=0,
        le=1000,
        description="Maximum captures processed in one run; 0 drains the eligible backlog.",
    )
    max_file_age_days: int = Field(
        default=30,
        description="Maximum age of capture files in days before cleanup"
    )
    max_storage_mb: int = Field(
        default=500,
        description="Maximum storage for capture files in MB"
    )
    auto_cleanup_enabled: bool = Field(
        default=True,
        description="Whether to automatically clean up old capture files"
    )
    excluded_bundle_ids: list[str] = Field(
        default_factory=list,
        description="macOS bundle identifiers excluded from automatic activity capture",
    )
    idle_threshold_seconds: float = Field(
        default=120.0,
        ge=0,
        description="Seconds of no keyboard or mouse input after which automatic activity capture is skipped",
    )
    post_wake_grace_seconds: float = Field(
        default=5.0,
        ge=0,
        description="Seconds after display wake or session unlock during which automatic activity capture is skipped",
    )
    contact_candidate_extraction_enabled: bool = Field(
        default=False,
        description=(
            "Allow Activity Capture post-processing to derive unverified contact "
            "identity observations from captured screen text. Observations are "
            "stored separately from learned contacts and never assert a "
            "relationship on their own."
        )
    )


class AmbientSuggestionSettings(BaseModel):
    """Ambient suggestion configuration settings."""
    enabled: bool = Field(
        default=False,
        description="Whether ambient suggestions are enabled"
    )
    frequency_minutes: float = Field(
        default=2.0,
        description="Frequency of ambient context checks in minutes"
    )
    frequency_seconds: float = Field(
        default=120.0,
        ge=1.0,
        description="Frequency of ambient context checks in seconds"
    )
    evaluation_model: str = Field(
        default="gpt-4o-mini",
        description="Model to use for evaluating whether a suggestion is useful"
    )
    mode: Literal["suggestion_only", "auto_execute"] = Field(
        default="suggestion_only",
        description="Whether to show suggestion cards or automatically execute eligible suggestions"
    )
    enabled_capabilities: List[Literal["assistant_session", "agent_task"]] = Field(
        default_factory=lambda: ["assistant_session"],
        description="Capabilities that ambient suggestions may propose"
    )
    auto_execute_capabilities: List[Literal["assistant_session", "agent_task"]] = Field(
        default_factory=list,
        description="Capabilities that may auto-execute when mode is auto_execute"
    )
    minimum_confidence: float = Field(
        default=0.8,
        ge=0.0,
        le=1.0,
        description="Minimum evaluator confidence required to surface a suggestion"
    )
    cooldown_minutes: float = Field(
        default=30.0,
        ge=0.0,
        description="Cooldown before suggesting the same action for the same context"
    )
    excluded_app_names: List[str] = Field(
        default_factory=list,
        description="Application names excluded from ambient suggestion capture"
    )
    allow_cloud_evaluation: bool = Field(
        default=False,
        description="Whether OCR/context text may be sent to cloud models for suggestion evaluation"
    )
    panel_position: Optional[Tuple[float, float, int]] = Field(
        default=None,
        description="Ambient suggestions panel position (x, y, screenID)"
    )
    panel_size: Tuple[int, int] = Field(
        default=(392, 152),
        description="Ambient suggestions panel size (width, height)"
    )
    panel_visible_on_launch: bool = Field(
        default=False,
        description="Whether to show the ambient suggestions panel when the app launches"
    )

    @model_validator(mode="after")
    def sync_frequency_fields(self) -> "AmbientSuggestionSettings":
        if "frequency_seconds" in self.model_fields_set:
            self.frequency_minutes = self.frequency_seconds / 60.0
        elif "frequency_minutes" in self.model_fields_set:
            self.frequency_seconds = self.frequency_minutes * 60.0
        return self


# Default meeting-app bundle identifiers monitored for audio activity. Native
# conferencing apps detect cleanly via CoreAudio IsRunningOutput; browsers are
# best-effort (any audio looks active) and are better confirmed via a calendar
# match (see require_calendar_match).
_DEFAULT_MEETING_EXCLUDED_BUNDLE_IDS: List[str] = [
    "com.stratten.basil",
]


class MeetingDetectionSettings(BaseModel):
    """Mechanical meeting-detection configuration.

    This is intentionally separate from AmbientSuggestionSettings: ambient
    suggestions are model-driven (each tick may cost an LLM evaluation, hence a
    relaxed cadence), whereas meeting detection is a couple of cheap CoreAudio
    HAL reads and runs on its own tight loop. It shares no store, record, or
    capability list with ambient suggestions.
    """
    enabled: bool = Field(
        default=False,
        description="Whether meeting detection is enabled"
    )
    start_at_startup: bool = Field(
        default=False,
        description="Automatically start the meeting-detection monitor when the application launches (no-op unless enabled)"
    )
    mode: Literal["prompt", "auto_start"] = Field(
        default="prompt",
        description="Whether to surface a prompt panel or auto-start transcription on detection"
    )
    poll_seconds: float = Field(
        default=10.0,
        ge=1.0,
        description="How often (seconds) the backend probes the client for meeting-app audio activity"
    )
    excluded_bundle_ids: List[str] = Field(
        default_factory=lambda: list(_DEFAULT_MEETING_EXCLUDED_BUNDLE_IDS),
        description="Bundle identifiers never treated as a meeting (Basil excludes itself by default)"
    )
    excluded_app_names: List[str] = Field(
        default_factory=list,
        description="Application names excluded from meeting detection"
    )
    cooldown_minutes: float = Field(
        default=10.0,
        ge=0.0,
        description="Cooldown before re-surfacing detection for the same app after dismissal/end"
    )
    use_calendar_enrichment: bool = Field(
        default=False,
        description="Whether to enrich detected meetings with the current calendar event (title/attendees)"
    )
    require_calendar_match: bool = Field(
        default=False,
        description="Only surface a detection when a calendar event is currently active (reduces false positives)"
    )
    auto_end: bool = Field(
        default=False,
        description="Whether to surface an end prompt when meeting-app audio stops for a sustained period"
    )
    inactivity_timeout_minutes: float = Field(
        default=2.0,
        ge=0.0,
        description="Sustained input+output absence before a detected meeting is considered ended (auto-end threshold)"
    )
    calendar_join_lead_minutes: float = Field(
        default=1.0,
        ge=0.0,
        description="Minutes before a joinable calendar event starts when Meeting Detection may surface a join prompt"
    )
    calendar_join_grace_minutes: float = Field(
        default=10.0,
        ge=0.0,
        description="Minutes after a joinable calendar event starts when Meeting Detection may still surface a join prompt"
    )


class CustomAppearanceThemeFields(BaseModel):
    """Palette and finish captured by a user-saved Appearance theme."""
    background_color_red: float = Field(ge=0.0, le=1.0)
    background_color_green: float = Field(ge=0.0, le=1.0)
    background_color_blue: float = Field(ge=0.0, le=1.0)
    primary_color_red: float = Field(ge=0.0, le=1.0)
    primary_color_green: float = Field(ge=0.0, le=1.0)
    primary_color_blue: float = Field(ge=0.0, le=1.0)
    secondary_color_red: float = Field(ge=0.0, le=1.0)
    secondary_color_green: float = Field(ge=0.0, le=1.0)
    secondary_color_blue: float = Field(ge=0.0, le=1.0)
    text_color_red: float = Field(ge=0.0, le=1.0)
    text_color_green: float = Field(ge=0.0, le=1.0)
    text_color_blue: float = Field(ge=0.0, le=1.0)
    surface_finish: Literal["flat", "metal"]


class CustomAppearanceTheme(CustomAppearanceThemeFields):
    """A named, deletable Appearance theme saved by the user."""
    id: str = Field(description="Server-generated identifier of the form 'custom-<32 lowercase hex characters>'.")
    name: str = Field(description="User-visible theme name, unique case-insensitively among custom themes.")


class UIPreferences(BaseModel):
    """User interface preferences."""
    assistant_session_widget_position: str = Field(default="top-right")
    assistant_session_widget_size: Tuple[int, int] = Field(default=(500, 450))

    # Appearance settings
    background_color_red: float = Field(default=0.0709251779736389, description="Background color red component (0.0-1.0)")
    background_color_green: float = Field(default=0.10432000903519285, description="Background color green component (0.0-1.0)")
    background_color_blue: float = Field(default=0.22791699626277573, description="Background color blue component (0.0-1.0)")
    primary_color_red: float = Field(default=0.21100852777444695, description="Primary color red component (0.0-1.0)")
    primary_color_green: float = Field(default=0.4699344845863317, description="Primary color green component (0.0-1.0)")
    primary_color_blue: float = Field(default=0.8893695758678611, description="Primary color blue component (0.0-1.0)")
    secondary_color_red: float = Field(default=0.376, description="Secondary color red component (0.0-1.0)")
    secondary_color_green: float = Field(default=0.647, description="Secondary color green component (0.0-1.0)")
    secondary_color_blue: float = Field(default=0.98, description="Secondary color blue component (0.0-1.0)")
    text_color_red: float = Field(default=0.9699399998499855, description="Text color red component (0.0-1.0)")
    text_color_green: float = Field(default=0.9902393003857255, description="Text color green component (0.0-1.0)")
    text_color_blue: float = Field(default=1.0, description="Text color blue component (0.0-1.0)")
    surface_finish: Literal["flat", "metal"] = Field(
        default="flat",
        description="Surface finish rendered by web-hosted panels: 'flat' (solid colors) or 'metal' (brushed-metal gradient and texture sheen layered over the active palette).",
    )

    # Processing bubble colors. These drive the AssistantSession/AgentTask/Transcription
    # "thinking" bubbles and any web-bridged processing bubble. Defaults are
    # sourced from the generated Royal Purple constants above (currently
    # #7C3AED base / #DDD6FE accent), chosen to remain distinct from Basil's
    # idle blue and from success/active green. To change the color, edit
    # the Swift literals in AestheticSystem.swift and re-run the canonical
    # asset builders -- never edit these defaults directly.
    processing_color_red: float = Field(default=DEFAULT_PROCESSING_BASE[0], description="Processing bubble base red component (0.0-1.0)")
    processing_color_green: float = Field(default=DEFAULT_PROCESSING_BASE[1], description="Processing bubble base green component (0.0-1.0)")
    processing_color_blue: float = Field(default=DEFAULT_PROCESSING_BASE[2], description="Processing bubble base blue component (0.0-1.0)")
    processing_accent_color_red: float = Field(default=DEFAULT_PROCESSING_ACCENT[0], description="Processing bubble accent red component (0.0-1.0)")
    processing_accent_color_green: float = Field(default=DEFAULT_PROCESSING_ACCENT[1], description="Processing bubble accent green component (0.0-1.0)")
    processing_accent_color_blue: float = Field(default=DEFAULT_PROCESSING_ACCENT[2], description="Processing bubble accent blue component (0.0-1.0)")

    preferred_font: str = Field(default="Helvetica-Light", description="Preferred font family")
    custom_appearance_themes: List[CustomAppearanceTheme] = Field(
        default_factory=list,
        description="User-saved Appearance themes shown after the built-in presets; only these can be deleted.",
    )


class GeneralSettings(BaseModel):
    """General application settings."""
    has_completed_onboarding: bool = Field(default=False, description="Indicates if the user has completed the initial onboarding flow")
    date_display_style: Literal["relative", "absolute"] = Field(
        default="relative",
        description="How timestamps render in history surfaces (conversation/meeting sidebars, agent-task history). 'relative' shows Today/Yesterday/weekday/short-date; 'absolute' shows a full yyyy-MM-dd date with time."
    )
