"""Thread-safe pool of pre-warmed model instances."""
import threading
from typing import Callable, Generic, List, TypeVar


T = TypeVar("T")


class ModelPool(Generic[T]):
    """Keep slow model loads outside the lock and caller event loop."""

    def __init__(self, loader: Callable[[], T], initial_count: int = 0):
        self._loader = loader
        self._lock = threading.Lock()
        self._items: List[T] = [loader() for _ in range(initial_count)]
        self._reservations = 0

    def pop(self) -> T:
        """Return a ready instance, loading only when the pool is empty."""
        with self._lock:
            if self._items:
                if self._reservations:
                    self._reservations -= 1
                return self._items.pop()
        return self._loader()

    def refill_one(self) -> None:
        """Load one instance outside the lock and append it."""
        item = self._loader()
        with self._lock:
            self._items.append(item)

    def ensure_ready(self) -> None:
        """Reserve one instance before an event-loop caller synchronously pops it."""
        with self._lock:
            if len(self._items) > self._reservations:
                self._reservations += 1
                return
        item = self._loader()
        with self._lock:
            self._items.append(item)
            self._reservations += 1
