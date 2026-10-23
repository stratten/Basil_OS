"""Portable secure credential storage for user-provided provider API keys."""

from __future__ import annotations

import logging
from typing import Optional

import keyring
from keyring.errors import KeyringError, NoKeyringError, PasswordDeleteError

logger = logging.getLogger("credential_store")

SERVICE_NAME = "com.basil.providerKeys"


class CredentialStoreUnavailableError(RuntimeError):
    """Raised when no usable OS credential backend is present."""


class CredentialStore:
    """Read, save, and delete secrets in the OS-native credential store."""

    def __init__(self, service_name: str = SERVICE_NAME) -> None:
        self._service_name = service_name

    def read(self, key: str) -> Optional[str]:
        try:
            return keyring.get_password(self._service_name, key)
        except NoKeyringError as exc:
            raise CredentialStoreUnavailableError(
                "No OS credential store backend is available on this platform."
            ) from exc
        except KeyringError as exc:
            logger.error("Credential store read failed for key=%r: %s", key, exc)
            return None

    def save(self, key: str, value: str) -> None:
        try:
            keyring.set_password(self._service_name, key, value)
        except NoKeyringError as exc:
            raise CredentialStoreUnavailableError(
                "No OS credential store backend is available on this platform."
            ) from exc
        except KeyringError as exc:
            logger.error("Credential store save failed for key=%r: %s", key, exc)
            raise

    def delete(self, key: str) -> None:
        try:
            keyring.delete_password(self._service_name, key)
        except NoKeyringError as exc:
            raise CredentialStoreUnavailableError(
                "No OS credential store backend is available on this platform."
            ) from exc
        except PasswordDeleteError:
            pass
        except KeyringError as exc:
            logger.error("Credential store delete failed for key=%r: %s", key, exc)
            raise

    def is_available(self) -> bool:
        try:
            return keyring.get_keyring().priority >= 0
        except Exception:
            return False


_default_store: Optional[CredentialStore] = None


def get_credential_store() -> CredentialStore:
    global _default_store
    if _default_store is None:
        _default_store = CredentialStore()
    return _default_store
