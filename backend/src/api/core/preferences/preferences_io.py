"""Shared preference and API key persistence helpers."""

import json
from pathlib import Path
from typing import Optional

from api.core.logging.api_logger import api_logger
from api.core.models.preferences import Preferences

SETTINGS_DIR = Path.home() / ".config" / "basil"
SETTINGS_FILE = SETTINGS_DIR / "preferences.json"
API_KEYS_FILE_PATH = Path.home() / ".basil" / "config" / "api_keys.json"


def get_api_key(provider: str) -> Optional[str]:
    """Retrieve an API key for a specific provider from the api_keys.json file."""
    if not API_KEYS_FILE_PATH.exists():
        api_logger.warning(f"API keys file not found at {API_KEYS_FILE_PATH}")
        return None
    try:
        keys_data = json.loads(API_KEYS_FILE_PATH.read_text())
        return keys_data.get(provider)
    except json.JSONDecodeError:
        api_logger.error(f"Error decoding API keys file: {API_KEYS_FILE_PATH}", exc_info=True)
        return None
    except Exception as e:
        api_logger.error(f"Error reading API key for {provider} from {API_KEYS_FILE_PATH}: {e}", exc_info=True)
        return None


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
