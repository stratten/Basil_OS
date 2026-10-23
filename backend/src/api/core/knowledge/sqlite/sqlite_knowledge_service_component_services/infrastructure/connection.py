"""Shared database connection factory and utilities for SQLite knowledge service components.

Centralizes connection creation, PRAGMA configuration, writer coordination, and
schema bootstrapping so that individual component services don't duplicate this
logic.

Writer coordination
--------------------
Every connection returned by ``get_sync_connection``/``get_async_connection`` is
an instance of ``_CoordinatedConnection``. That subclass installs a SQLite
authorizer (``sqlite3.Connection.set_authorizer``) that intercepts every
mutating statement -- inserts, updates, deletes, schema DDL, attach/detach, and
explicit ``BEGIN`` -- before SQLite executes it. The first such statement on a
connection admits that connection into a strict-FIFO, per-canonical-database-
path queue (``_WriteCoordinator``); the connection holds its queue position
until it commits, rolls back, or closes, so a whole read-modify-write
transaction is treated as one admission. Plain reads (``SELECT``, ``PRAGMA``)
never join the queue, so WAL reader concurrency is unaffected. This closes the
gap where ``TodoRepository`` (and other repositories that call
``conn.execute("BEGIN IMMEDIATE")`` or issue autocommit-style writes directly)
previously bypassed the old ``run_write_transaction``-only gate and could race
another writer for SQLite's single-writer lock on the same file, surfacing as
"database is locked" ``OperationalError``s.

The coordinator is process-local. It prevents same-process writer races; it
does not, and cannot, coordinate a second OS process that opens the same
database file. The existing SQLite ``busy_timeout`` PRAGMA remains the last
defense against that separate scenario.
"""

from __future__ import annotations

import asyncio
import collections
import hashlib
import logging
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Deque, Optional, TypeVar

import aiosqlite

from ...schema import get_schema_statements

logger = logging.getLogger(__name__)

REQUIRED_TABLES = [
    "activities",
    "transcriptions",
    "activity_metadata",
    "activity_patterns",
]

DEFAULT_BUSY_TIMEOUT_MS = 5000
DEFAULT_SYNCHRONOUS_MODE = "NORMAL"
MAX_WRITE_RETRY_ATTEMPTS = 5
INITIAL_RETRY_DELAY_SECONDS = 0.01
MAX_RETRY_DELAY_SECONDS = 0.5
WRITE_OPERATION_CEILING_SECONDS = 30.0

T = TypeVar("T")

# SQLite authorizer action codes. Python's ``sqlite3`` module does not expose
# these as attributes, so they are declared here from SQLite's public, stable
# ``sqlite3.h`` numbering. Only the codes relevant to classifying a statement
# as a write (or an explicit transaction start) are declared; codes irrelevant
# to that classification (e.g. SQLITE_READ, SQLITE_SELECT, SQLITE_FUNCTION)
# are intentionally omitted so they fall through to the "not a write" branch.
_ACTION_CREATE_INDEX = 1
_ACTION_CREATE_TABLE = 2
_ACTION_CREATE_TEMP_INDEX = 3
_ACTION_CREATE_TEMP_TABLE = 4
_ACTION_CREATE_TEMP_TRIGGER = 5
_ACTION_CREATE_TEMP_VIEW = 6
_ACTION_CREATE_TRIGGER = 7
_ACTION_CREATE_VIEW = 8
_ACTION_DELETE = 9
_ACTION_DROP_INDEX = 10
_ACTION_DROP_TABLE = 11
_ACTION_DROP_TEMP_INDEX = 12
_ACTION_DROP_TEMP_TABLE = 13
_ACTION_DROP_TEMP_TRIGGER = 14
_ACTION_DROP_TEMP_VIEW = 15
_ACTION_DROP_TRIGGER = 16
_ACTION_DROP_VIEW = 17
_ACTION_INSERT = 18
_ACTION_TRANSACTION = 22
_ACTION_UPDATE = 23
_ACTION_ATTACH = 24
_ACTION_DETACH = 25
_ACTION_ALTER_TABLE = 26
_ACTION_REINDEX = 27
_ACTION_ANALYZE = 28

_WRITE_ACTIONS = frozenset(
    {
        _ACTION_CREATE_INDEX,
        _ACTION_CREATE_TABLE,
        _ACTION_CREATE_TEMP_INDEX,
        _ACTION_CREATE_TEMP_TABLE,
        _ACTION_CREATE_TEMP_TRIGGER,
        _ACTION_CREATE_TEMP_VIEW,
        _ACTION_CREATE_TRIGGER,
        _ACTION_CREATE_VIEW,
        _ACTION_DELETE,
        _ACTION_DROP_INDEX,
        _ACTION_DROP_TABLE,
        _ACTION_DROP_TEMP_INDEX,
        _ACTION_DROP_TEMP_TABLE,
        _ACTION_DROP_TEMP_TRIGGER,
        _ACTION_DROP_TEMP_VIEW,
        _ACTION_DROP_TRIGGER,
        _ACTION_DROP_VIEW,
        _ACTION_INSERT,
        _ACTION_UPDATE,
        _ACTION_ATTACH,
        _ACTION_DETACH,
        _ACTION_ALTER_TABLE,
        _ACTION_REINDEX,
        _ACTION_ANALYZE,
    }
)

# SQLite authorizer return codes (``sqlite3.h``: SQLITE_OK=0, SQLITE_DENY=1).
# Declared locally rather than relying on ``sqlite3.SQLITE_OK`` for the same
# portability reason as the action codes above.
_AUTHORIZER_OK = 0
_AUTHORIZER_DENY = 1


class SQLiteWriteTimeoutError(RuntimeError):
    """Raised when a write could not be admitted to the per-database-file
    write coordinator within its budget."""

    def __init__(self, db_path: str, operation_name: str, budget_seconds: float):
        super().__init__(
            f"Timed out after {budget_seconds:.1f}s waiting for the SQLite write "
            f"coordinator for {db_path!r} during {operation_name!r}"
        )
        self.db_path = db_path
        self.operation_name = operation_name
        self.budget_seconds = budget_seconds


def _current_task_name() -> Optional[str]:
    """Return the current asyncio task name when this executes on an event loop."""
    try:
        task = asyncio.current_task()
    except RuntimeError:
        return None
    return task.get_name() if task is not None else None


def _summarize_write_statement(sql: object) -> str:
    """Keep timeout diagnostics useful without logging SQL values or parameters."""
    words = str(sql).strip().split()
    return " ".join(words[:4])[:160] or "(write statement unavailable)"


@dataclass(frozen=True)
class _WriteHolder:
    token: object
    operation_name: str
    statement_summary: str
    acquired_at: float
    thread_id: int
    thread_name: str
    task_name: Optional[str]


class _WriteCoordinator:
    """Strict-FIFO admission queue for write transactions against one
    canonical database file path. Read-only statements never call into this
    class, so WAL reader concurrency is unaffected."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._condition = threading.Condition()
        self._queue: Deque[object] = collections.deque()
        self._holder: Optional[_WriteHolder] = None

    def acquire(
        self,
        token: object,
        deadline: float,
        *,
        operation_name: str = "unspecified_write",
        statement_summary: str = "(write statement unavailable)",
    ) -> None:
        with self._condition:
            self._queue.append(token)
            while True:
                if self._holder is None and self._queue and self._queue[0] is token:
                    self._holder = _WriteHolder(
                        token=token,
                        operation_name=operation_name,
                        statement_summary=statement_summary,
                        acquired_at=time.monotonic(),
                        thread_id=threading.get_ident(),
                        thread_name=threading.current_thread().name,
                        task_name=_current_task_name(),
                    )
                    self._queue.popleft()
                    return
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    try:
                        self._queue.remove(token)
                    except ValueError:
                        pass
                    raise TimeoutError()
                self._condition.wait(timeout=remaining)

    def release(self, token: object) -> None:
        with self._condition:
            if self._holder is not None and self._holder.token is token:
                self._holder = None
            self._condition.notify_all()

    def timeout_diagnostics(self) -> dict[str, object]:
        """Return non-sensitive holder state after an admission timeout."""
        with self._condition:
            holder = self._holder
            return {
                "holder_operation": holder.operation_name if holder else None,
                "holder_statement": holder.statement_summary if holder else None,
                "holder_age_seconds": round(time.monotonic() - holder.acquired_at, 3) if holder else None,
                "holder_thread_id": holder.thread_id if holder else None,
                "holder_thread_name": holder.thread_name if holder else None,
                "holder_task_name": holder.task_name if holder else None,
                "queued_writers": len(self._queue),
            }


_write_coordinators: dict[str, _WriteCoordinator] = {}
_write_coordinators_guard = threading.Lock()


def _canonical_db_path(db_path: str) -> str:
    """Resolve to an absolute path so relative and absolute references to the
    same file share one coordinator instance."""
    try:
        return str(Path(db_path).expanduser().resolve())
    except OSError:
        return str(Path(db_path).expanduser())


def _coordinator_for(db_path: str) -> _WriteCoordinator:
    canonical_path = _canonical_db_path(db_path)
    with _write_coordinators_guard:
        coordinator = _write_coordinators.get(canonical_path)
        if coordinator is None:
            coordinator = _WriteCoordinator(canonical_path)
            _write_coordinators[canonical_path] = coordinator
        return coordinator


class _CoordinatedConnection(sqlite3.Connection):
    """``sqlite3.Connection`` that joins the shared per-database-file write
    coordinator before any mutating statement or explicit ``BEGIN`` executes,
    and releases its queue position exactly once when the transaction ends."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        database = args[0] if args else kwargs.get("database", "")
        self._basil_db_path = str(database)
        self._basil_operation_name = "unspecified_write"
        self._basil_budget_seconds = WRITE_OPERATION_CEILING_SECONDS
        self._basil_write_token: Optional[object] = None
        self._basil_pending_timeout_error: Optional[SQLiteWriteTimeoutError] = None
        self._basil_statement_summary = "(write statement unavailable)"
        self.set_authorizer(self._basil_authorize)

    def _basil_authorize(self, action, arg1, arg2, db_name, trigger_name):
        if self._basil_write_token is not None:
            return _AUTHORIZER_OK
        if action == _ACTION_TRANSACTION:
            if (arg1 or "").upper() != "BEGIN":
                return _AUTHORIZER_OK
        elif action not in _WRITE_ACTIONS:
            return _AUTHORIZER_OK

        coordinator = _coordinator_for(self._basil_db_path)
        deadline = time.monotonic() + self._basil_budget_seconds
        token = object()
        try:
            coordinator.acquire(
                token,
                deadline,
                operation_name=self._basil_operation_name,
                statement_summary=self._basil_statement_summary,
            )
        except TimeoutError:
            diagnostics = coordinator.timeout_diagnostics()
            logger.warning(
                "SQLite write coordinator timeout for %s (operation=%s, budget=%.1fs, holder_operation=%s, holder_statement=%s, holder_age_seconds=%s, holder_thread=%s:%s, holder_task=%s, queued_writers=%s)",
                coordinator.db_path,
                self._basil_operation_name,
                self._basil_budget_seconds,
                diagnostics["holder_operation"],
                diagnostics["holder_statement"],
                diagnostics["holder_age_seconds"],
                diagnostics["holder_thread_name"],
                diagnostics["holder_thread_id"],
                diagnostics["holder_task_name"],
                diagnostics["queued_writers"],
            )
            self._basil_pending_timeout_error = SQLiteWriteTimeoutError(
                coordinator.db_path, self._basil_operation_name, self._basil_budget_seconds
            )
            return _AUTHORIZER_DENY
        self._basil_write_token = token
        return _AUTHORIZER_OK

    def _basil_release_write_token(self) -> None:
        token = self._basil_write_token
        if token is not None:
            self._basil_write_token = None
            _coordinator_for(self._basil_db_path).release(token)

    def execute(self, sql, parameters=()):
        self._basil_statement_summary = _summarize_write_statement(sql)
        try:
            return super().execute(sql, parameters)
        except sqlite3.DatabaseError as exc:
            self._basil_raise_pending_timeout(exc)

    def executemany(self, sql, parameters):
        self._basil_statement_summary = _summarize_write_statement(sql)
        try:
            return super().executemany(sql, parameters)
        except sqlite3.DatabaseError as exc:
            self._basil_raise_pending_timeout(exc)

    def executescript(self, sql_script):
        self._basil_statement_summary = _summarize_write_statement(sql_script)
        try:
            return super().executescript(sql_script)
        except sqlite3.DatabaseError as exc:
            self._basil_raise_pending_timeout(exc)

    def _basil_raise_pending_timeout(self, exc: sqlite3.DatabaseError) -> None:
        pending = self._basil_pending_timeout_error
        if pending is not None:
            self._basil_pending_timeout_error = None
            raise pending
        raise exc

    def commit(self) -> None:
        try:
            super().commit()
        finally:
            self._basil_release_write_token()

    def rollback(self) -> None:
        try:
            super().rollback()
        finally:
            self._basil_release_write_token()

    def close(self) -> None:
        try:
            super().close()
        finally:
            self._basil_release_write_token()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, exc_tb):
        # sqlite3.Connection.__exit__ commits/rolls back in C and never calls
        # the Python commit()/rollback() overrides, which would leak the FIFO
        # token and deadlock the next same-process writer for this file.
        try:
            if exc_type is None:
                try:
                    self.commit()
                except Exception:
                    self.rollback()
                    raise
            else:
                self.rollback()
        finally:
            self._basil_release_write_token()
        return False


class _AsyncCoordinatedConnection(_CoordinatedConnection):
    """Coordinator-aware connection used by aiosqlite worker threads."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._basil_operation_name = "async_write"


def _configure_sync_connection(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(f"PRAGMA busy_timeout = {DEFAULT_BUSY_TIMEOUT_MS}")
    conn.execute(f"PRAGMA synchronous = {DEFAULT_SYNCHRONOUS_MODE}")


async def _configure_async_connection(
    conn: aiosqlite.Connection, *, foreign_keys: bool = True
) -> None:
    if foreign_keys:
        await conn.execute("PRAGMA foreign_keys = ON")
    await conn.execute(f"PRAGMA busy_timeout = {DEFAULT_BUSY_TIMEOUT_MS}")
    await conn.execute(f"PRAGMA synchronous = {DEFAULT_SYNCHRONOUS_MODE}")


_initialized_wal_databases: set[str] = set()
_initialized_wal_guard = threading.Lock()


def initialize_sqlite_database_mode(db_path: str) -> None:
    """Configure WAL journal mode once during database startup."""
    with _initialized_wal_guard:
        if db_path in _initialized_wal_databases:
            return
        conn = sqlite3.connect(db_path)
        try:
            conn.execute("PRAGMA foreign_keys = ON")
            cursor = conn.execute("PRAGMA journal_mode = WAL")
            mode = cursor.fetchone()[0]
            if str(mode).lower() != "wal":
                raise RuntimeError(
                    f"Failed to enable WAL mode for {db_path!r}, got {mode!r}"
                )
            conn.commit()
            _initialized_wal_databases.add(db_path)
            logger.info("SQLite WAL mode initialized for %s", db_path)
        finally:
            conn.close()


def _is_lock_error(exc: Exception) -> bool:
    if isinstance(exc, sqlite3.OperationalError):
        message = str(exc).lower()
        return "database is locked" in message or "database is busy" in message
    return False


def get_sync_connection(
    db_path: str,
    *,
    ensure_schema: bool = True,
    operation_name: str = "unspecified_write",
) -> sqlite3.Connection:
    """Get a synchronous database connection with proper configuration.

    Args:
        db_path: Path to the SQLite database file.
        ensure_schema: If True, verify required tables exist and create any
            that are missing. Set to False when the caller only needs a
            lightweight connection (e.g. for a single PRAGMA query).
        operation_name: Short label used in write-coordinator timeout errors
            and logs if this connection is used to write. Purely diagnostic;
            has no effect on read-only use of the connection.

    Returns:
        A configured ``sqlite3.Connection`` with Row factory, foreign keys
        enabled, and a finite busy timeout. Journal mode is configured once at
        startup via ``initialize_sqlite_database_mode``. The connection
        transparently joins the shared per-database-file write coordinator
        the first time it executes a mutating statement.
    """
    conn = sqlite3.connect(db_path, factory=_CoordinatedConnection)
    conn._basil_operation_name = operation_name
    conn.row_factory = sqlite3.Row
    _configure_sync_connection(conn)

    if ensure_schema:
        _ensure_tables(conn)

    return conn


async def get_async_connection(
    db_path: str,
    *,
    ensure_schema: bool = True,
    foreign_keys: bool = True,
) -> aiosqlite.Connection:
    """Get an async database connection with proper configuration.

    The underlying SQLite connection joins the same per-database-file write coordinator as ``get_sync_connection`` the first time it executes a mutating statement, so async and sync writers to the same file are serialized against each other. Async writes are labeled ``"async_write"`` in coordinator diagnostics; see the module docstring for why a per-call label is not threaded through this path. Set ``foreign_keys=False`` only for a legacy caller whose existing persisted data behavior depends on SQLite's default disabled foreign-key enforcement.
    """
    conn = await aiosqlite.connect(db_path, factory=_AsyncCoordinatedConnection)
    conn.row_factory = aiosqlite.Row
    await _configure_async_connection(conn, foreign_keys=foreign_keys)

    if ensure_schema:
        cursor = await conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='activities'"
        )
        if await cursor.fetchone() is None:
            for statement in get_schema_statements():
                await conn.execute(statement)
            await conn.commit()

    return conn


def run_read_transaction(
    db_path: str,
    body: Callable[[sqlite3.Connection], T],
    *,
    ensure_schema: bool = True,
) -> T:
    """Run a read-only callback against one configured connection."""
    conn = get_sync_connection(db_path, ensure_schema=ensure_schema)
    try:
        return body(conn)
    finally:
        conn.close()


def run_write_transaction(
    db_path: str,
    operation_name: str,
    body: Callable[[sqlite3.Connection], T],
    *,
    ensure_schema: bool = True,
) -> T:
    """Run one immediate write transaction.

    The connection joins the shared per-database-file write coordinator
    automatically when it executes ``BEGIN IMMEDIATE`` (see
    ``_CoordinatedConnection``), so this function no longer manages a
    separate lock itself. The retry loop below now only guards against a
    SQLite-level lock held by something outside this process's coordinator
    (e.g. a second Basil process, or a manual sqlite3 session against the
    same file) -- same-process contention is already serialized before
    ``BEGIN IMMEDIATE`` is admitted.
    """
    deadline = time.monotonic() + WRITE_OPERATION_CEILING_SECONDS
    retry_count = 0
    delay = INITIAL_RETRY_DELAY_SECONDS

    while True:
        conn: sqlite3.Connection | None = None
        try:
            conn = get_sync_connection(
                db_path, ensure_schema=ensure_schema, operation_name=operation_name
            )
            conn.execute("BEGIN IMMEDIATE")
            result = body(conn)
            conn.commit()
            return result
        except SQLiteWriteTimeoutError:
            raise
        except Exception as exc:
            if conn is not None:
                try:
                    conn.rollback()
                except Exception:
                    pass
            if (
                _is_lock_error(exc)
                and time.monotonic() < deadline
                and retry_count < MAX_WRITE_RETRY_ATTEMPTS
            ):
                retry_count += 1
                logger.warning(
                    "SQLite write retry for %s (attempt %s, wait %.0fms, db=%s): %s",
                    operation_name,
                    retry_count,
                    delay * 1000,
                    db_path,
                    exc,
                )
                if conn is not None:
                    conn.close()
                    conn = None
                time.sleep(delay)
                delay = min(delay * 2, MAX_RETRY_DELAY_SECONDS)
                continue
            raise
        finally:
            if conn is not None:
                conn.close()


async def run_write_transaction_async(
    db_path: str,
    operation_name: str,
    body: Callable[[sqlite3.Connection], T],
    *,
    ensure_schema: bool = True,
) -> T:
    """Async wrapper around ``run_write_transaction``."""
    return await asyncio.to_thread(
        run_write_transaction,
        db_path,
        operation_name,
        body,
        ensure_schema=ensure_schema,
    )


def generate_context_hash(
    app_name: str,
    window_title: Optional[str],
    extracted_text: Optional[str],
) -> str:
    """Generate a SHA-256 context hash for grouping similar activities."""
    context = f"{app_name}:{window_title or ''}:{extracted_text or ''}"
    return hashlib.sha256(context.encode()).hexdigest()


def _ensure_tables(conn: sqlite3.Connection) -> None:
    """Create any missing required tables using the canonical schema."""
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name IN ({})".format(
            ",".join("?" * len(REQUIRED_TABLES))
        ),
        REQUIRED_TABLES,
    )
    existing = {row[0] for row in cursor.fetchall()}
    missing = set(REQUIRED_TABLES) - existing

    if missing:
        logger.info("Missing tables detected: %s, initializing schema", missing)
        statements = get_schema_statements()
        for statement in statements:
            if "CREATE INDEX" in statement.upper() or "CREATE UNIQUE INDEX" in statement.upper():
                continue
            conn.execute(statement)
        for statement in statements:
            if "CREATE INDEX" in statement.upper() or "CREATE UNIQUE INDEX" in statement.upper():
                conn.execute(statement)
        conn.commit()
        logger.info("Database schema initialized successfully")


def reset_sqlite_connection_state_for_tests() -> None:
    """Clear process-local write coordinators and WAL initialization tracking."""
    with _write_coordinators_guard:
        _write_coordinators.clear()
    with _initialized_wal_guard:
        _initialized_wal_databases.clear()
