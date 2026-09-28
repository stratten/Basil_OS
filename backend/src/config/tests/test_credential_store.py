"""Unit tests for CredentialStore with an in-memory keyring backend."""

import keyring
import pytest

from config.credential_store import CredentialStore, CredentialStoreUnavailableError


@pytest.fixture()
def fake_store(monkeypatch):
    class InMemoryKeyring:
        def __init__(self) -> None:
            self.data: dict[tuple[str, str], str] = {}

        def get_password(self, service: str, username: str):
            return self.data.get((service, username))

        def set_password(self, service: str, username: str, password: str):
            self.data[(service, username)] = password

        def delete_password(self, service: str, username: str):
            if (service, username) not in self.data:
                from keyring.errors import PasswordDeleteError

                raise PasswordDeleteError("not found")
            del self.data[(service, username)]

    backend = InMemoryKeyring()
    monkeypatch.setattr(keyring, "get_password", backend.get_password)
    monkeypatch.setattr(keyring, "set_password", backend.set_password)
    monkeypatch.setattr(keyring, "delete_password", backend.delete_password)
    return CredentialStore(service_name="com.basil.test")


def test_save_then_read_round_trips(fake_store):
    fake_store.save("openai", "sk-test-123")
    assert fake_store.read("openai") == "sk-test-123"


def test_read_missing_key_returns_none(fake_store):
    assert fake_store.read("anthropic") is None


def test_delete_is_idempotent(fake_store):
    fake_store.save("openai", "sk-test-123")
    fake_store.delete("openai")
    fake_store.delete("openai")
    assert fake_store.read("openai") is None


def test_unavailable_backend_raises_typed_error(monkeypatch):
    from keyring.errors import NoKeyringError

    def raise_no_keyring(*_args, **_kwargs):
        raise NoKeyringError("no backend")

    monkeypatch.setattr(keyring, "get_password", raise_no_keyring)
    store = CredentialStore(service_name="com.basil.test")

    with pytest.raises(CredentialStoreUnavailableError):
        store.read("openai")
