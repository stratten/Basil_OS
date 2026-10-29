"""Unit tests for the app-hosted provider-key store and the credential-store selection."""

import asyncio

import keyring
import pytest

from config import credential_store as credential_store_module
from config.client_hosted_credential_store import (
    NOT_CONNECTED_MESSAGE,
    VAULT_UNREADABLE_MESSAGE,
    ClientHostedCredentialStore,
)
from config.credential_store import CredentialStore, CredentialStoreUnavailableError, is_client_hosted


class RecordingTransport:
    def __init__(self, error: Exception | None = None) -> None:
        self.stored: list[tuple[str, str]] = []
        self.deleted: list[str] = []
        self.error = error

    async def store_key(self, name: str, value: str) -> None:
        if self.error:
            raise self.error
        self.stored.append((name, value))

    async def delete_key(self, name: str) -> None:
        if self.error:
            raise self.error
        self.deleted.append(name)


def ready_store(transport: RecordingTransport, keys: dict[str, str] | None = None) -> ClientHostedCredentialStore:
    store = ClientHostedCredentialStore()
    store.attach_transport(transport)
    store.load_snapshot(keys or {})
    store.mark_ready()
    return store


def test_snapshot_keys_are_read_from_memory_and_blank_entries_are_dropped():
    store = ClientHostedCredentialStore()

    store.load_snapshot({"openai": "sk-a", "": "orphan", "google": "", "anthropic": "k"})

    assert store.read("openai") == "sk-a"
    assert store.read("google") is None
    assert store.names() == ["anthropic", "openai"]


def test_the_store_is_not_ready_until_marked_and_loading_a_snapshot_alone_does_not_ready_it():
    store = ClientHostedCredentialStore()
    store.load_snapshot({"openai": "sk-a"})
    assert store.is_ready() is False

    store.mark_ready()

    assert store.is_ready() is True
    assert store.unavailable_reason() is None


@pytest.mark.asyncio
async def test_await_ready_returns_when_the_store_is_marked_from_another_task():
    store = ClientHostedCredentialStore()

    async def release() -> None:
        await asyncio.sleep(0.01)
        store.mark_ready()

    task = asyncio.create_task(release())

    assert await store.await_ready(timeout=2) is True
    await task


@pytest.mark.asyncio
async def test_await_ready_times_out_and_reports_false_instead_of_hanging():
    assert await ClientHostedCredentialStore().await_ready(timeout=0.01) is False


def test_the_readiness_event_follows_the_running_event_loop():
    store = ClientHostedCredentialStore()
    assert asyncio.run(store.await_ready(timeout=0.01)) is False

    async def release_then_wait() -> bool:
        asyncio.get_running_loop().call_later(0.01, store.mark_ready)
        return await store.await_ready(timeout=2)

    assert asyncio.run(release_then_wait()) is True


@pytest.mark.asyncio
async def test_marking_unavailable_releases_waiters_and_blocks_writes_with_the_reason():
    transport = RecordingTransport()
    store = ClientHostedCredentialStore()
    store.attach_transport(transport)
    store.mark_unavailable(VAULT_UNREADABLE_MESSAGE)

    assert await store.await_ready(timeout=0.01) is True
    with pytest.raises(CredentialStoreUnavailableError, match="Keychain vault"):
        await store.asave("openai", "sk-new")
    assert transport.stored == []


@pytest.mark.asyncio
async def test_saving_goes_through_the_app_first_and_is_remembered_only_after_it_answers():
    transport = RecordingTransport()
    store = ready_store(transport)

    await store.asave("openai", "sk-new")

    assert transport.stored == [("openai", "sk-new")]
    assert store.read("openai") == "sk-new"


@pytest.mark.asyncio
async def test_a_failed_save_is_not_remembered():
    store = ready_store(RecordingTransport(error=CredentialStoreUnavailableError("The app refused.")))

    with pytest.raises(CredentialStoreUnavailableError, match="The app refused."):
        await store.asave("openai", "sk-new")

    assert store.read("openai") is None


@pytest.mark.asyncio
async def test_deleting_forgets_the_key_only_after_the_app_answers():
    transport = RecordingTransport()
    store = ready_store(transport, {"openai": "sk-a", "google": "g"})

    await store.adelete("openai")

    assert transport.deleted == ["openai"]
    assert store.read("openai") is None
    assert store.read("google") == "g"


@pytest.mark.asyncio
async def test_a_failed_delete_keeps_the_key():
    store = ready_store(RecordingTransport(error=CredentialStoreUnavailableError("The app refused.")), {"openai": "sk-a"})

    with pytest.raises(CredentialStoreUnavailableError):
        await store.adelete("openai")

    assert store.read("openai") == "sk-a"


@pytest.mark.asyncio
async def test_a_write_without_a_connected_app_reports_that_the_app_is_not_connected():
    store = ClientHostedCredentialStore()
    store.mark_ready()

    with pytest.raises(CredentialStoreUnavailableError) as raised:
        await store.asave("openai", "sk-new")

    assert str(raised.value) == NOT_CONNECTED_MESSAGE


@pytest.mark.asyncio
async def test_a_write_made_before_the_snapshot_waits_for_it():
    transport = RecordingTransport()
    store = ClientHostedCredentialStore()
    store.attach_transport(transport)

    save = asyncio.create_task(store.asave("openai", "sk-new"))
    for _ in range(5):
        await asyncio.sleep(0)
    assert transport.stored == []

    store.load_snapshot({})
    store.mark_ready()
    await save

    assert transport.stored == [("openai", "sk-new")]


def test_the_synchronous_writers_refuse_because_the_app_owns_persistence():
    store = ClientHostedCredentialStore()

    with pytest.raises(CredentialStoreUnavailableError):
        store.save("openai", "sk-a")
    with pytest.raises(CredentialStoreUnavailableError):
        store.delete("openai")


@pytest.mark.parametrize(
    ("value", "expected"),
    [("client", True), ("  CLIENT ", True), ("", False), ("keyring", False)],
)
def test_is_client_hosted_reads_the_environment(monkeypatch, value, expected):
    monkeypatch.setenv("BASIL_CREDENTIAL_HOST", value)
    assert is_client_hosted() is expected


def test_the_client_hosted_store_is_selected_only_when_the_app_hosts_the_credentials(monkeypatch):
    monkeypatch.setattr(credential_store_module, "_default_store", None)
    monkeypatch.delenv("BASIL_CREDENTIAL_HOST", raising=False)
    assert isinstance(credential_store_module.get_credential_store(), CredentialStore)

    monkeypatch.setattr(credential_store_module, "_default_store", None)
    monkeypatch.setenv("BASIL_CREDENTIAL_HOST", "client")
    assert isinstance(credential_store_module.get_credential_store(), ClientHostedCredentialStore)


@pytest.mark.asyncio
async def test_the_keyring_store_saves_and_deletes_asynchronously_through_the_same_backend(monkeypatch):
    data: dict[tuple[str, str], str] = {}
    monkeypatch.setattr(keyring, "get_password", lambda service, name: data.get((service, name)))
    monkeypatch.setattr(keyring, "set_password", lambda service, name, value: data.__setitem__((service, name), value))
    monkeypatch.setattr(keyring, "delete_password", lambda service, name: data.pop((service, name), None))
    store = CredentialStore(service_name="com.basil.test")

    await store.asave("openai", "sk-a")
    assert store.read("openai") == "sk-a"
    await store.adelete("openai")

    assert store.read("openai") is None
    assert store.is_ready() is True
    assert store.unavailable_reason() is None
