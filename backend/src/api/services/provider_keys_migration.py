"""One-time move of provider keys from the OS keyring into the Basil app's Keychain vault."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Iterable, Optional

from api.core.atomic_text import atomic_write_text
from config.client_hosted_credential_store import ClientHostedCredentialStore, ProviderKeyTransport
from config.credential_store import CredentialStore, CredentialStoreUnavailableError

logger = logging.getLogger(__name__)

MARKER_FILE_NAME = "provider_keys_vault_migrated"


def default_marker_path() -> Path:
    return Path.home() / ".basil" / "config" / MARKER_FILE_NAME


def candidate_key_names() -> list[str]:
    """Every name an earlier version could have stored: the built-in providers, every flagged name, custom names, and the meeting transcription providers."""
    from api.services.meeting_cloud_asr.models import PROVIDER_IDS
    from config.api_keys import get_api_key_manager

    return sorted(set(get_api_key_manager().known_key_names()) | set(PROVIDER_IDS))


async def migrate_legacy_provider_keys(
    *,
    store: ClientHostedCredentialStore,
    transport: ProviderKeyTransport,
    legacy_store: Optional[CredentialStore] = None,
    names: Optional[Iterable[str]] = None,
    marker_path: Optional[Path] = None,
) -> int:
    """Move earlier keyring keys into the app's vault. Returns how many keys moved.

    A key already present in the vault wins: the earlier keyring item is deleted without overwriting it. A key is deleted from the keyring only after the app acknowledged saving it. The marker is written only when every name was handled, so a failure (for example the app being unreachable) is retried on the next launch.
    """
    marker = marker_path or default_marker_path()
    if marker.exists():
        return 0
    legacy = legacy_store or CredentialStore()
    candidates = list(names) if names is not None else candidate_key_names()
    moved = 0
    clean = True
    for name in candidates:
        try:
            value = await asyncio.to_thread(legacy.read, name)
        except CredentialStoreUnavailableError:
            logger.info("No OS credential store backend is available; there are no earlier provider keys to move")
            _write_marker(marker)
            return moved
        except Exception as exc:
            logger.warning("Could not read the earlier key for %s: %s", name, exc)
            clean = False
            continue
        if not value:
            continue
        try:
            if store.read(name) is None:
                await transport.store_key(name, value)
                store.record_key(name, value)
            await asyncio.to_thread(legacy.delete, name)
            moved += 1
            logger.info("Moved the earlier provider key for %s into the Keychain vault", name)
        except Exception as exc:
            logger.warning("Could not move the earlier key for %s: %s", name, exc)
            clean = False
    if clean:
        _write_marker(marker)
    return moved


def _write_marker(marker: Path) -> None:
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(marker, "1")
    except Exception as exc:
        logger.warning("Could not record the provider-key migration: %s", exc)
