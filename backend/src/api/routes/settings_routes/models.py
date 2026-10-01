"""Models for core settings routes."""

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, model_validator


class BehaviorSettingsUpdate(BaseModel):
    """Model for updating behavior settings."""
    start_on_startup: Optional[bool] = None
    show_notifications: Optional[bool] = None
    minimize_to_tray: Optional[bool] = None
    hold_enabled: Optional[bool] = None
    hold_duration: Optional[float] = None
    enable_monitoring_at_startup: Optional[bool] = None
    enable_voice_listener_at_startup: Optional[bool] = None
    allow_mac_contacts_for_generation: Optional[bool] = None

    @model_validator(mode="after")
    def reject_explicit_null_values(self) -> "BehaviorSettingsUpdate":
        for field_name in self.model_fields_set:
            if getattr(self, field_name) is None:
                raise ValueError(f"{field_name} cannot be null")
        return self


class ModelSettingsUpdate(BaseModel):
    """Model for updating model settings."""
    transcription_model: str
    persistence_duration: int
    vision_model: str
    language_model: str
    reasoning_model: str
    local_vision_fallback_enabled: Optional[bool] = None
    local_vision_model_id: Optional[str] = None
    reasoning_fallback_enabled: Optional[bool] = None
    reasoning_fallback_model_id: Optional[str] = None
    
    # API model settings
    use_api_models: Optional[bool] = None
    
    # Anthropic settings
    anthropic_enabled: Optional[bool] = None
    anthropic_models: Dict[str, bool] = {}
    
    # OpenAI settings
    openai_enabled: Optional[bool] = None
    openai_models: Dict[str, bool] = {}
    
    # Special features
    api_extended_thinking: bool = False
    close_assistant_session_on_insert: bool = False
    auto_paste_assistant_output: bool = True
    use_region_selection: bool = False


class GeneralSettingsUpdate(BaseModel):
    """Model for updating general settings."""
    has_completed_onboarding: Optional[bool] = None
    date_display_style: Optional[Literal["relative", "absolute"]] = None


class MemoryIntelligenceSettingsUpdate(BaseModel):
    """Model for updating memory intelligence settings."""
    memory_after_task_enabled: Optional[bool] = None
    memory_daily_enabled: Optional[bool] = None
    memory_daily_time_local: Optional[str] = None
    memory_processing_model: Optional[str] = None
    skill_after_task_enabled: Optional[bool] = None
    skill_daily_enabled: Optional[bool] = None
    skill_daily_time_local: Optional[str] = None
    skill_processing_model: Optional[str] = None
    skill_reconciliation_min_instances: Optional[int] = None


class ZettelSettingsUpdate(BaseModel):
    """Model for updating unified event stream (zettel) settings."""
    enabled_sources: Optional[List[str]] = None
    history_days: Optional[int] = None
    carding_enabled: Optional[bool] = None
    carding_interval_minutes: Optional[int] = None
    limit_per_source_per_pass: Optional[int] = None
    narrative_enabled: Optional[bool] = None
    narrative_model: Optional[str] = None
    narrative_mode: Optional[str] = None
    narrative_scheduled_time: Optional[str] = None
    narrative_interval_minutes: Optional[int] = None
    narrative_batch_size: Optional[int] = None
    narrative_max_attempts: Optional[int] = None
    narrative_max_records: Optional[int] = None


class ZettelSourceStat(BaseModel):
    """Per-source counters for the Memories settings readout."""
    kind: str
    collected: int
    awaiting_collection: int


class ZettelStatsResponse(BaseModel):
    """Read-only progress counters for the unified stream (zettel)."""
    collected: int
    summarized: int
    awaiting_summary: int
    awaiting_retry: int
    failed: int
    awaiting_collection: int
    by_source: List[ZettelSourceStat]


class NarrativeProgressResponse(BaseModel):
    """Live progress of a manual/scheduled summarize (narrative) run."""
    active: bool
    total: int
    processed: int
    finalized: int
    still_open: int
    failed: int
    remaining: int
    eta_seconds: Optional[float] = None
    last_error: Optional[str] = None
    canceling: bool = False
    analysis_concurrency: int = 1
    processing_strategy: str = "sequential"


class AggregatedSettingsResponse(BaseModel):
    """Response model for aggregated settings."""
    hotkeys: Dict[str, Any]
    behavior: Dict[str, Any]
    models: Dict[str, Any]
