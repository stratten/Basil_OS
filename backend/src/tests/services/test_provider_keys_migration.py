"""One-time move of provider keys from the OS keyring into the app's Keychain vault."""

import pytest

from api.services.provider_keys_migration import candidate_key_names, migrate_legacy_provider_keys
from config.client_hosted_credential_store import ClientHostedCredentialStore
from config.credential_store import CredentialStoreUnavailableError


class FakeLegacyStore:
    def __init__(self, keys: dict | None = None, read_error: Exception | None = None) -> None:
        self.keys = dict(keys or {})
        self.deleted: list[str] = []
        self.read_error = read_error

    def read(self, name: str):
        if self.read_error:
            raise self.read_error
        return self.keys.get(name)

    def delete(self, name: str) -> None:
        self.deleted.append(name)
        self.keys.pop(name, None)


class FakeTransport:
    def __init__(self, fail_for: tuple = ()) -> None:
        self.stored: list[tuple[str, str]] = []
        self.fail_for = set(fail_for)

    async def store_key(self, name: str, value: str) -> None:
        if name in self.fail_for:
            raise CredentialStoreUnavailableError("The app is unreachable.")
        self.stored.append((name, value))

    async def delete_key(self, name: str) -> None:
        self.stored = [item for item in self.stored if item[0] != name]


@pytest.fixture
def store() -> ClientHostedCredentialStore:
    hosted = ClientHostedCredentialStore()
    hosted.load_snapshot({})
    hosted.mark_ready()
    return hosted


@pytest.mark.asyncio
async def test_earlier_keyring_keys_move_into_the_vault_and_are_removed(store, tmp_path):
    legacy = FakeLegacyStore({"openai": "sk-a", "google": "g-b"})
    transport = FakeTransport()
    marker = tmp_path / "migrated"

    moved = await migrate_legacy_provider_keys(
        store=store, transport=transport, legacy_store=legacy, names=["openai", "google", "anthropic"], marker_path=marker
    )

    assert moved == 2
    assert transport.stored == [("openai", "sk-a"), ("google", "g-b")]
    assert legacy.keys == {}
    assert store.read("openai") == "sk-a"
    assert marker.exists()


@pytest.mark.asyncio
async def test_a_key_already_in_the_vault_wins_and_the_earlier_copy_is_removed(store, tmp_path):
    store.load_snapshot({"openai": "vault-key"})
    legacy = FakeLegacyStore({"openai": "old-key"})
    transport = FakeTransport()

    await migrate_legacy_provider_keys(
        store=store, transport=transport, legacy_store=legacy, names=["openai"], marker_path=tmp_path / "migrated"
    )

    assert transport.stored == []
    assert store.read("openai") == "vault-key"
    assert legacy.deleted == ["openai"]


@pytest.mark.asyncio
async def test_a_key_the_app_could_not_save_stays_in_the_keyring_and_the_move_is_retried_next_launch(store, tmp_path):
    legacy = FakeLegacyStore({"openai": "sk-a", "google": "g-b"})
    transport = FakeTransport(fail_for=("openai",))
    marker = tmp_path / "migrated"

    moved = await migrate_legacy_provider_keys(
        store=store, transport=transport, legacy_store=legacy, names=["openai", "google"], marker_path=marker
    )

    assert moved == 1
    assert legacy.keys == {"openai": "sk-a"}
    assert store.read("openai") is None
    assert not marker.exists()


@pytest.mark.asyncio
async def test_a_finished_migration_is_not_repeated(store, tmp_path):
    marker = tmp_path / "migrated"
    marker.write_text("1")
    legacy = FakeLegacyStore({"openai": "sk-a"})

    moved = await migrate_legacy_provider_keys(
        store=store, transport=FakeTransport(), legacy_store=legacy, names=["openai"], marker_path=marker
    )

    assert moved == 0
    assert legacy.keys == {"openai": "sk-a"}


@pytest.mark.asyncio
async def test_a_machine_without_a_keyring_backend_has_nothing_to_move(store, tmp_path):
    marker = tmp_path / "migrated"
    legacy = FakeLegacyStore(read_error=CredentialStoreUnavailableError("no backend"))

    moved = await migrate_legacy_provider_keys(
        store=store, transport=FakeTransport(), legacy_store=legacy, names=["openai"], marker_path=marker
    )

    assert moved == 0
    assert marker.exists()


@pytest.mark.asyncio
async def test_an_unreadable_earlier_key_is_retried_next_launch(store, tmp_path):
    marker = tmp_path / "migrated"
    legacy = FakeLegacyStore(read_error=RuntimeError("user denied the prompt"))

    moved = await migrate_legacy_provider_keys(
        store=store, transport=FakeTransport(), legacy_store=legacy, names=["openai"], marker_path=marker
    )

    assert moved == 0
    assert not marker.exists()


def test_every_name_an_earlier_version_could_have_used_is_searched():
    names = set(candidate_key_names())

    assert {"anthropic", "openai", "google", "gemini", "deepgram", "assemblyai"} <= names
