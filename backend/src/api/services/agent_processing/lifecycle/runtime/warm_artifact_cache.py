"""Process-wide warm cache for conversation-agnostic agent artifacts (P5).

Stores artifacts that are expensive to build but depend only on the runtime
*environment* (installed services, active model, tool-rendering profile), NOT
on the specific conversation/turn. A lookup is a hit only when the caller's
signature matches the stored one AND the entry is within its idle TTL; a
changed signature (model switch, a service that failed to initialize this run,
profile change) forces a rebuild, so no explicit invalidation wiring at every
mutation site is required.

This is a deterministic fingerprint cache. It performs NO classification or
heuristic matching of any kind.
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, Optional, Tuple

DEFAULT_TTL_SECONDS = 300.0


def compute_environment_signature(
    *,
    model_id: str,
    tool_rendering: str,
    available_service_names: Tuple[str, ...],
) -> str:
    """Deterministic fingerprint of everything the cached artifacts depend on."""
    raw = "|".join(
        [
            f"model={model_id or 'none'}",
            f"tool_rendering={tool_rendering or 'none'}",
            "services=" + ",".join(sorted(available_service_names)),
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass
class _Entry:
    signature: str
    value: Any
    created_at: float


class WarmArtifactCache:
    """Async-safe get-or-build keyed cache with per-entry signature + idle TTL."""

    def __init__(self) -> None:
        self._entries: Dict[str, _Entry] = {}
        self._locks: Dict[str, asyncio.Lock] = {}
        self._global_lock = asyncio.Lock()

    async def _lock_for(self, key: str) -> asyncio.Lock:
        async with self._global_lock:
            lock = self._locks.get(key)
            if lock is None:
                lock = asyncio.Lock()
                self._locks[key] = lock
            return lock

    async def get_or_build(
        self,
        *,
        key: str,
        signature: str,
        builder: Callable[[], Awaitable[Any]],
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
    ) -> Tuple[Any, bool]:
        """Return (value, was_hit). Rebuild on signature change or TTL expiry.

        The builder runs under a per-key lock so concurrent turns sharing a key
        build at most once.
        """
        now = time.monotonic()
        entry = self._entries.get(key)
        if (
            entry is not None
            and entry.signature == signature
            and (now - entry.created_at) < ttl_seconds
        ):
            return entry.value, True

        lock = await self._lock_for(key)
        async with lock:
            entry = self._entries.get(key)
            now = time.monotonic()
            if (
                entry is not None
                and entry.signature == signature
                and (now - entry.created_at) < ttl_seconds
            ):
                return entry.value, True
            value = await builder()
            self._entries[key] = _Entry(
                signature=signature, value=value, created_at=time.monotonic()
            )
            return value, False

    def invalidate(self, key: Optional[str] = None) -> None:
        if key is None:
            self._entries.clear()
        else:
            self._entries.pop(key, None)


_WARM_ARTIFACT_CACHE: Optional[WarmArtifactCache] = None


def get_warm_artifact_cache() -> WarmArtifactCache:
    global _WARM_ARTIFACT_CACHE
    if _WARM_ARTIFACT_CACHE is None:
        _WARM_ARTIFACT_CACHE = WarmArtifactCache()
    return _WARM_ARTIFACT_CACHE
