"""Persistence helpers for the public Preferences model."""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Type

from .defaults import (
    _get_anthropic_model_defaults,
    _get_gemini_model_defaults,
    _get_openai_model_defaults,
    _get_openai_transcription_model_defaults,
)
from .hotkeys import HotkeySettings
from .migrations import (
    _migrate_legacy_keys_for_team_identity_rename,
    _normalize_api_key_preference,
    migrate_zettel_source_catalog_in_data,
    normalize_auth_preference_in_data,
)


def initialize_default_hotkeys(preferences: Any, logger: logging.Logger) -> None:
    """Ensure hotkeys are populated with defaults if empty."""
    if not preferences.hotkeys:
        logger.info("🔑 HOTKEY INIT: Empty hotkeys detected, populating with defaults")
        default_hotkeys = HotkeySettings()
        for field in HotkeySettings.model_fields:
            preferences.hotkeys[field] = getattr(default_hotkeys, field)
        logger.info(f"🔑 HOTKEY INIT: Populated {len(preferences.hotkeys)} default hotkey bindings")
        for key, binding in preferences.hotkeys.items():
            logger.debug(f"🔑 HOTKEY INIT: {key} -> {binding.key} (enabled: {binding.enabled})")
    else:
        logger.debug(f"🔑 HOTKEY INIT: Hotkeys already populated ({len(preferences.hotkeys)} bindings)")


def load_preferences_model(
    preferences_cls: Type,
    settings_dir: Path,
    settings_file: Path,
    logger: logging.Logger,
):
    """Load preferences from file or return defaults. Ensures all hotkey fields are present."""
    try:
        logger.debug(f"📂 Loading preferences from {settings_file}")
        settings_dir.mkdir(parents=True, exist_ok=True)
        if settings_file.exists():
            data = json.loads(settings_file.read_text())
            logger.debug(f"📄 Loaded preferences data keys: {list(data.keys())}")

            # Team identity rename on-read migration. Old preference files
            # written before the rename use the legacy key names; map them
            # to the new durable capability names in-place so model_validate
            # sees the new shape and existing user customisations survive.
            # Idempotent: if the new name is already present, the legacy
            # entry is dropped without overwriting.
            _migrate_legacy_keys_for_team_identity_rename(data)
            normalize_auth_preference_in_data(data)
            zettel_catalog_updated = migrate_zettel_source_catalog_in_data(data)
            models_data = data.get("models")
            vision_model_migrated = (
                isinstance(models_data, dict)
                and models_data.get("vision_model") == "vikhyatk/moondream2"
            )
            if vision_model_migrated:
                models_data["vision_model"] = ""
                logger.info("🤖 VISION MODEL MIGRATE: Cleared obsolete Moondream default")

            # Log hotkeys section specifically
            if 'hotkeys' in data:
                logger.info(f"🔑 HOTKEY LOAD: Found hotkeys section with {len(data['hotkeys'])} entries")
                for key, binding in data['hotkeys'].items():
                    logger.debug(f"🔑 HOTKEY LOAD: {key} -> {binding}")
            else:
                logger.info("🔑 HOTKEY LOAD: No hotkeys section found in preferences file")

            preferences = preferences_cls.model_validate(data)
            logger.debug("✅ Successfully parsed preferences")

            if zettel_catalog_updated:
                logger.info("💾 ZETTEL SAVE: Saving preferences with updated source catalog")
                preferences.save()

            # Ensure all hotkey fields are present (dict key check)
            default_hotkeys = HotkeySettings()
            hotkeys_updated = False
            missing_hotkeys = []
            for field in HotkeySettings.model_fields:
                if field not in preferences.hotkeys:
                    preferences.hotkeys[field] = getattr(default_hotkeys, field)
                    hotkeys_updated = True
                    missing_hotkeys.append(field)
                    logger.debug(f"🔑 Added missing hotkey: {field}")

            if missing_hotkeys:
                logger.info(f"🔑 HOTKEY POPULATE: Added {len(missing_hotkeys)} missing hotkeys: {missing_hotkeys}")

            # If we added any hotkeys, save the updated preferences
            if hotkeys_updated:
                logger.info("💾 HOTKEY SAVE: Saving preferences with populated hotkey defaults")
                preferences.save()
                logger.info("✅ HOTKEY SAVE: Successfully saved preferences with hotkey defaults")
            else:
                logger.debug("🔑 HOTKEY LOAD: All hotkeys already present, no save needed")

            # Ensure all model fields are present (for API models).
            # Uses helper functions that merge registry + legacy defaults.
            models_updated = vision_model_migrated
            missing_anthropic_models = []
            missing_openai_models = []
            missing_gemini_models = []

            # Get merged defaults (registry overrides legacy).
            anthropic_defaults = _get_anthropic_model_defaults()
            openai_defaults = _get_openai_model_defaults()
            gemini_defaults = _get_gemini_model_defaults()

            # Check for missing Anthropic models.
            for model_id, default_enabled in anthropic_defaults.items():
                if model_id not in preferences.models.anthropic_models:
                    preferences.models.anthropic_models[model_id] = default_enabled
                    models_updated = True
                    missing_anthropic_models.append(model_id)
                    logger.debug(f"🤖 Added missing Anthropic model: {model_id}")

            # Check for missing OpenAI models.
            for model_id, default_enabled in openai_defaults.items():
                if model_id not in preferences.models.openai_models:
                    preferences.models.openai_models[model_id] = default_enabled
                    models_updated = True
                    missing_openai_models.append(model_id)
                    logger.debug(f"🤖 Added missing OpenAI model: {model_id}")

            # Check for missing Gemini models.
            for model_id, default_enabled in gemini_defaults.items():
                if model_id not in preferences.models.gemini_models:
                    preferences.models.gemini_models[model_id] = default_enabled
                    models_updated = True
                    missing_gemini_models.append(model_id)
                    logger.debug(f"🤖 Added missing Gemini model: {model_id}")

            if missing_anthropic_models:
                logger.info(f"🤖 MODEL POPULATE: Added {len(missing_anthropic_models)} missing Anthropic models: {missing_anthropic_models}")

            if missing_openai_models:
                logger.info(f"🤖 MODEL POPULATE: Added {len(missing_openai_models)} missing OpenAI models: {missing_openai_models}")

            if missing_gemini_models:
                logger.info(f"🤖 MODEL POPULATE: Added {len(missing_gemini_models)} missing Gemini models: {missing_gemini_models}")

            # Check for missing OpenAI transcription API models.
            missing_openai_transcription_models = []
            openai_transcription_defaults = _get_openai_transcription_model_defaults()
            for model_id, default_enabled in openai_transcription_defaults.items():
                if model_id not in preferences.models.openai_transcription_models:
                    preferences.models.openai_transcription_models[model_id] = default_enabled
                    models_updated = True
                    missing_openai_transcription_models.append(model_id)
                    logger.debug(f"🤖 Added missing OpenAI transcription model: {model_id}")

            if missing_openai_transcription_models:
                logger.info(f"🤖 MODEL POPULATE: Added {len(missing_openai_transcription_models)} missing OpenAI transcription models: {missing_openai_transcription_models}")

            # If we added any models, save the updated preferences.
            if models_updated:
                logger.info("💾 MODEL SAVE: Saving preferences with populated model defaults")
                preferences.save()
                logger.info("✅ MODEL SAVE: Successfully saved preferences with model defaults")
            else:
                logger.debug("🤖 MODEL LOAD: All models already present, no save needed")

            logger.info(f"🔑 FINAL STATE: Loaded preferences with {len(preferences.hotkeys)} hotkey bindings")
            return preferences
        logger.info("ℹ️ No existing preferences found, using defaults")
        new_prefs = preferences_cls()
        logger.info(f"🔑 NEW PREFS: Created new preferences with {len(new_prefs.hotkeys)} hotkey bindings")
        return new_prefs
    except Exception as e:
        logger.error(f"❌ Error loading preferences: {e}", exc_info=True)
        _preserve_unreadable_preferences_file(settings_file, logger)
        fallback_prefs = preferences_cls()
        logger.info(f"🔑 FALLBACK: Created fallback preferences with {len(fallback_prefs.hotkeys)} hotkey bindings")
        return fallback_prefs


def _preserve_unreadable_preferences_file(settings_file: Path, logger: logging.Logger) -> None:
    """Back up a preferences file that failed to load instead of letting the
    in-memory fallback silently overwrite it on the next save.

    Without this, a single transient read/parse failure (for example a
    backend crash mid-write truncating the JSON, or one malformed field)
    causes ``load_preferences_model`` to return brand-new defaults; the very
    next unrelated settings write then persists those defaults over the
    original file, permanently losing every previously-saved preference
    (this is how a set of registered remote MCP connections disappeared in
    practice). Preserving the original bytes under a timestamped ``.bak``
    sibling makes a load failure recoverable instead of silently
    destructive, without changing the fallback-to-defaults behavior itself.
    """
    if not settings_file.exists():
        return
    timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    backup_path = settings_file.with_name(f"{settings_file.name}.unreadable-{timestamp}.bak")
    try:
        backup_path.write_bytes(settings_file.read_bytes())
        logger.error(f"🛑 Preserved unreadable preferences file at {backup_path} before falling back to defaults")
    except Exception as backup_error:
        logger.error(
            f"❌ Could not preserve unreadable preferences file {settings_file}: {backup_error}",
            exc_info=True,
        )


def save_preferences_model(preferences: Any, settings_dir: Path, settings_file: Path, logger: logging.Logger) -> None:
    """Save preferences to file."""
    try:
        logger.debug(f"💾 Saving preferences to {settings_file}")
        settings_dir.mkdir(parents=True, exist_ok=True)
        preferences.auth.api_key_preference = _normalize_api_key_preference(preferences.auth.api_key_preference)

        # Convert to JSON and log
        json_data = preferences.model_dump_json()
        logger.debug(f"📄 Preferences data to save: {json_data}")

        # Write to file
        settings_file.write_text(json_data)
        logger.info("✅ Successfully saved preferences to file")
    except Exception as e:
        logger.error(f"❌ Error saving preferences: {e}", exc_info=True)
        raise
