"""Portable secure credential storage for user-provided provider API keys.

Two interchangeable backends share one interface. ``CredentialStore`` uses the operating system's credential store through ``keyring`` and is the default (tests, headless runs, and platforms without the Basil app). ``ClientHostedCredentialStore`` is selected by ``BASIL_CREDENTIAL_HOST=client``, which Basil's launch scripts set: the native app owns the one Keychain vault that holds every Basil secret, and the backend keeps provider keys in memory only, asking the app to save or remove them.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional

import keyring
from keyring.errors import KeyringError, NoKeyringError, PasswordDeleteError

logger = logging.getLogger("credential_store")

SERVICE_NAME = "com.basil.providerKeys"

CREDENTIAL_HOST_ENV = "BASIL_CREDENTIAL_HOST"


class CredentialStoreUnavailableError(RuntimeError):
    """Raised when no usable credential backend is present or a secret could not be stored."""


def is_client_hosted() -> bool:
    """Whether the native Basil app hosts the provider keys (the app's launch scripts set this)."""
    return os.environ.get(CREDENTIAL_HOST_ENV, "").strip().lower() == "client"


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

    async def asave(self, key: str, value: str) -> None:
        """Save without blocking the event loop (the OS may show a permission prompt)."""
        await asyncio.to_thread(self.save, key, value)

    async def adelete(self, key: str) -> None:
        """Delete without blocking the event loop (the OS may show a permission prompt)."""
        await asyncio.to_thread(self.delete, key)

    def is_available(self) -> bool:
        try:
            return keyring.get_keyring().priority >= 0
        except Exception:
            return False

    def is_ready(self) -> bool:
        """The OS credential store has nothing to wait for."""
        return True

    def unavailable_reason(self) -> Optional[str]:
        return None


_default_store: Optional[object] = None


def get_credential_store():
    """The process-wide store: client-hosted when ``BASIL_CREDENTIAL_HOST=client``, otherwise the OS credential store."""
    global _default_store
    if _default_store is None:
        if is_client_hosted():
            from .client_hosted_credential_store import get_client_hosted_credential_store

            _default_store = get_client_hosted_credential_store()
        else:
            _default_store = CredentialStore()
    return _default_store
