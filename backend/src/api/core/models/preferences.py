"""User preferences models for FastAPI backend."""

from pathlib import Path
from typing import Dict, Optional, Tuple
import logging

from pydantic import BaseModel, Field

from .preference_models.browser_automation import (
    BrowserAutomationSessionMode,
    BrowserAutomationSettings,
    BrowserDomainApproval,
    BrowserForegroundControlPolicy,
    BrowserPreferredUserBrowser,
    BrowserSensitiveFillPolicy,
)
from .preference_models.defaults import (
    _get_anthropic_model_defaults,
    _get_gemini_model_defaults,
    _get_openai_model_defaults,
    _get_openai_transcription_model_defaults,
)
from .preference_models.execution_and_connections import (
    APIKeyPreference,
    ApprovalTimeoutBehavior,
    AuthSettings,
    BehaviorSettings,
    CommandPattern,
    ConnectionsSettings,
    ExecutionApprovalMode,
    MCPCachedTool,
    MCPConnectionRecord,
    MCPToolPolicy,
    MemoryIntelligenceSettings,
    ToolExecutionSettings,
    ZettelSettings,
)
from .preference_models.hotkeys import HotkeyBinding, HotkeySettings
from .preference_models.migrations import (
    _TEAM_IDENTITY_RENAME_KEY_MIGRATIONS,
    _migrate_legacy_keys_for_team_identity_rename,
    _normalize_api_key_preference,
    normalize_auth_preference_in_data,
)
from .preference_models.model_settings import ModelSettings
from .preference_models.persistence import (
    initialize_default_hotkeys,
    load_preferences_model,
    save_preferences_model,
)
from .preference_models.transcription import (
    ModelPersistenceDuration,
    TranscriptionModelUnloadDelay,
    TranscriptionSettings,
)
from .preference_models.ui_and_capture import (
    DEFAULT_PROCESSING_ACCENT,
    DEFAULT_PROCESSING_BASE,
    ActivityCaptureSettings,
    AmbientSuggestionSettings,
    AgentTaskPreferences,
    AssistantSessionPreferences,
    ConversationWidgetPreferences,
    GeneralSettings,
    MeetingDetectionSettings,
    UIPreferences,
)

logger = logging.getLogger(__name__)

# Constants
SETTINGS_DIR = Path.home() / ".basil" / "config"
SETTINGS_FILE = SETTINGS_DIR / "preferences.json"


class Preferences(BaseModel):
    """Application preferences."""
    general: GeneralSettings = Field(default_factory=GeneralSettings)
    models: ModelSettings = Field(default_factory=ModelSettings)
    behavior: BehaviorSettings = Field(default_factory=BehaviorSettings)
    ui: UIPreferences = Field(default_factory=UIPreferences)
    transcription: TranscriptionSettings = Field(default_factory=TranscriptionSettings)
    conversation_widget: ConversationWidgetPreferences = Field(default_factory=ConversationWidgetPreferences)
    agent_task: AgentTaskPreferences = Field(default_factory=AgentTaskPreferences)
    assistant_session: AssistantSessionPreferences = Field(default_factory=AssistantSessionPreferences)
    activity_capture: ActivityCaptureSettings = Field(default_factory=ActivityCaptureSettings)
    ambient_suggestions: AmbientSuggestionSettings = Field(default_factory=AmbientSuggestionSettings)
    meeting_detection: MeetingDetectionSettings = Field(default_factory=MeetingDetectionSettings)
    browser_automation: BrowserAutomationSettings = Field(default_factory=BrowserAutomationSettings)
    tool_execution: ToolExecutionSettings = Field(default_factory=ToolExecutionSettings)
    memory_intelligence: MemoryIntelligenceSettings = Field(default_factory=MemoryIntelligenceSettings)
    zettel: ZettelSettings = Field(default_factory=ZettelSettings)
    auth: AuthSettings = Field(default_factory=AuthSettings)
    connections: ConnectionsSettings = Field(default_factory=ConnectionsSettings)
    hotkeys: Dict[str, HotkeyBinding] = Field(default_factory=dict)
    window_position: Optional[Tuple[int, int]] = Field(default=None, description="Last known window position")

    def model_post_init(self, __context) -> None:
        """Ensure hotkeys are populated with defaults if empty."""
        initialize_default_hotkeys(self, logger)

    @classmethod
    def load(cls) -> 'Preferences':
        """Load preferences from file or return defaults. Ensures all hotkey fields are present."""
        return load_preferences_model(cls, SETTINGS_DIR, SETTINGS_FILE, logger)

    def save(self) -> None:
        """Save preferences to file."""
        save_preferences_model(self, SETTINGS_DIR, SETTINGS_FILE, logger)


__all__ = [
    "APIKeyPreference",
    "ActivityCaptureSettings",
    "AmbientSuggestionSettings",
    "AgentTaskPreferences",
    "ApprovalTimeoutBehavior",
    "AssistantSessionPreferences",
    "AuthSettings",
    "BehaviorSettings",
    "BrowserAutomationSessionMode",
    "BrowserAutomationSettings",
    "BrowserDomainApproval",
    "BrowserForegroundControlPolicy",
    "BrowserPreferredUserBrowser",
    "BrowserSensitiveFillPolicy",
    "CommandPattern",
    "ConnectionsSettings",
    "ConversationWidgetPreferences",
    "DEFAULT_PROCESSING_ACCENT",
    "DEFAULT_PROCESSING_BASE",
    "ExecutionApprovalMode",
    "GeneralSettings",
    "HotkeyBinding",
    "HotkeySettings",
    "MCPCachedTool",
    "MCPConnectionRecord",
    "MCPToolPolicy",
    "MeetingDetectionSettings",
    "MemoryIntelligenceSettings",
    "ModelPersistenceDuration",
    "ModelSettings",
    "Preferences",
    "SETTINGS_DIR",
    "SETTINGS_FILE",
    "ToolExecutionSettings",
    "TranscriptionModelUnloadDelay",
    "TranscriptionSettings",
    "UIPreferences",
    "_TEAM_IDENTITY_RENAME_KEY_MIGRATIONS",
    "_get_anthropic_model_defaults",
    "_get_gemini_model_defaults",
    "_get_openai_model_defaults",
    "_get_openai_transcription_model_defaults",
    "_migrate_legacy_keys_for_team_identity_rename",
    "_normalize_api_key_preference",
    "normalize_auth_preference_in_data",
]
