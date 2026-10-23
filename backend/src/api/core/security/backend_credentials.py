"""Per-launch loopback credentials written by the Basil backend and read by every native shell."""

from __future__ import annotations

import hmac
import json
import os
import secrets
import stat
import tempfile
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional, TypeGuard

BACKEND_TOKEN_HEADER = "X-Basil-Token"
WEBSOCKET_TOKEN_PROTOCOL_PREFIX = "basil.token."
WEBSOCKET_ACCEPT_PROTOCOL = "basil.v1"
CREDENTIALS_FILE_VERSION = 1
ROTATE_ON_STARTUP_ENV = "BASIL_ROTATE_BACKEND_CREDENTIALS"
_TOKEN_HEX_LENGTH = 64
_HEX_DIGITS = frozenset("0123456789abcdef")

CredentialType = Literal["host", "webview"]


def default_credentials_path() -> Path:
    return Path.home() / ".basil" / "runtime" / "backend_credentials.json"


def _is_valid_token(value: object) -> TypeGuard[str]:
    return isinstance(value, str) and len(value) == _TOKEN_HEX_LENGTH and set(value) <= _HEX_DIGITS


def _is_private_to_current_user(stat_result: os.stat_result, platform_name: str = os.name) -> bool:
    if platform_name == "nt":
        return True
    return stat_result.st_uid == os.getuid() and not stat.S_IMODE(stat_result.st_mode) & 0o077


@dataclass(frozen=True)
class BackendCredentials:
    host_token: str
    webview_token: str

    @classmethod
    def generate(cls) -> "BackendCredentials":
        return cls(host_token=secrets.token_hex(32), webview_token=secrets.token_hex(32))

    @classmethod
    def parse(cls, raw: bytes) -> Optional["BackendCredentials"]:
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict):
            return None
        version = payload.get("version")
        if isinstance(version, bool) or not isinstance(version, int) or version != CREDENTIALS_FILE_VERSION:
            return None
        host_token = payload.get("host_token")
        webview_token = payload.get("webview_token")
        if not _is_valid_token(host_token) or not _is_valid_token(webview_token):
            return None
        if host_token == webview_token:
            return None
        return cls(host_token=host_token, webview_token=webview_token)

    def serialize(self) -> bytes:
        payload = {
            "version": CREDENTIALS_FILE_VERSION,
            "host_token": self.host_token,
            "webview_token": self.webview_token,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        return json.dumps(payload, sort_keys=True).encode("utf-8")


class BackendCredentialStore:
    """Loads, creates, rotates, and caches the credentials file, re-reading it whenever it changes on disk."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._cached: Optional[BackendCredentials] = None
        self._cached_signature: Optional[tuple[int, int, int]] = None

    @property
    def path(self) -> Path:
        return self._path

    def current(self) -> BackendCredentials:
        with self._lock:
            credentials = self._read_if_changed()
            if credentials is not None:
                return credentials
            self._write_fresh_credentials(replace_existing=self._stat() is not None)
            credentials = self._read_if_changed()
            if credentials is None:
                raise OSError(f"Backend credentials at {self._path} are unreadable after creation.")
            return credentials

    def rotate(self) -> BackendCredentials:
        with self._lock:
            self._write_fresh_credentials(replace_existing=True)
            credentials = self._read_if_changed()
            if credentials is None:
                raise OSError(f"Backend credentials at {self._path} are unreadable after rotation.")
            return credentials

    def classify(self, token: Optional[str]) -> Optional[CredentialType]:
        if not token or not token.isascii():
            return None
        credentials = self.current()
        encoded = token.encode("ascii")
        if hmac.compare_digest(encoded, credentials.host_token.encode("ascii")):
            return "host"
        if hmac.compare_digest(encoded, credentials.webview_token.encode("ascii")):
            return "webview"
        return None

    def _stat(self) -> Optional[os.stat_result]:
        try:
            return self._path.stat()
        except FileNotFoundError:
            return None

    def _read_if_changed(self) -> Optional[BackendCredentials]:
        stat_result = self._stat()
        if stat_result is None:
            self._cached = None
            self._cached_signature = None
            return None
        signature = (stat_result.st_ino, stat_result.st_mtime_ns, stat_result.st_size)
        if signature == self._cached_signature and self._cached is not None:
            return self._cached
        self._cached = None
        self._cached_signature = None
        if not _is_private_to_current_user(stat_result):
            return None
        try:
            raw = self._path.read_bytes()
        except FileNotFoundError:
            return None
        credentials = BackendCredentials.parse(raw)
        if credentials is not None:
            self._cached = credentials
            self._cached_signature = signature
        return credentials

    def _write_fresh_credentials(self, *, replace_existing: bool) -> None:
        directory = self._path.parent
        directory.mkdir(parents=True, exist_ok=True)
        file_descriptor, temporary_name = tempfile.mkstemp(
            prefix=".backend_credentials.", suffix=".tmp", dir=directory
        )
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(file_descriptor, "wb") as handle:
                handle.write(BackendCredentials.generate().serialize())
                handle.flush()
                os.fsync(handle.fileno())
            if replace_existing:
                os.replace(temporary_path, self._path)
            else:
                try:
                    os.link(temporary_path, self._path)
                except FileExistsError:
                    pass
        finally:
            temporary_path.unlink(missing_ok=True)


_default_store: Optional[BackendCredentialStore] = None
_default_store_lock = threading.Lock()


def get_backend_credential_store() -> BackendCredentialStore:
    global _default_store
    with _default_store_lock:
        if _default_store is None:
            _default_store = BackendCredentialStore(default_credentials_path())
        return _default_store


def load_host_token() -> str:
    return get_backend_credential_store().current().host_token


def prepare_backend_credentials_for_startup() -> BackendCredentialStore:
    store = get_backend_credential_store()
    if os.environ.get(ROTATE_ON_STARTUP_ENV) == "1":
        store.rotate()
    else:
        store.current()
    return store
