"""In-memory one-time store for browser sensitive-fill values."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from threading import Lock
from typing import Dict, Optional


@dataclass
class SensitiveValueRecord:
    value: str
    expires_at: float


class BrowserSensitiveValueStore:
    """Process-local token store for sensitive values."""

    def __init__(self, default_ttl_seconds: int = 300) -> None:
        self.default_ttl_seconds = default_ttl_seconds
        self._values: Dict[str, SensitiveValueRecord] = {}
        self._lock = Lock()

    def store_sensitive_value(self, value: str, ttl_seconds: Optional[int] = None) -> str:
        """Store a value and return a one-time token."""
        token = str(uuid.uuid4())
        ttl = ttl_seconds if ttl_seconds is not None else self.default_ttl_seconds
        with self._lock:
            self._cleanup_expired_locked()
            self._values[token] = SensitiveValueRecord(
                value=value,
                expires_at=time.time() + ttl,
            )
        return token

    def consume_sensitive_value(self, token: str) -> Optional[str]:
        """Consume and delete a value by token."""
        with self._lock:
            self._cleanup_expired_locked()
            record = self._values.pop(token, None)
            if record is None:
                return None
            if record.expires_at < time.time():
                return None
            return record.value

    def _cleanup_expired_locked(self) -> None:
        now = time.time()
        expired_tokens = [
            token
            for token, record in self._values.items()
            if record.expires_at < now
        ]
        for token in expired_tokens:
            self._values.pop(token, None)


_SENSITIVE_VALUE_STORE = BrowserSensitiveValueStore()


def get_browser_sensitive_value_store() -> BrowserSensitiveValueStore:
    """Return the process-local browser sensitive value store."""
    return _SENSITIVE_VALUE_STORE

