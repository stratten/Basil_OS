"""Preference migrations and legacy value normalization."""

import logging
from typing import Any

logger = logging.getLogger(__name__)

_ZETTEL_SOURCE_ADDITIONS_BY_CATALOG_VERSION = {
    1: ("meeting",),
}


# Mapping of legacy preference key -> new preference key, per JSON path.
# Tuples are (parent_section, legacy_name, new_name); a None parent means
# the key lives directly on the top-level Preferences object. Used by
# ``_migrate_legacy_keys_for_team_identity_rename``.
_TEAM_IDENTITY_RENAME_KEY_MIGRATIONS = [
    # Legacy suggestion keys.
    ("ui", "suggestion_widget_position", "assistant_session_widget_position"),
    ("ui", "suggestion_widget_size", "assistant_session_widget_size"),
    ("models", "close_suggestion_on_insert", "close_assistant_session_on_insert"),
    ("models", "auto_paste_suggestion", "auto_paste_assistant_output"),
    ("hotkeys", "insert_suggestion", "insert_assistant_output"),
    ("hotkeys", "minion", "agent_task"),
    (None, "minion", "agent_task"),
]


def _migrate_legacy_keys_for_team_identity_rename(data: dict) -> None:
    """Rewrite legacy preference keys to durable names in-place.

    Idempotent: if the new key already exists in a section, the legacy
    entry is dropped without overwriting (the user has presumably already
    written via the new name). If only the legacy key exists, it is
    moved to the new name. Missing sections are silently skipped.
    """
    migrated = []
    for section, legacy_name, new_name in _TEAM_IDENTITY_RENAME_KEY_MIGRATIONS:
        section_data = data if section is None else data.get(section)
        if not isinstance(section_data, dict):
            continue
        if legacy_name not in section_data:
            continue
        if new_name in section_data:
            section_data.pop(legacy_name, None)
            key_path = legacy_name if section is None else f"{section}.{legacy_name}"
            migrated.append(f"{key_path} (dropped; new key already set)")
            continue
        section_data[new_name] = section_data.pop(legacy_name)
        old_path = legacy_name if section is None else f"{section}.{legacy_name}"
        new_path = new_name if section is None else f"{section}.{new_name}"
        migrated.append(f"{old_path} -> {new_path}")

    if migrated:
        logger.info(
            f"📦 Team identity rename: migrated {len(migrated)} legacy preference keys: {migrated}"
        )


def migrate_assistant_output_paste_mode_in_data(data: dict) -> None:
    """Replace the legacy ``models.auto_paste_assistant_output`` boolean with ``models.assistant_output_paste_mode``.

    False maps to "never"; True (and any other legacy value) maps to "always". When the new key is already present the legacy key is dropped without overwriting it. Must run after ``_migrate_legacy_keys_for_team_identity_rename`` so the older ``auto_paste_suggestion`` name has already been renamed.
    """
    models = data.get("models")
    if not isinstance(models, dict) or "auto_paste_assistant_output" not in models:
        return
    legacy_value = models.pop("auto_paste_assistant_output")
    if "assistant_output_paste_mode" in models:
        return
    models["assistant_output_paste_mode"] = "never" if legacy_value is False else "always"
    logger.info(
        f"📦 Migrated models.auto_paste_assistant_output={legacy_value!r} -> "
        f"assistant_output_paste_mode={models['assistant_output_paste_mode']}"
    )


def normalize_auth_preference_in_data(data: dict) -> None:
    """Normalize legacy auth api-key preference aliases in raw preference data."""
    from .execution_and_connections import APIKeyPreference

    auth_settings = data.get("auth")
    if isinstance(auth_settings, dict):
        legacy_preference = auth_settings.get("api_key_preference")
        if legacy_preference in {APIKeyPreference.APP_KEYS.value, APIKeyPreference.TRIAL.value}:
            auth_settings["api_key_preference"] = APIKeyPreference.BASIL_CLOUD.value
            logger.info(
                "🔐 Migrated legacy auth api_key_preference "
                f"{legacy_preference} → {APIKeyPreference.BASIL_CLOUD.value}"
            )


def migrate_zettel_source_catalog_in_data(data: dict) -> bool:
    """Enable newly introduced default zettel sources exactly once.

    ``enabled_sources`` is an explicit user preference, so simply filling a
    missing source on every load would make it impossible to turn that source
    off. The persisted catalog version separates an older file that predates a
    source from a current file where the user deliberately disabled it.
    """
    from .execution_and_connections import ZETTEL_SOURCE_CATALOG_VERSION

    zettel = data.get("zettel")
    if not isinstance(zettel, dict):
        return False

    try:
        current_version = int(zettel.get("source_catalog_version", 0))
    except (TypeError, ValueError):
        current_version = 0
    if current_version >= ZETTEL_SOURCE_CATALOG_VERSION:
        return False

    enabled_sources = zettel.get("enabled_sources")
    if isinstance(enabled_sources, list):
        additions = [
            source
            for version in range(current_version + 1, ZETTEL_SOURCE_CATALOG_VERSION + 1)
            for source in _ZETTEL_SOURCE_ADDITIONS_BY_CATALOG_VERSION.get(version, ())
        ]
        zettel["enabled_sources"] = [
            *enabled_sources,
            *(
                source
                for source in additions
                if source not in enabled_sources
            ),
        ]
    zettel["source_catalog_version"] = ZETTEL_SOURCE_CATALOG_VERSION
    logger.info(
        "Migrated zettel source catalog to version %s",
        ZETTEL_SOURCE_CATALOG_VERSION,
    )
    return True


# Models removed from the registry because their provider or OpenRouter retires them (OpenAI 2026-10-23 and 2027-01-14, Anthropic 2026-11-30, Gemini 2.5 on OpenRouter 2026-10-20), mapped to the model a saved preference should use instead. Targets follow each provider's published replacement, except that the GPT-4o Mini and GPT-4.1 Mini family moves to GPT-5.4 Mini by owner decision. No target is itself scheduled for shutdown. The dated GPT-4o snapshots were never registry entries but can be saved by hand or through a custom setup.
RETIRED_CLOUD_MODEL_REPLACEMENTS = {
    # OpenAI, retired on 2027-01-14.
    "gpt-4o-mini": "gpt-5.4-mini",
    "gpt-4o-mini-2024-07-18": "gpt-5.4-mini",
    "gpt-4.1-mini": "gpt-5.4-mini",
    "gpt-4.1-mini-2025-04-14": "gpt-5.4-mini",
    "gpt-4o": "gpt-6-luna",
    "gpt-4o-2024-05-13": "gpt-6-luna",
    "gpt-4o-2024-08-06": "gpt-6-luna",
    "gpt-4o-2024-11-20": "gpt-6-luna",
    "gpt-4.1": "gpt-6-luna",
    "gpt-4.1-2025-04-14": "gpt-6-luna",
    # OpenAI, retired on 2026-10-23.
    "o1": "gpt-5.6-sol",
    "o3-mini": "gpt-5.6-sol",
    "o4-mini": "gpt-5.6-terra",
    "gpt-4.1-nano": "gpt-5.6-luna",
    "gpt-4-turbo": "gpt-5.6-sol",
    # Google, expired on OpenRouter 2026-10-20 or never a valid id.
    "gemini-2.5-pro": "gemini-3.1-pro-preview",
    "gemini-2.5-flash": "gemini-3.8-flash",
    "gemini-3-flash": "gemini-3.8-flash",
    # Anthropic, retired on 2026-11-30.
    "claude-sonnet-4-5-20250929": "claude-sonnet-5-5",
}

# (section, field) pairs in the raw preference JSON that hold a registry model id and are read by background services that have no fallback for an unknown id.
_MODEL_ID_PREFERENCE_FIELDS = (
    ("models", "reasoning_model"),
    ("models", "reasoning_fallback_model_id"),
    ("models", "language_model"),
    ("models", "vision_model"),
    ("activity_capture", "processing_model"),
    ("ambient_suggestions", "evaluation_model"),
    ("memory_intelligence", "memory_processing_model"),
    ("memory_intelligence", "skill_processing_model"),
    ("zettel", "narrative_model"),
)


def migrate_retired_cloud_model_ids_in_data(data: dict) -> bool:
    """Replace saved references to retired cloud models with their registry replacements, in place.

    Returns True when anything changed so the caller can persist the file. Only exact matches are rewritten, so a custom or local model id is never touched, and running it again changes nothing.
    """
    migrated = []
    for section, field in _MODEL_ID_PREFERENCE_FIELDS:
        section_data = data.get(section)
        if not isinstance(section_data, dict):
            continue
        current = section_data.get(field)
        replacement = RETIRED_CLOUD_MODEL_REPLACEMENTS.get(current) if isinstance(current, str) else None
        if replacement is None:
            continue
        section_data[field] = replacement
        migrated.append(f"{section}.{field}: {current} -> {replacement}")

    if migrated:
        logger.info(f"📦 Retired cloud models: migrated {len(migrated)} saved model preferences: {migrated}")
    return bool(migrated)


def _normalize_api_key_preference(value: Any):
    """Collapse legacy cloud preference values into the canonical Basil Cloud mode."""
    from .execution_and_connections import APIKeyPreference

    preference = value if isinstance(value, APIKeyPreference) else APIKeyPreference(value)
    if preference in {APIKeyPreference.APP_KEYS, APIKeyPreference.TRIAL}:
        return APIKeyPreference.BASIL_CLOUD
    return preference
