"""Process-local delivery registry bridging a provider-interaction HTTP answer to a waiting live ACP request.

Mirrors `InteractiveApprovalManager`'s `_pending_approvals` class-level
future registry. This registry never persists anything — `ProviderInteractionRepository`
is the durable authority. A future here only survives for the lifetime of
the backend process and the live provider run awaiting it; a backend
restart loses all pending futures, which is the accepted Package-4A/4C
boundary (no restart recovery in this package).
"""
from __future__ import annotations

import asyncio
from typing import Any


class ProviderInteractionDeliveryRegistry:
    """Class-level registry of pending provider-interaction futures, keyed by interaction id."""

    _pending: dict[str, "asyncio.Future[dict[str, Any]]"] = {}
    _resolving: set[str] = set()

    @classmethod
    def register(cls, interaction_id: str) -> "asyncio.Future[dict[str, Any]]":
        """Create and track the future a coordinator will await for one interaction."""
        future: "asyncio.Future[dict[str, Any]]" = asyncio.get_running_loop().create_future()
        cls._pending[interaction_id] = future
        return future

    @classmethod
    def has_pending(cls, interaction_id: str) -> bool:
        """Return whether a live coordinator is still awaiting this interaction."""
        future = cls._pending.get(interaction_id)
        return future is not None and not future.done()

    @classmethod
    def claim(cls, interaction_id: str) -> bool:
        """Reserve a pending future while its durable resolution is recorded."""
        if interaction_id in cls._resolving or not cls.has_pending(interaction_id):
            return False
        cls._resolving.add(interaction_id)
        return True

    @classmethod
    def deliver_claimed(cls, interaction_id: str, outcome: str, values: dict[str, Any] | None) -> bool:
        """Resolve a future previously reserved by `claim`."""
        future = cls._pending.get(interaction_id)
        if interaction_id not in cls._resolving or future is None or future.done():
            return False
        try:
            future.set_result({"outcome": outcome, "values": values})
            return True
        finally:
            cls._resolving.discard(interaction_id)

    @classmethod
    def release_claim(cls, interaction_id: str) -> None:
        """Release a reservation after its durable write could not complete."""
        cls._resolving.discard(interaction_id)

    @classmethod
    def resolve(cls, interaction_id: str, outcome: str, values: dict[str, Any] | None) -> bool:
        """Resolve a pending future. Returns False when unknown, already resolving, or already done."""
        if not cls.claim(interaction_id):
            return False
        return cls.deliver_claimed(interaction_id, outcome, values)

    @classmethod
    def discard(cls, interaction_id: str) -> None:
        """Remove a completed or abandoned interaction's future from the registry."""
        cls._resolving.discard(interaction_id)
        cls._pending.pop(interaction_id, None)


__all__ = ["ProviderInteractionDeliveryRegistry"]
