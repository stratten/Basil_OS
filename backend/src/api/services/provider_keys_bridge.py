"""Backend side of the provider-key bridge to the native app's Keychain vault.

Wire protocol (all messages use the ``type`` field and travel only to and from host connections):

* ``provider_keys_request`` (backend to app) asks for every stored provider key. The app answers ``provider_keys_snapshot`` with ``status`` ``ok`` and a ``keys`` object, or ``status`` ``unavailable`` when the vault exists but cannot be read.
* ``provider_key_store`` and ``provider_key_delete`` (backend to app) save or remove one key. The app answers ``provider_key_result`` with ``ok`` and, on failure, an ``error`` code.

The sync runs as a background task started when a host connection opens, so the websocket receive loop stays free to deliver the replies. When it finishes, the store is marked ready and everything waiting on ``await_provider_keys_ready`` continues.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any, Dict, Optional

from config.client_hosted_credential_store import (
    NOT_CONNECTED_MESSAGE,
    VAULT_UNREADABLE_MESSAGE,
    ClientHostedCredentialStore,
    get_client_hosted_credential_store,
)
from config.credential_store import CredentialStoreUnavailableError, is_client_hosted

from api.services.host_connection_channel import is_host_connection, send_json_to_host_connections

logger = logging.getLogger(__name__)

PROVIDER_KEY_RESPONSE_TYPES = frozenset({"provider_keys_snapshot", "provider_key_result"})

# A snapshot read can wait on a macOS permission prompt, so the app is given about three minutes in total
# (the same bound used for MCP token requests); the request is repeated each interval in case one was lost.
SNAPSHOT_ATTEMPT_SECONDS = 20.0
SNAPSHOT_MAX_ATTEMPTS = 9
# A save can also wait on a permission prompt.
WRITE_TIMEOUT_SECONDS = 180.0

ERROR_MESSAGES: Dict[str, str] = {
    "vault_unreadable": VAULT_UNREADABLE_MESSAGE,
    "write_failed": "The Basil app could not save the key to your Keychain.",
    "bad_request": "The Basil app rejected the key request.",
}
UNACKNOWLEDGED_MESSAGE = "The Basil app did not confirm the key change in time. Check the Keychain prompt and try again."

_waiters: Dict[str, "asyncio.Future[Dict[str, Any]]"] = {}
_sync_task: Optional["asyncio.Task[None]"] = None


def handle_provider_key_message(message: Dict[str, Any]) -> bool:
    """Resolve the waiter for a ``provider_keys_snapshot`` or ``provider_key_result``. Returns whether a waiter was resolved. The caller must only pass messages received on a host connection."""
    correlation_id = message.get("correlation_id")
    if not isinstance(correlation_id, str):
        return False
    future = _waiters.get(correlation_id)
    if future is None or future.done():
        return False
    future.set_result(message)
    return True


class _HostTransport:
    """Saves and removes keys through the app, waiting for its acknowledgment."""

    async def store_key(self, name: str, value: str) -> None:
        await _round_trip({"type": "provider_key_store", "name": name, "value": value})

    async def delete_key(self, name: str) -> None:
        await _round_trip({"type": "provider_key_delete", "name": name})


_transport = _HostTransport()


async def _round_trip(payload: Dict[str, Any], timeout: float = WRITE_TIMEOUT_SECONDS) -> None:
    correlation_id = uuid.uuid4().hex
    future: "asyncio.Future[Dict[str, Any]]" = asyncio.get_running_loop().create_future()
    _waiters[correlation_id] = future
    try:
        sent = await send_json_to_host_connections({**payload, "correlation_id": correlation_id})
        if sent == 0:
            raise CredentialStoreUnavailableError(NOT_CONNECTED_MESSAGE)
        try:
            result = await asyncio.wait_for(future, timeout)
        except asyncio.TimeoutError as exc:
            raise CredentialStoreUnavailableError(UNACKNOWLEDGED_MESSAGE) from exc
    finally:
        _waiters.pop(correlation_id, None)
    if not result.get("ok"):
        code = result.get("error")
        raise CredentialStoreUnavailableError(ERROR_MESSAGES.get(code if isinstance(code, str) else "", ERROR_MESSAGES["write_failed"]))


async def _run_sync(store: ClientHostedCredentialStore) -> None:
    from api.services.provider_keys_migration import migrate_legacy_provider_keys

    correlation_id = uuid.uuid4().hex
    future: "asyncio.Future[Dict[str, Any]]" = asyncio.get_running_loop().create_future()
    _waiters[correlation_id] = future
    try:
        reply: Optional[Dict[str, Any]] = None
        for _attempt in range(SNAPSHOT_MAX_ATTEMPTS):
            sent = await send_json_to_host_connections({"type": "provider_keys_request", "correlation_id": correlation_id})
            if sent == 0:
                logger.info("No host connection is open; provider keys will be requested on the next connection")
                return
            try:
                reply = await asyncio.wait_for(asyncio.shield(future), SNAPSHOT_ATTEMPT_SECONDS)
                break
            except asyncio.TimeoutError:
                continue
        if reply is None:
            logger.warning("The Basil app did not deliver provider keys")
            store.mark_unavailable(UNACKNOWLEDGED_MESSAGE)
            return
        if reply.get("status") != "ok":
            logger.warning("The Basil app reported its Keychain vault unreadable")
            store.mark_unavailable(VAULT_UNREADABLE_MESSAGE)
            return
        keys = reply.get("keys")
        store.load_snapshot(keys if isinstance(keys, dict) else {})
        logger.info("Received %d provider key name(s) from the Basil app", len(store.names()))
        try:
            await migrate_legacy_provider_keys(store=store, transport=_transport)
        except Exception:
            logger.exception("Moving earlier provider keys into the Keychain vault failed; they will be retried on the next launch")
        store.mark_ready()
    except Exception:
        logger.exception("Syncing provider keys with the Basil app failed")
        store.mark_unavailable(UNACKNOWLEDGED_MESSAGE)
    finally:
        _waiters.pop(correlation_id, None)


def start_provider_key_sync(websocket: Any, store: Optional[ClientHostedCredentialStore] = None) -> Optional["asyncio.Task[None]"]:
    """Begin delivering provider keys when a host connection opens. Does nothing unless the app hosts the credentials, the connection is a host connection, and the keys have not already arrived."""
    global _sync_task
    if not is_client_hosted() or not is_host_connection(websocket):
        return None
    target = store or get_client_hosted_credential_store()
    target.attach_transport(_transport)
    if target.is_ready() and target.unavailable_reason() is None:
        return None
    if _sync_task is not None and not _sync_task.done():
        return _sync_task
    _sync_task = asyncio.get_running_loop().create_task(_run_sync(target))
    return _sync_task
