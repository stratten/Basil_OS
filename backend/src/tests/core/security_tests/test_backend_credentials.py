"""Tests for the per-launch backend credentials file."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from api.core.security import backend_credentials
from api.core.security.backend_credentials import BackendCredentials, BackendCredentialStore


def _valid_payload(host: str = "a" * 64, webview: str = "b" * 64) -> dict:
    return {"version": 1, "host_token": host, "webview_token": webview, "created_at": "2026-01-01T00:00:00+00:00"}


def _write(path: Path, payload: object, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    os.chmod(path, mode)


def test_current_creates_a_private_file_with_distinct_tokens(tmp_path: Path) -> None:
    path = tmp_path / "runtime" / "backend_credentials.json"

    credentials = BackendCredentialStore(path).current()

    assert path.is_file()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert len(credentials.host_token) == 64
    assert len(credentials.webview_token) == 64
    assert credentials.host_token != credentials.webview_token
    assert BackendCredentials.parse(path.read_bytes()) == credentials
    assert list(path.parent.glob(".backend_credentials.*.tmp")) == []


def test_current_reuses_a_valid_existing_file(tmp_path: Path) -> None:
    path = tmp_path / "backend_credentials.json"
    _write(path, _valid_payload())

    assert BackendCredentialStore(path).current() == BackendCredentials(host_token="a" * 64, webview_token="b" * 64)


def test_current_rereads_the_file_after_another_process_rotates_it(tmp_path: Path) -> None:
    path = tmp_path / "backend_credentials.json"
    _write(path, _valid_payload())
    store = BackendCredentialStore(path)
    assert store.current().host_token == "a" * 64

    replacement = tmp_path / "replacement.json"
    _write(replacement, _valid_payload(host="c" * 64, webview="d" * 64))
    os.replace(replacement, path)

    assert store.current() == BackendCredentials(host_token="c" * 64, webview_token="d" * 64)


@pytest.mark.parametrize(
    "raw",
    [
        b"not json",
        b"[]",
        json.dumps({**_valid_payload(), "version": 2}).encode("utf-8"),
        json.dumps({**_valid_payload(), "version": True}).encode("utf-8"),
        json.dumps(_valid_payload(host="a" * 63)).encode("utf-8"),
        json.dumps(_valid_payload(host="A" * 64)).encode("utf-8"),
        json.dumps(_valid_payload(host="a" * 64, webview="a" * 64)).encode("utf-8"),
        json.dumps({"version": 1, "host_token": "a" * 64}).encode("utf-8"),
    ],
)
def test_current_replaces_an_invalid_file(tmp_path: Path, raw: bytes) -> None:
    path = tmp_path / "backend_credentials.json"
    path.write_bytes(raw)
    os.chmod(path, 0o600)

    credentials = BackendCredentialStore(path).current()

    assert BackendCredentials.parse(path.read_bytes()) == credentials
    assert credentials.host_token != "a" * 64


def test_current_replaces_a_group_readable_file(tmp_path: Path) -> None:
    path = tmp_path / "backend_credentials.json"
    _write(path, _valid_payload(), mode=0o644)

    credentials = BackendCredentialStore(path).current()

    assert credentials.host_token != "a" * 64
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_classify_distinguishes_host_webview_and_unknown_tokens(tmp_path: Path) -> None:
    path = tmp_path / "backend_credentials.json"
    _write(path, _valid_payload())
    store = BackendCredentialStore(path)

    assert store.classify("a" * 64) == "host"
    assert store.classify("b" * 64) == "webview"
    assert store.classify("c" * 64) is None
    assert store.classify("a" * 64 + "0") is None
    assert store.classify("") is None
    assert store.classify(None) is None
    assert store.classify("é" * 64) is None


def test_rotate_replaces_a_valid_file_and_readers_follow(tmp_path: Path) -> None:
    path = tmp_path / "backend_credentials.json"
    _write(path, _valid_payload())
    reader = BackendCredentialStore(path)
    assert reader.current().host_token == "a" * 64

    rotated = BackendCredentialStore(path).rotate()

    assert rotated.host_token != "a" * 64
    assert rotated.webview_token != "b" * 64
    assert reader.current() == rotated
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert list(path.parent.glob(".backend_credentials.*.tmp")) == []


def test_rotate_creates_a_missing_file(tmp_path: Path) -> None:
    path = tmp_path / "runtime" / "backend_credentials.json"

    rotated = BackendCredentialStore(path).rotate()

    assert BackendCredentials.parse(path.read_bytes()) == rotated


@pytest.mark.parametrize(("environment_value", "expect_rotation"), [("1", True), (None, False), ("0", False), ("true", False)])
def test_startup_preparation_rotates_only_when_the_launcher_opts_in(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    environment_value: str | None,
    expect_rotation: bool,
) -> None:
    path = tmp_path / "backend_credentials.json"
    _write(path, _valid_payload())
    store = BackendCredentialStore(path)
    monkeypatch.setattr(backend_credentials, "get_backend_credential_store", lambda: store)
    if environment_value is None:
        monkeypatch.delenv(backend_credentials.ROTATE_ON_STARTUP_ENV, raising=False)
    else:
        monkeypatch.setenv(backend_credentials.ROTATE_ON_STARTUP_ENV, environment_value)

    prepared = backend_credentials.prepare_backend_credentials_for_startup()

    assert prepared is store
    assert (store.current().host_token != "a" * 64) is expect_rotation


def test_permission_check_is_platform_aware(tmp_path: Path) -> None:
    path = tmp_path / "backend_credentials.json"
    _write(path, _valid_payload(), mode=0o644)
    stat_result = path.stat()

    assert backend_credentials._is_private_to_current_user(stat_result, platform_name="posix") is False
    assert backend_credentials._is_private_to_current_user(stat_result, platform_name="nt") is True
