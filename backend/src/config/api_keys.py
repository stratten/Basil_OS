"""API key management backed by the operating-system credential store.

Only non-secret provider-selection metadata is written to local JSON. Provider
key values are stored through CredentialStore and are never migrated from the
legacy plaintext ``~/.basil/config/api_keys.json`` file.
"""

import json
import logging
import os
from pathlib import Path
from typing import Dict, Optional, Set

from dotenv import load_dotenv

from .credential_store import (
    CredentialStore,
    CredentialStoreUnavailableError,
    get_credential_store,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("api_keys")

USER_CONFIG_DIR = Path.home() / ".basil" / "config"
KEY_FLAGS_FILE = USER_CONFIG_DIR / "api_key_flags.json"

DEFAULT_API_KEYS: Dict[str, str] = {
    "anthropic": "",
    "openai": "",
    "google": "",
    "gemini": "",
}


class APIKeyManager:
    """Manage provider API keys using an OS-native credential store."""

    def __init__(self, credential_store: Optional[CredentialStore] = None):
        self._store = credential_store or get_credential_store()
        self.use_user_keys: Dict[str, bool] = {}
        self._custom_key_names: Set[str] = set()

        USER_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        load_dotenv()
        self._load_env_keys()
        self._load_flags()

    def _load_env_keys(self) -> None:
        env_anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
        if env_anthropic_key:
            DEFAULT_API_KEYS["anthropic"] = env_anthropic_key
            logger.info("Loaded Anthropic API key from environment")

        env_openai_key = os.environ.get("OPENAI_API_KEY")
        if env_openai_key:
            DEFAULT_API_KEYS["openai"] = env_openai_key
            logger.info("Loaded OpenAI API key from environment")

        env_google_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
        if env_google_key:
            DEFAULT_API_KEYS["google"] = env_google_key
            DEFAULT_API_KEYS["gemini"] = env_google_key
            logger.info("Loaded Google/Gemini API key from environment")

    def _load_flags(self) -> None:
        if not KEY_FLAGS_FILE.exists():
            return

        try:
            with KEY_FLAGS_FILE.open("r") as file:
                data = json.load(file)
            self.use_user_keys = data.get("use_user_keys", {})
            self._custom_key_names = set(data.get("custom_key_names", []))
        except Exception as exc:
            logger.error("Error loading API-key flags: %s", exc)

    def _save_flags(self) -> None:
        try:
            with KEY_FLAGS_FILE.open("w") as file:
                json.dump(
                    {
                        "use_user_keys": self.use_user_keys,
                        "custom_key_names": sorted(self._custom_key_names),
                    },
                    file,
                    indent=2,
                )
        except Exception as exc:
            logger.error("Error saving API-key flags: %s", exc)

    def _read_user_key(self, service: str) -> Optional[str]:
        try:
            return self._store.read(service)
        except CredentialStoreUnavailableError:
            return None

    def get_api_key(self, service: str) -> str:
        if self.use_user_keys.get(service, False):
            key = self._read_user_key(service)
            if key and key.strip():
                return key

        if service in DEFAULT_API_KEYS and DEFAULT_API_KEYS[service]:
            return DEFAULT_API_KEYS[service]

        raise ValueError(f"No API key available for {service}")

    def set_user_api_key(self, service: str, key: str) -> None:
        if not key:
            self.clear_user_api_key(service)
            return

        self._store.save(service, key)
        self.use_user_keys[service] = True
        if service not in DEFAULT_API_KEYS:
            self._custom_key_names.add(service)
        self._save_flags()
        logger.info("Set user API key for %s", service)

    def clear_user_api_key(self, service: str) -> None:
        try:
            self._store.delete(service)
        except CredentialStoreUnavailableError:
            pass
        self.use_user_keys[service] = False
        self._custom_key_names.discard(service)
        self._save_flags()
        logger.info("Cleared user API key for %s", service)

    def use_application_key(self, service: str) -> None:
        self.use_user_keys[service] = False
        self._save_flags()
        logger.info("Using application default key for %s", service)

    def use_user_key(self, service: str) -> None:
        key = self._read_user_key(service)
        if not key:
            raise ValueError(f"No user API key set for {service}")
        self.use_user_keys[service] = True
        self._save_flags()
        logger.info("Using user key for %s", service)

    def is_using_user_key(self, service: str) -> bool:
        return self.use_user_keys.get(service, False)

    def has_api_key(self, service: str) -> bool:
        if self.use_user_keys.get(service, False):
            key = self._read_user_key(service)
            if key and key.strip():
                return True

        if service in DEFAULT_API_KEYS and DEFAULT_API_KEYS[service]:
            return True

        key = self._read_user_key(service)
        return bool(key and key.strip())

    def has_user_key(self, service: str) -> bool:
        """Return whether a user-supplied key (not an app default) is stored for ``service``."""
        key = self._read_user_key(service)
        return bool(key and key.strip())

    def get_all_configured_keys(self) -> Dict[str, bool]:
        result = {
            service: self.has_api_key(service) for service in DEFAULT_API_KEYS
        }
        for service in self._custom_key_names:
            if service not in result:
                result[service] = self.has_api_key(service)
        return result

    def list_custom_key_names(self) -> list[str]:
        return sorted(self._custom_key_names)


api_key_manager = APIKeyManager()


def get_api_key_manager() -> APIKeyManager:
    return api_key_manager


def get_api_key(service: str) -> str:
    return api_key_manager.get_api_key(service)


def set_api_key(service: str, key: str) -> bool:
    try:
        if key:
            api_key_manager.set_user_api_key(service, key)
        else:
            api_key_manager.clear_user_api_key(service)
        return True
    except Exception as exc:
        logger.error("Error setting API key: %s", exc)
        return False


def list_available_providers() -> list[str]:
    return list(DEFAULT_API_KEYS.keys())


def has_api_key(service: str) -> bool:
    return api_key_manager.has_api_key(service)


def has_user_key(service: str) -> bool:
    return api_key_manager.has_user_key(service)


def get_all_configured_keys() -> Dict[str, bool]:
    return api_key_manager.get_all_configured_keys()


def list_custom_key_names() -> list[str]:
    return api_key_manager.list_custom_key_names()
