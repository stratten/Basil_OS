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


def _normalize_api_key_preference(value: Any):
    """Collapse legacy cloud preference values into the canonical Basil Cloud mode."""
    from .execution_and_connections import APIKeyPreference

    preference = value if isinstance(value, APIKeyPreference) else APIKeyPreference(value)
    if preference in {APIKeyPreference.APP_KEYS, APIKeyPreference.TRIAL}:
        return APIKeyPreference.BASIL_CLOUD
    return preference
