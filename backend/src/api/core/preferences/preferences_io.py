"""Shared preference persistence helpers.

API key lookups live in ``config.api_keys`` (OS-native credential store);
this module no longer reads or writes plaintext key material.
"""

from pathlib import Path

from api.core.logging.api_logger import api_logger
from api.core.models.preferences import Preferences

SETTINGS_DIR = Path.home() / ".config" / "basil"
SETTINGS_FILE = SETTINGS_DIR / "preferences.json"


def load_preferences() -> Preferences:
    """Load preferences from file or return defaults."""
    try:
        # Use the new consolidated Preferences.load() method which handles migration
        return Preferences.load()
    except Exception as e:
        api_logger.error(f"❌ Error loading preferences: {e}", exc_info=True)
        return Preferences()


def save_preferences(preferences: Preferences) -> None:
    """Save preferences to file."""
    try:
        # Use the new consolidated Preferences.save() method
        preferences.save()
        api_logger.info("✅ Successfully saved preferences to file")
    except Exception as e:
        api_logger.error(f"❌ Error saving preferences: {e}", exc_info=True)
        raise
