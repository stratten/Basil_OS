"""Run-scoped model leases.

An agent run obtains its local model deep inside the graph (the coordinator
resolves it lazily), but the run itself starts and ends in one place. A
``ModelRunScope`` is opened where the run starts. Whatever model the run ends up
using is attached to the scope and leased until the scope exits, so the idle
timer can never unload a model in the middle of a long tool call.

The scope lives in a ``ContextVar``. Tasks spawned inside the run copy the
context, but they all see the same scope object, so a lease taken in a child
task is still released when the run ends.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Iterator, List, Optional

logger = logging.getLogger(__name__)

_current_scope: ContextVar[Optional["ModelRunScope"]] = ContextVar(
    "basil_model_run_scope", default=None
)


class ModelRunScope:
    """Holds the model leases taken by one agent run."""

    def __init__(self, owner: str = "") -> None:
        self.owner = owner
        self._leases: List[Any] = []
        self._attached_ids: set[int] = set()
        self._closed = False

    def __deepcopy__(self, memo: dict) -> "ModelRunScope":
        # Run state can be deep-copied (checkpoints, retries). Leases must stay
        # with the one scope that owns them, so a copy is the same scope.
        return self

    def attach(self, model: Any, manager: Any = None) -> bool:
        """Lease ``model`` for the rest of the run. Returns True if a lease is now held.

        Attaching the same model twice is a no-op. Models the manager does not
        track (API clients) have nothing to hold and return False.
        """
        if self._closed or model is None:
            return False
        if id(model) in self._attached_ids:
            return True
        if manager is None:
            from api.core.services.model_service import get_model_service

            manager = get_model_service().model_manager
        lease = manager.acquire_lease_for_model(model, owner=self.owner or "agent_run")
        if lease is None:
            return False
        self._attached_ids.add(id(model))
        self._leases.append(lease)
        return True

    def close(self) -> None:
        """Release every lease. Safe to call more than once."""
        self._closed = True
        leases, self._leases = self._leases, []
        self._attached_ids.clear()
        for lease in leases:
            try:
                lease.release()
            except Exception as exc:  # pragma: no cover - release is not expected to fail
                logger.warning("Model lease release failed: %s", exc)

    @property
    def lease_count(self) -> int:
        return len(self._leases)


@contextmanager
def model_run_scope(owner: str = "") -> Iterator[ModelRunScope]:
    """Open a scope that releases its model leases on exit, however the run ends."""
    scope = ModelRunScope(owner=owner)
    token = _current_scope.set(scope)
    try:
        yield scope
    finally:
        try:
            _current_scope.reset(token)
        except ValueError:
            # Closed from a different context than it was opened in; the leases
            # below are still released, which is what matters.
            _current_scope.set(None)
        scope.close()


def current_model_run_scope() -> Optional[ModelRunScope]:
    return _current_scope.get()


def attach_model_to_current_run(model: Any, manager: Any = None) -> bool:
    """Lease ``model`` for the current run, if a run scope is open. Never raises."""
    scope = _current_scope.get()
    if scope is None:
        return False
    try:
        return scope.attach(model, manager=manager)
    except Exception as exc:
        logger.warning("Could not lease model for the current run: %s", exc)
        return False
