"""Numeric bounds and retention constants for managed file history.

Settled defaults (Workstream C decision groups 4 and 5). Binary/PDF files
are categorically out of scope under decision 1 (structured text writes
only), so these bounds apply only to in-scope UTF-8 text content.
"""

from __future__ import annotations

MAX_CHANGE_BYTES = 10 * 1024 * 1024
MAX_TASK_BYTES = 50 * 1024 * 1024
MAX_STORE_BYTES = 2 * 1024 * 1024 * 1024
MAX_VERSIONS_PER_FILE = 50
MAX_VERSION_AGE_DAYS = 90


class ManagedHistoryBoundsExceededError(RuntimeError):
    """Raised when a managed write would exceed a durable storage bound."""
