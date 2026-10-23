"""Cloud transcription preferences (a small JSON file) and provider key access (the OS credential store)."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Literal, Optional, Protocol

from pydantic import BaseModel, ConfigDict, ValidationError

from api.core.atomic_text import atomic_write_text

from .models import PROVIDER_IDS

logger = logging.getLogger(__name__)

SETTINGS_FILE_NAME = "meeting_cloud_transcription_settings.json"


class CloudTranscriptionSettings(BaseModel):
    """Opt-in preferences; nothing here is secret, provider keys live in the credential store."""

    model_config = ConfigDict(extra="ignore")

    enabled: bool = False
    provider: Literal["deepgram", "assemblyai"] = "deepgram"
    connection: Literal["own_key", "basil_account"] = "own_key"
    acknowledged: bool = False


class CloudTranscriptionSettingsStore:
    """``~/.basil/config/meeting_cloud_transcription_settings.json``; an unreadable file reads as the defaults (off)."""

    def __init__(self, path: Optional[Path] = None) -> None:
        self._explicit_path = path

    @property
    def path(self) -> Path:
        if self._explicit_path is not None:
            return self._explicit_path
        return Path.home() / ".basil" / "config" / SETTINGS_FILE_NAME

    def load(self) -> CloudTranscriptionSettings:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return CloudTranscriptionSettings()
        try:
            return CloudTranscriptionSettings.model_validate(raw)
        except ValidationError:
            logger.warning("Ignoring invalid cloud transcription settings at %s", self.path)
            return CloudTranscriptionSettings()

    def save(self, settings: CloudTranscriptionSettings) -> None:
        atomic_write_text(self.path, json.dumps(settings.model_dump(mode="json"), ensure_ascii=False))


class KeyAccess(Protocol):
    def read(self, provider: str) -> Optional[str]: ...

    def write(self, provider: str, key: str) -> bool: ...

    def clear(self, provider: str) -> bool: ...


class CredentialStoreKeyAccess:
    """Provider keys through the same OS credential store the Settings API keys use."""

    @staticmethod
    def _valid(provider: str) -> bool:
        return provider in PROVIDER_IDS

    def read(self, provider: str) -> Optional[str]:
        if not self._valid(provider):
            return None
        from config.api_keys import get_api_key_manager

        manager = get_api_key_manager()
        if not manager.has_user_key(provider):
            return None
        try:
            return manager.get_api_key(provider) or None
        except ValueError:
            return None

    def write(self, provider: str, key: str) -> bool:
        if not self._valid(provider) or not key:
            return False
        from config.api_keys import set_api_key

        return set_api_key(provider, key)

    def clear(self, provider: str) -> bool:
        if not self._valid(provider):
            return False
        from config.api_keys import set_api_key

        return set_api_key(provider, "")


def account_token_available() -> bool:
    """True when a Basil account token is already cached; never prompts for sign-in."""
    from api.core.services.model_service import get_auth_access_token

    return get_auth_access_token() is not None


_settings_store = CloudTranscriptionSettingsStore()
_key_access: KeyAccess = CredentialStoreKeyAccess()


def get_settings_store() -> CloudTranscriptionSettingsStore:
    return _settings_store


def get_key_access() -> KeyAccess:
    return _key_access
