"""Who may change each Basil setting, decided once and reviewed by hand.

Every setting in the preference models appears here exactly once, or is covered by the curated Appearance entries in `entries.py`. A test fails when a setting is added to the models without being classified here, so a new setting is never silently exposed to agents and never silently invisible to them.

A setting is classified by the tier a change needs:
- cosmetic: applies at once and can be undone.
- behavioral: the user approves each change.
- privacy: the user approves each change, and it is never remembered. Used where the setting sends data off the Mac, records, listens, or widens what Basil may look at.
- human_only: an agent cannot change it. It is listed without its value, with the reason and where the user can change it.

A writable setting (anything except human_only) can also name an apply group. The Settings screens run extra code after saving some settings, and the same code must run when an agent changes them, or the change would be saved but not take effect until a restart.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple

from .manifest import Tier

GROUP_MODEL_RESIDENCY = "models_residency"
GROUP_ZETTEL = "zettel"
GROUP_MEETING_DETECTION = "meeting_detection"
GROUP_AMBIENT_SUGGESTIONS = "ambient_suggestions"

APPLY_GROUPS: Tuple[str, ...] = (
    "",
    GROUP_MODEL_RESIDENCY,
    GROUP_ZETTEL,
    GROUP_MEETING_DETECTION,
    GROUP_AMBIENT_SUGGESTIONS,
)

SECTION_LABELS: Dict[str, str] = {
    "general": "General",
    "models": "Models",
    "behavior": "Behavior",
    "ui": "Appearance",
    "transcription": "Transcription",
    "conversation_widget": "Conversation",
    "agent_task": "Agent Tasks",
    "assistant_session": "Assistant Session",
    "activity_capture": "Activity Capture",
    "ambient_suggestions": "Ambient Suggestions",
    "meeting_detection": "Meeting Detection",
    "browser_automation": "Browser Automation",
    "tool_execution": "Permissions",
    "memory_intelligence": "Memory",
    "zettel": "Unified Event Stream",
    "auth": "Account",
    "connections": "Connections",
}


@dataclass(frozen=True)
class FieldPolicy:
    tier: Tier
    group: str = ""
    reason: str = ""


POLICIES: Dict[str, FieldPolicy] = {}

_REASON_AUTHORITY = "It controls what Basil may do without asking, so an agent must not be able to widen its own permissions."
_REASON_MODEL_ID = "It needs a model id checked against the installed and available models, which arrives with the models package. Until then the user picks it from the model list."
_REASON_GEOMETRY = "It records where a window sits and how big it is, which the user sets by dragging it."
_REASON_STRUCTURED = "It holds a structured list or table, not a single value. A dedicated tool for it arrives with its area's package."
_REASON_NATIVE = "The Mac app applies it when the Settings screen saves it, and an agent's change would be saved without taking effect. It arrives with the native command channel."
_REASON_LIVE_SERVICE = "Changing it starts, stops or reschedules a live service, and the code that does that lives in the Settings route. It arrives with the capture package."
_REASON_ACCOUNT = "It is part of the user's account, sign-in or connections."


def _add(section: str, names: str, tier: Tier, group: str = "", reason: str = "") -> None:
    for name in names.split():
        path = f"{section}.{name}" if section else name
        if path in POLICIES:
            raise ValueError(f"Setting classified twice: {path}")
        if tier == Tier.HUMAN_ONLY and not reason:
            raise ValueError(f"A human-only setting needs a reason: {path}")
        POLICIES[path] = FieldPolicy(tier=tier, group=group, reason=reason)


_C, _B, _P, _H = Tier.COSMETIC, Tier.BEHAVIORAL, Tier.PRIVACY, Tier.HUMAN_ONLY

# general
_add("general", "date_display_style", _C)
_add("general", "has_completed_onboarding", _H, reason="It records whether first-run setup finished, and Basil sets it itself.")

# models
_add("models", "persistence_duration keep_loaded_while_window_open", _B, GROUP_MODEL_RESIDENCY)
_add("models", "local_vision_fallback_enabled reasoning_fallback_enabled api_extended_thinking close_assistant_session_on_insert assistant_output_paste_mode use_region_selection", _B)
_add("models", "use_api_models anthropic_enabled openai_enabled gemini_enabled use_api_transcription_models openai_transcription_enabled", _P)
_add("models", "vision_model language_model reasoning_model transcription_model local_vision_model_id reasoning_fallback_model_id", _H, reason=_REASON_MODEL_ID)
_add("models", "anthropic_models openai_models gemini_models openai_transcription_models", _H, reason=_REASON_STRUCTURED)

# behavior
_add("behavior", "start_on_startup show_notifications minimize_to_tray transcription_language hold_enabled hold_duration enable_monitoring_at_startup", _B)
_add("behavior", "enable_voice_listener_at_startup allow_mac_contacts_for_generation", _P)

# ui: the colors, text size, font, surface finish, blueprint reveal and chain expansion are curated in entries.py
_add("ui", "assistant_session_widget_position assistant_session_widget_size", _H, reason=_REASON_GEOMETRY)
_add("ui", "custom_appearance_themes", _H, reason=_REASON_STRUCTURED)

# transcription
_add("transcription", "auto_paste auto_close_on_paste language auto_retranscribe_on_stop auto_retranscribe_during_recording retranscribe_window_seconds auto_analyze_on_complete auto_analyze_custom_instructions auto_analyze_timing live_transcription_by_default", _B)
_add("transcription", "selected_model", _H, reason=_REASON_MODEL_ID)
_add("transcription", "model_unload_delay", _H, reason="Changing it also re-arms the loaded transcription model's idle timer, and that code is not shared with the Settings route yet.")
_add("transcription", "widget_size widget_position is_widget_minimized", _H, reason=_REASON_GEOMETRY)
_add("transcription", "enable_push_to_talk push_to_talk_threshold_ms", _H, reason=_REASON_NATIVE)
_add("transcription", "auto_analyze_modes text_replacements", _H, reason=_REASON_STRUCTURED)

# conversation_widget, agent_task, assistant_session
_add("conversation_widget", "default_conversation_only", _B)
_add("conversation_widget", "widget_size widget_position is_sidebar_collapsed", _H, reason=_REASON_GEOMETRY)
_add("agent_task", "default_input_modality auto_reopen_on_completion", _B)
_add("agent_task", "widget_position result_widget_size", _H, reason=_REASON_GEOMETRY)
_add("agent_task", "enable_push_to_talk push_to_talk_threshold_ms", _H, reason=_REASON_NATIVE)
_add("assistant_session", "default_input_modality", _B)
_add("assistant_session", "enable_push_to_talk push_to_talk_threshold_ms", _H, reason=_REASON_NATIVE)

# activity_capture
_add(
    "activity_capture",
    "enabled start_at_startup frequency_minutes processing_model processing_mode scheduled_processing_time processing_max_records max_file_age_days max_storage_mb auto_cleanup_enabled excluded_bundle_ids idle_threshold_seconds post_wake_grace_seconds contact_candidate_extraction_enabled",
    _H,
    reason=_REASON_LIVE_SERVICE,
)

# ambient_suggestions
_add("ambient_suggestions", "enabled mode", _P, GROUP_AMBIENT_SUGGESTIONS)
_add("ambient_suggestions", "minimum_confidence cooldown_minutes", _B, GROUP_AMBIENT_SUGGESTIONS)
_add("ambient_suggestions", "allow_cloud_evaluation", _P)
_add("ambient_suggestions", "panel_visible_on_launch", _B)
_add("ambient_suggestions", "frequency_minutes frequency_seconds", _H, reason="The two fields must change together and the Settings route keeps them in step, so it is changed there.")
_add("ambient_suggestions", "evaluation_model", _H, reason=_REASON_MODEL_ID)
_add("ambient_suggestions", "enabled_capabilities auto_execute_capabilities excluded_app_names", _H, reason=_REASON_STRUCTURED)
_add("ambient_suggestions", "panel_position panel_size", _H, reason=_REASON_GEOMETRY)

# meeting_detection
_add("meeting_detection", "enabled mode use_calendar_enrichment", _P, GROUP_MEETING_DETECTION)
_add("meeting_detection", "start_at_startup poll_seconds cooldown_minutes require_calendar_match auto_end inactivity_timeout_minutes calendar_join_lead_minutes calendar_join_grace_minutes", _B, GROUP_MEETING_DETECTION)
_add("meeting_detection", "excluded_bundle_ids excluded_app_names", _H, reason=_REASON_STRUCTURED)

# browser_automation
_add("browser_automation", "sensitive_fill_policy foreground_control_policy approved_sensitive_fill_domains", _H, reason=_REASON_AUTHORITY)
_add("browser_automation", "default_session_mode record_browser_action_trace allow_visual_fallback", _P)
_add("browser_automation", "preferred_user_browser show_action_highlights", _B)

# tool_execution: all of it is the permission system
_add(
    "tool_execution",
    "approval_mode whitelisted_commands show_full_command_in_prompt remember_choice_option auto_approve_read_only model_judges_command_safety block_dangerous_patterns dangerous_patterns safe_execution_mode approval_timeout_seconds timeout_behavior",
    _H,
    reason=_REASON_AUTHORITY,
)

# memory_intelligence
_add("memory_intelligence", "memory_after_task_enabled memory_daily_enabled memory_daily_time_local skill_after_task_enabled skill_daily_enabled skill_daily_time_local skill_reconciliation_min_instances", _B)
_add("memory_intelligence", "memory_processing_model skill_processing_model", _H, reason=_REASON_MODEL_ID)

# zettel
_add("zettel", "history_days carding_enabled carding_interval_minutes limit_per_source_per_pass narrative_enabled narrative_reasoning_effort narrative_mode narrative_scheduled_time narrative_interval_minutes narrative_batch_size narrative_max_attempts narrative_max_records", _B, GROUP_ZETTEL)
_add("zettel", "narrative_model", _H, reason=_REASON_MODEL_ID)
_add("zettel", "enabled_sources", _H, reason=_REASON_STRUCTURED)
_add("zettel", "source_catalog_version", _H, reason="It is an internal version number that Basil maintains.")

# auth and connections
_add("auth", "api_key_preference is_authenticated user_email", _H, reason=_REASON_ACCOUNT)
_add("connections", "mcp_connections gmail_transport", _H, reason=_REASON_ACCOUNT)

# top-level settings that have no section
_add("", "hotkeys", _H, reason="Keyboard shortcuts are recorded by pressing the keys in Settings.")
_add("", "window_position", _H, reason=_REASON_GEOMETRY)

# Agent-facing wording for the few writable settings whose model field has no description of its own.
DESCRIPTION_OVERRIDES: Dict[str, str] = {
    "browser_automation.default_session_mode": "Which browser agents drive by default: user_browser (your own browser, with your sign-ins) or basil_automation_browser (a separate browser Basil controls).",
    "browser_automation.preferred_user_browser": "Which browser agents use when driving your own browser: system_default, chrome, edge or safari.",
    "browser_automation.show_action_highlights": "Whether the browser page shows a highlight around what the agent is about to click or fill.",
    "browser_automation.record_browser_action_trace": "Whether Basil keeps a step-by-step record of the browser actions an agent took.",
    "browser_automation.allow_visual_fallback": "Whether an agent may fall back to looking at a screenshot of the page when it cannot read the page's structure.",
}

# Allowed words for text settings that hold one of a few fixed values.
CHOICE_OVERRIDES: Dict[str, Tuple[str, ...]] = {
    "zettel.narrative_mode": ("scheduled", "continuous"),
    "zettel.narrative_reasoning_effort": ("none", "low", "medium", "high", ""),
}

# Settings that hold a local time as HH:MM.
TIME_OF_DAY_SETTINGS = frozenset(
    {
        "memory_intelligence.memory_daily_time_local",
        "memory_intelligence.skill_daily_time_local",
        "zettel.narrative_scheduled_time",
    }
)

# A setting whose name contains one of these words must be human-only, unless it is listed in REVIEWED_NAME_EXCEPTIONS with the reason it is safe.
SENSITIVE_NAME_WORDS: Tuple[str, ...] = ("token", "secret", "password", "credential", "whitelist", "allowlist", "permission", "policy", "approval", "approved", "auth", "api_key")
REVIEWED_NAME_EXCEPTIONS: Dict[str, str] = {}
