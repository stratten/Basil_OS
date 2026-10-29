"""APIKeyManager behavior with the app-hosted store and the keyring store."""

import json

import keyring
import pytest
from keyring.errors import NoKeyringError

from config import api_keys
from config.api_keys import APIKeyManager
from config.client_hosted_credential_store import ClientHostedCredentialStore
from config.credential_store import CredentialStore, CredentialStoreUnavailableError


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


@pytest.fixture
def flags_file(monkeypatch, tmp_path):
    monkeypatch.setattr(api_keys, "USER_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(api_keys, "KEY_FLAGS_FILE", tmp_path / "api_key_flags.json")
    return tmp_path / "api_key_flags.json"


def hosted_manager(transport: RecordingTransport | None = None, ready: bool = True, keys: dict | None = None):
    store = ClientHostedCredentialStore()
    store.attach_transport(transport or RecordingTransport())
    if ready:
        store.load_snapshot(keys or {})
        store.mark_ready()
    return APIKeyManager(store), store


def test_before_the_apps_keys_arrive_status_checks_answer_from_the_non_secret_flags(flags_file):
    manager, store = hosted_manager(ready=False)
    manager.use_user_keys = {"custom_demo": True}

    assert manager.has_user_key("custom_demo") is True
    assert manager.has_api_key("custom_demo") is True
    assert manager.has_user_key("custom_other") is False
    assert manager.has_api_key("custom_other") is False

    store.load_snapshot({})
    store.mark_ready()

    assert manager.has_user_key("custom_demo") is False
    assert manager.has_api_key("custom_demo") is False


def test_a_flagged_key_is_read_from_the_apps_memory_once_it_arrived(flags_file):
    manager, _ = hosted_manager(keys={"custom_demo": "k-123"})

    assert manager.has_user_key("custom_demo") is True

    manager.use_user_keys = {"custom_demo": True}
    assert manager.get_api_key("custom_demo") == "k-123"


def test_an_unflagged_service_has_no_key_even_when_the_vault_holds_one(flags_file):
    manager, _ = hosted_manager(keys={"custom_demo": "k-123"})

    with pytest.raises(ValueError, match="No API key available for custom_demo"):
        manager.get_api_key("custom_demo")


def test_an_unreadable_vault_explains_itself_only_for_a_flagged_key(flags_file):
    manager, store = hosted_manager(ready=False)
    store.mark_unavailable("Quit and reopen Basil.")

    manager.use_user_keys = {"custom_demo": True}
    with pytest.raises(ValueError, match="Quit and reopen Basil."):
        manager.get_api_key("custom_demo")

    with pytest.raises(ValueError) as raised:
        manager.get_api_key("custom_unflagged")
    assert str(raised.value) == "No API key available for custom_unflagged"


@pytest.mark.asyncio
async def test_saving_asks_the_app_then_records_the_flags(flags_file):
    transport = RecordingTransport()
    manager, store = hosted_manager(transport)

    await manager.aset_user_api_key("custom_demo", "k-123")

    assert transport.stored == [("custom_demo", "k-123")]
    assert store.read("custom_demo") == "k-123"
    assert manager.use_user_keys == {"custom_demo": True}
    assert manager.list_custom_key_names() == ["custom_demo"]
    saved = json.loads(flags_file.read_text())
    assert saved["use_user_keys"] == {"custom_demo": True}
    assert saved["custom_key_names"] == ["custom_demo"]


@pytest.mark.asyncio
async def test_a_refused_save_changes_neither_the_flags_nor_the_keys(flags_file):
    manager, store = hosted_manager(RecordingTransport(error=CredentialStoreUnavailableError("The app refused.")))

    with pytest.raises(CredentialStoreUnavailableError, match="The app refused."):
        await manager.aset_user_api_key("custom_demo", "k-123")

    assert store.read("custom_demo") is None
    assert manager.use_user_keys == {}
    assert not flags_file.exists()


@pytest.mark.asyncio
async def test_clearing_asks_the_app_then_clears_the_flags(flags_file):
    transport = RecordingTransport()
    manager, store = hosted_manager(transport, keys={"custom_demo": "k-123"})
    manager.use_user_keys = {"custom_demo": True}

    await manager.aclear_user_api_key("custom_demo")

    assert transport.deleted == ["custom_demo"]
    assert store.read("custom_demo") is None
    assert manager.use_user_keys == {"custom_demo": False}


@pytest.mark.asyncio
async def test_a_failed_clear_keeps_the_key_and_the_flag(flags_file):
    manager, store = hosted_manager(
        RecordingTransport(error=CredentialStoreUnavailableError("The app is gone.")), keys={"custom_demo": "k-123"}
    )
    manager.use_user_keys = {"custom_demo": True}

    with pytest.raises(CredentialStoreUnavailableError):
        await manager.aclear_user_api_key("custom_demo")

    assert store.read("custom_demo") == "k-123"
    assert manager.use_user_keys == {"custom_demo": True}


@pytest.mark.asyncio
async def test_saving_an_empty_key_clears_it(flags_file):
    transport = RecordingTransport()
    manager, _ = hosted_manager(transport, keys={"custom_demo": "k-123"})

    await manager.aset_user_api_key("custom_demo", "")

    assert transport.deleted == ["custom_demo"]
    assert transport.stored == []


@pytest.mark.asyncio
async def test_the_keyring_store_still_saves_reads_and_clears_keys(flags_file, monkeypatch):
    data: dict[tuple[str, str], str] = {}
    monkeypatch.setattr(keyring, "get_password", lambda service, name: data.get((service, name)))
    monkeypatch.setattr(keyring, "set_password", lambda service, name, value: data.__setitem__((service, name), value))
    monkeypatch.setattr(keyring, "delete_password", lambda service, name: data.pop((service, name), None))
    manager = APIKeyManager(CredentialStore(service_name="com.basil.test"))

    await manager.aset_user_api_key("custom_demo", "k-123")
    assert manager.get_api_key("custom_demo") == "k-123"
    assert manager.has_user_key("custom_demo") is True
    assert await manager.await_ready(timeout=0.01) is True

    await manager.aclear_user_api_key("custom_demo")
    assert manager.has_user_key("custom_demo") is False


@pytest.mark.asyncio
async def test_a_keyring_store_without_a_backend_has_nothing_to_clear_but_cannot_save(flags_file, monkeypatch):
    def no_backend(*_args, **_kwargs):
        raise NoKeyringError("no backend")

    monkeypatch.setattr(keyring, "delete_password", no_backend)
    monkeypatch.setattr(keyring, "set_password", no_backend)
    manager = APIKeyManager(CredentialStore(service_name="com.basil.test"))

    await manager.aclear_user_api_key("custom_demo")
    assert manager.use_user_keys == {"custom_demo": False}

    with pytest.raises(CredentialStoreUnavailableError):
        await manager.aset_user_api_key("custom_demo", "k-123")


def test_known_key_names_include_the_built_in_providers_and_every_recorded_name(flags_file):
    manager, _ = hosted_manager()
    manager.use_user_keys = {"deepgram": True, "custom_demo": False}
    manager._custom_key_names = {"custom_other"}

    names = manager.known_key_names()

    assert {"anthropic", "openai", "google", "gemini", "deepgram", "custom_demo", "custom_other"} <= set(names)
    assert names == sorted(names)
