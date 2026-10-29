"""Provider API keys held in memory for the native app's single Keychain vault.

The Basil app owns one Keychain item that holds the account session, every connector token, and the provider API keys the user supplied, so macOS asks for Keychain access once. The backend never touches the Keychain for those keys. It receives them from the app as a snapshot when the app connects, answers reads from memory, and asks the app to save or remove a key before it reports success.

The store is ready once the first snapshot arrived (or the vault was reported unreadable). Code that needs a real key value awaits ``await_ready`` first; synchronous status checks use the non-secret flag file as a hint until then (see ``config.api_keys``).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Dict, List, Optional, Protocol

from .credential_store import CredentialStoreUnavailableError

logger = logging.getLogger("client_hosted_credential_store")

READINESS_TIMEOUT_SECONDS = 60.0

NOT_CONNECTED_MESSAGE = (
    "The Basil app is not connected, so the key could not be saved to your Keychain. Reopen Basil and try again."
)
VAULT_UNREADABLE_MESSAGE = (
    "Basil could not open its Keychain vault, so your saved API keys are unavailable. "
    "Quit and reopen Basil, and choose Always Allow when macOS asks to use the Keychain."
)


class ProviderKeyTransport(Protocol):
    """How the store asks the native app to persist a change. Each call returns only after the app acknowledged it, and raises ``CredentialStoreUnavailableError`` when it could not be saved."""

    async def store_key(self, name: str, value: str) -> None: ...

    async def delete_key(self, name: str) -> None: ...


class ClientHostedCredentialStore:
    """Provider keys in memory, persisted by the native app's vault."""

    def __init__(self) -> None:
        self._keys: Dict[str, str] = {}
        self._ready = False
        self._unavailable_reason: Optional[str] = None
        self._transport: Optional[ProviderKeyTransport] = None
        self._ready_event: Optional[asyncio.Event] = None
        self._ready_event_loop: Optional[asyncio.AbstractEventLoop] = None

    # Reads are synchronous and never leave the process.

    def read(self, key: str) -> Optional[str]:
        return self._keys.get(key)

    def names(self) -> List[str]:
        return sorted(self._keys)

    def is_available(self) -> bool:
        return True

    def is_ready(self) -> bool:
        return self._ready

    def unavailable_reason(self) -> Optional[str]:
        return self._unavailable_reason

    # State driven by the bridge.

    def attach_transport(self, transport: ProviderKeyTransport) -> None:
        self._transport = transport

    def load_snapshot(self, keys: Dict[str, str]) -> None:
        """Replace the in-memory keys with the app's vault contents. Empty names and values are dropped."""
        self._keys = {name: value for name, value in keys.items() if name and isinstance(value, str) and value}
        self._unavailable_reason = None

    def record_key(self, name: str, value: str) -> None:
        """Remember a key the app already persisted (used by the legacy migration)."""
        self._keys[name] = value

    def mark_unavailable(self, reason: str) -> None:
        """The app reported the vault unreadable or never answered. Waiters are released; reads return nothing."""
        self._unavailable_reason = reason
        self.mark_ready()

    def mark_ready(self) -> None:
        self._ready = True
        event = self._ready_event
        loop = self._ready_event_loop
        if event is None or loop is None:
            return
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is loop:
            event.set()
        elif not loop.is_closed():
            loop.call_soon_threadsafe(event.set)

    def _event_for_running_loop(self) -> asyncio.Event:
        loop = asyncio.get_running_loop()
        if self._ready_event is None or self._ready_event_loop is not loop:
            self._ready_event = asyncio.Event()
            self._ready_event_loop = loop
            if self._ready:
                self._ready_event.set()
        return self._ready_event

    async def await_ready(self, timeout: float = READINESS_TIMEOUT_SECONDS) -> bool:
        """Wait until the app's keys have arrived. Returns False (after logging) when the app did not answer in time, so callers proceed instead of hanging."""
        if self._ready:
            return True
        try:
            await asyncio.wait_for(self._event_for_running_loop().wait(), timeout)
        except asyncio.TimeoutError:
            logger.warning("Provider keys were not delivered by the Basil app within %.0f seconds; continuing without them", timeout)
            return self._ready
        return True

    # Writes go to the app first and are remembered only after it acknowledges.

    async def _require_writable(self) -> ProviderKeyTransport:
        await self.await_ready()
        if self._unavailable_reason:
            raise CredentialStoreUnavailableError(self._unavailable_reason)
        if self._transport is None or not self._ready:
            raise CredentialStoreUnavailableError(NOT_CONNECTED_MESSAGE)
        return self._transport

    async def asave(self, key: str, value: str) -> None:
        transport = await self._require_writable()
        await transport.store_key(key, value)
        self._keys[key] = value

    async def adelete(self, key: str) -> None:
        transport = await self._require_writable()
        await transport.delete_key(key)
        self._keys.pop(key, None)

    def save(self, key: str, value: str) -> None:
        raise CredentialStoreUnavailableError("Provider keys are saved through the Basil app; use the asynchronous API.")

    def delete(self, key: str) -> None:
        raise CredentialStoreUnavailableError("Provider keys are removed through the Basil app; use the asynchronous API.")


_client_hosted_store: Optional[ClientHostedCredentialStore] = None


def get_client_hosted_credential_store() -> ClientHostedCredentialStore:
    global _client_hosted_store
    if _client_hosted_store is None:
        _client_hosted_store = ClientHostedCredentialStore()
    return _client_hosted_store
